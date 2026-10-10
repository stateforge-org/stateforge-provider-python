"""Discover typed declarations and freeze one validated P1 snapshot."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from typing import Any, get_type_hints

from google.protobuf.json_format import MessageToDict, ParseDict
from pydantic.errors import PydanticUndefinedAnnotation, PydanticUserError
from pydantic.json_schema import JsonSchemaMode
from stateforge_protocol.sfp.manifest.v1 import contract as manifest_contract
from stateforge_protocol.sfp.manifest.v1 import manifest_pb2

from stateforge_provider._runtime.configuration import (
    DEFAULT_RUNTIME_LIMITS,
    ProviderRuntimeLimits,
)
from stateforge_provider._runtime.identity import ProviderEndpointIdentity
from stateforge_provider._services.manifest.limits import (
    MAX_CANONICAL_REVISION_PREIMAGE_BYTES,
    MAX_EMBEDDED_JSON_DEPTH,
    MAX_RESPONSE_BYTES,
)
from stateforge_provider._services.manifest.schema import (
    JSON_SCHEMA_DRAFT_2020_12_URI,
    ManifestError,
    bounded_json,
    canonical_bytes,
    validate_schema,
    validate_structure,
)
from stateforge_provider.declarations import (
    Platform,
    ProviderModel,
    RuntimeRequirement,
    Trigger,
    _Operation,
)


def _model_schema(
    model: object,
    path: str,
    mode: JsonSchemaMode,
    limits: ProviderRuntimeLimits,
) -> dict[str, Any]:
    if not isinstance(model, type) or not issubclass(model, ProviderModel):
        raise ManifestError(f"{path}: must be a ProviderModel subclass")
    try:
        schema = model.model_json_schema(mode=mode)
    except (
        PydanticUndefinedAnnotation,
        PydanticUserError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        raise ManifestError(f"{path}: cannot derive model schema") from None
    schema.setdefault("$schema", JSON_SCHEMA_DRAFT_2020_12_URI)
    schema.setdefault("type", "object")
    validate_schema(schema, path, limits=limits)
    return schema


def _sequence(owner: type, name: str, limit: int) -> tuple[Any, ...]:
    value = getattr(owner, name, ())
    if not isinstance(value, tuple) or len(value) > limit:
        raise ManifestError(f"{name}: must be a bounded tuple")
    return value


def _mro_namespace(owner: type) -> dict[str, Any]:
    """Collect the class namespace used where a method was declared."""
    namespace: dict[str, Any] = {}
    for base in reversed(owner.__mro__):
        namespace.update(vars(base))
    return namespace


# Keep discovery and its rejection rules adjacent.
def _operations(  # noqa: PLR0912
    owner: type, limits: ProviderRuntimeLimits
) -> dict[str, Any]:
    methods: dict[str, tuple[Any, type]] = {}
    for base in reversed(owner.__mro__):
        for name, method in vars(base).items():
            prior = methods.get(name)
            if getattr(
                prior[0] if prior is not None else None,
                "__stateforge_operation__",
                None,
            ) is not None and not isinstance(
                getattr(method, "__stateforge_operation__", None), _Operation
            ):
                raise ManifestError(
                    "operations: overrides must redeclare metadata"
                )
            methods[name] = (method, base)
    declared_methods: list[tuple[Any, type, _Operation]] = []
    for method, declaring_class in methods.values():
        metadata = getattr(method, "__stateforge_operation__", None)
        if isinstance(metadata, _Operation):
            declared_methods.append((method, declaring_class, metadata))
    if len(declared_methods) > manifest_contract.MAX_OPERATIONS:
        raise ManifestError("operations: entry limit exceeded")

    declarations: dict[str, Any] = {}
    for method, declaring_class, metadata in declared_methods:
        path = f"operations[{len(declarations)}]"
        validate_structure(metadata.identifier, "identifier", path)
        if metadata.identifier in declarations:
            raise ManifestError(f"{path}: duplicate operation identifier")
        if not inspect.iscoroutinefunction(method):
            raise ManifestError(f"{path}: operation method must be async")
        parameters = tuple(inspect.signature(method).parameters)
        if parameters != ("self", "request"):
            raise ManifestError(f"{path}: expected (self, request) signature")
        try:
            annotations = get_type_hints(
                method,
                localns=_mro_namespace(declaring_class),
            )
        except (NameError, TypeError):
            raise ManifestError(
                f"{path}: unresolved model annotations"
            ) from None
        roles = metadata.implements
        if (
            not isinstance(roles, tuple)
            or len(roles) > manifest_contract.MAX_PROFILE_CLAIMS_PER_OPERATION
        ):
            raise ManifestError(f"{path}.implements: must be a bounded tuple")
        for role in roles:
            validate_structure(role, "dottedIdentifier", f"{path}.implements")
        if len(set(roles)) != len(roles):
            raise ManifestError(f"{path}.implements: duplicate role")
        declarations[metadata.identifier] = {
            "inputSchema": _model_schema(
                annotations.get("request"),
                f"{path}.input",
                "validation",
                limits,
            ),
            "resultSchema": _model_schema(
                annotations.get("return"),
                f"{path}.result",
                "serialization",
                limits,
            ),
            "implements": sorted(roles),
        }
    return declarations


def _check_combined_schema_budget(
    configuration: dict[str, Any],
    operations: dict[str, Any],
    triggers: dict[str, Any],
) -> None:
    """Bound all generated schemas before validating the full manifest."""
    schemas = [configuration]
    schemas.extend(
        schema
        for declaration in operations.values()
        for schema in (
            declaration["inputSchema"],
            declaration["resultSchema"],
        )
    )
    schemas.extend(
        declaration["payloadSchema"] for declaration in triggers.values()
    )
    total = 0
    for schema in schemas:
        total += len(canonical_bytes(schema))
        if total > MAX_CANONICAL_REVISION_PREIMAGE_BYTES:
            raise ManifestError(
                "manifest: combined schema size limit exceeded"
            )


@dataclass(frozen=True, slots=True)
class ManifestDeclaration:
    """Freeze validated declaration bytes before author startup."""

    document: bytes

    @classmethod
    def discover(
        cls,
        owner: type,
        *,
        limits: ProviderRuntimeLimits = DEFAULT_RUNTIME_LIMITS,
    ) -> ManifestDeclaration:
        """Inspect class metadata without invoking business methods."""
        platforms = _sequence(
            owner, "platforms", manifest_contract.MAX_PLATFORMS
        )
        if any(not isinstance(item, Platform) for item in platforms):
            raise ManifestError("platforms: expected Platform declarations")
        platform_documents = [
            {
                "operatingSystem": item.operating_system,
                "architecture": item.architecture,
            }
            for item in platforms
        ]
        for item in platform_documents:
            validate_structure(item, "platform", "platforms")
        requirements = {}
        for index, requirement in enumerate(
            _sequence(
                owner,
                "runtime_requirements",
                manifest_contract.MAX_RUNTIME_REQUIREMENTS,
            )
        ):
            path = f"runtime_requirements[{index}]"
            if not isinstance(requirement, RuntimeRequirement):
                raise ManifestError(f"{path}: expected RuntimeRequirement")
            validate_structure(
                requirement.identifier, "dottedIdentifier", path
            )
            if requirement.identifier in requirements:
                raise ManifestError(
                    f"{path}: duplicate requirement identifier"
                )
            requirements[requirement.identifier] = {
                "description": requirement.description,
                "versionConstraint": requirement.version_constraint,
            }
        triggers = {}
        for index, trigger in enumerate(
            _sequence(owner, "triggers", manifest_contract.MAX_TRIGGERS)
        ):
            path = f"triggers[{index}]"
            if not isinstance(trigger, Trigger):
                raise ManifestError(f"{path}: expected Trigger")
            validate_structure(trigger.identifier, "identifier", path)
            if trigger.identifier in triggers:
                raise ManifestError(f"{path}: duplicate trigger identifier")
            triggers[trigger.identifier] = {
                "payloadSchema": _model_schema(
                    trigger.payload, path, "serialization", limits
                )
            }
        operations = _operations(owner, limits)
        configuration = _model_schema(
            getattr(owner, "configuration_model", ProviderModel),
            "configuration_schema",
            "validation",
            limits,
        )
        _check_combined_schema_budget(configuration, operations, triggers)
        document = {
            "providerIdentity": getattr(owner, "identity", None),
            "implementationVersion": getattr(owner, "version", None),
            "displayName": getattr(owner, "display_name", None),
            "platforms": sorted(
                platform_documents,
                key=lambda item: (
                    item["operatingSystem"],
                    item["architecture"],
                ),
            ),
            "runtimeRequirements": requirements,
            "triggers": triggers,
            "operations": operations,
            "configurationSchema": configuration,
        }
        bounded_json(
            document,
            "manifest",
            depth_limit=MAX_EMBEDDED_JSON_DEPTH + 4,
            limits=limits,
        )
        # Bound canonical content before recursive metaschema processing.
        content = canonical_bytes(document)
        validate_structure(document, "providerManifest", "manifest")
        return cls(content)

    def snapshot(self, identity: ProviderEndpointIdentity) -> ManifestSnapshot:
        """Construct the exchange after identity allocation and startup."""
        manifest = ParseDict(
            json.loads(self.document), manifest_pb2.ProviderManifest()
        )
        projected = MessageToDict(
            manifest, always_print_fields_with_no_presence=True
        )
        preimage = canonical_bytes(
            {
                "manifest": projected,
                "manifestSchemaVersion": 1,
                "providerInstanceId": str(identity.provider_instance_id),
            }
        )
        response = manifest_pb2.GetManifestResponse(
            provider_instance_id=str(identity.provider_instance_id),
            endpoint_generation=identity.endpoint_generation,
            manifest_schema_version=1,
            manifest_revision="sha256:" + hashlib.sha256(preimage).hexdigest(),
            manifest=manifest,
            # Reserve the largest legal UTF-8 session header before serving.
            session_id="\U0001f600" * 255,
        )
        if response.ByteSize() > MAX_RESPONSE_BYTES:
            raise ManifestError("manifest: response size limit exceeded")
        validate_structure(
            MessageToDict(response, always_print_fields_with_no_presence=True),
            "getManifestResponse",
            "response",
        )
        response.ClearField("session_id")
        return ManifestSnapshot(response.SerializeToString())


@dataclass(frozen=True, slots=True)
class ManifestSnapshot:
    """Retain an immutable serialized response template."""

    document: bytes

    def response(self, session_id: str) -> manifest_pb2.GetManifestResponse:
        """Return a fresh complete envelope bound to this validated call."""
        response = manifest_pb2.GetManifestResponse.FromString(self.document)
        response.session_id = session_id
        return response
