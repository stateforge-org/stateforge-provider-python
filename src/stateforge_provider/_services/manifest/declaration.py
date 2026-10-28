"""Discover typed declarations and freeze one validated P1 snapshot."""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import Any, get_args, get_origin, get_type_hints

from google.protobuf.json_format import MessageToDict, ParseDict
from pydantic.errors import PydanticUndefinedAnnotation, PydanticUserError
from pydantic.json_schema import JsonSchemaMode
from stateforge_protocol.sfp.manifest.v1 import contract as manifest_contract
from stateforge_protocol.sfp.manifest.v1 import manifest_pb2
from stateforge_protocol.sfp.manifest.v1.validation import (
    JSON_SCHEMA_DRAFT_2020_12_URI,
    ManifestValidationError,
    ManifestValidationLimits,
    canonical_bytes,
    compute_manifest_revision,
    validate_manifest_document,
    validate_manifest_response,
    validate_schema,
    validate_structure,
)

from stateforge_provider._runtime.configuration import (
    DEFAULT_RUNTIME_LIMITS,
    ProviderRuntimeLimits,
)
from stateforge_provider._runtime.identity import ProviderEndpointIdentity
from stateforge_provider._services.manifest.errors import ManifestError
from stateforge_provider.declarations import (
    Platform,
    ProviderModel,
    RuntimeRequirement,
    Trigger,
    _effective_methods,
    _mro_namespace,
    _Operation,
)
from stateforge_provider.triggers import _TriggerSource


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
    validate_schema(schema, path, limits=_validation_limits(limits))
    return schema


def _sequence(owner: type, name: str, limit: int) -> tuple[Any, ...]:
    value = getattr(owner, name, ())
    if not isinstance(value, tuple) or len(value) > limit:
        raise ManifestError(f"{name}: must be a bounded tuple")
    return value


# Keep discovery and its rejection rules adjacent.
def _operations(owner: type, limits: ProviderRuntimeLimits) -> dict[str, Any]:
    methods, metadata_erased = _effective_methods(
        owner,
        metadata_attribute="__stateforge_operation__",
        metadata_type=_Operation,
    )
    if metadata_erased:
        raise ManifestError("operations: overrides must redeclare metadata")
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


def _triggers(  # noqa: PLR0912
    owner: type,
    limits: ProviderRuntimeLimits,
) -> tuple[
    dict[str, Any],
    tuple[Trigger, ...],
    tuple[tuple[str, str], ...],
]:
    """Discover explicit and decorated triggers through one path."""
    declared: list[tuple[Trigger, str | None]] = []
    for index, item in enumerate(
        _sequence(owner, "triggers", manifest_contract.MAX_TRIGGERS)
    ):
        if not isinstance(item, Trigger):
            raise ManifestError(f"triggers[{index}]: expected Trigger")
        declared.append((item, None))

    methods, metadata_erased = _effective_methods(
        owner,
        metadata_attribute="__stateforge_trigger_source__",
        metadata_type=_TriggerSource,
    )
    if metadata_erased:
        raise ManifestError("triggers: overrides must redeclare metadata")
    for source_name, (method, declaring_class) in methods.items():
        metadata = getattr(method, "__stateforge_trigger_source__", None)
        if not isinstance(metadata, _TriggerSource):
            continue
        path = f"triggers.{source_name}"
        if not inspect.isasyncgenfunction(method):
            raise ManifestError(f"{path}: must be an async generator")
        signature = inspect.signature(method)
        if tuple(signature.parameters) != ("self",):
            raise ManifestError(f"{path}: expected a (self) signature")
        try:
            annotations = get_type_hints(
                method,
                globalns=vars(inspect.getmodule(method) or {}),
                localns=_mro_namespace(declaring_class),
            )
        except (NameError, TypeError):
            raise ManifestError(
                f"{path}: unresolved model annotations"
            ) from None
        return_annotation = annotations.get("return")
        if get_origin(return_annotation) not in (
            AsyncIterator,
            AsyncGenerator,
        ):
            raise ManifestError(
                f"{path}: return annotation must be "
                "AsyncIterator[ProviderModel]"
            )
        arguments = get_args(return_annotation)
        payload = arguments[0] if arguments else None
        if not isinstance(payload, type) or not issubclass(
            payload, ProviderModel
        ):
            raise ManifestError(
                f"{path}: return annotation must contain a ProviderModel"
            )
        declared.append((Trigger(metadata.identifier, payload), source_name))

    if len(declared) > manifest_contract.MAX_TRIGGERS:
        raise ManifestError("triggers: entry limit exceeded")
    documents: dict[str, Any] = {}
    declarations: dict[str, Trigger] = {}
    sources: list[tuple[str, str]] = []
    for index, (item, declared_source_name) in enumerate(declared):
        path = f"triggers[{index}]"
        validate_structure(item.identifier, "identifier", path)
        if item.identifier in documents:
            raise ManifestError(f"{path}: duplicate trigger identifier")
        payload_schema = _model_schema(
            item.payload,
            path,
            "serialization",
            limits,
        )
        if _contains_write_only(payload_schema):
            raise ManifestError(
                f"{path}: trigger payloads cannot contain secrets"
            )
        documents[item.identifier] = {"payloadSchema": payload_schema}
        declarations[item.identifier] = item
        if declared_source_name is not None:
            sources.append((item.identifier, declared_source_name))
    return (
        documents,
        tuple(declarations[key] for key in sorted(declarations)),
        tuple(sorted(sources)),
    )


def _contains_write_only(value: Any) -> bool:
    """Detect secret-bearing fields anywhere in a trigger payload schema."""
    if isinstance(value, dict):
        return value.get("writeOnly") is True or any(
            _contains_write_only(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_write_only(item) for item in value)
    return False


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
        if total > manifest_contract.MAX_CANONICAL_REVISION_PREIMAGE_BYTES:
            raise ManifestError(
                "manifest: combined schema size limit exceeded"
            )


@dataclass(frozen=True, slots=True)
class ManifestDeclaration:
    """Freeze validated declaration bytes before author startup."""

    document: bytes
    trigger_declarations: tuple[Trigger, ...] = ()
    trigger_source_methods: tuple[tuple[str, str], ...] = ()

    @property
    def trigger_schemas(self) -> dict[str, dict[str, Any]]:
        """Return fresh schemas from the one accepted declaration document."""
        document = json.loads(self.document)
        return {
            identifier: declaration["payloadSchema"]
            for identifier, declaration in document["triggers"].items()
        }

    @classmethod
    def discover(
        cls,
        owner: type,
        *,
        limits: ProviderRuntimeLimits = DEFAULT_RUNTIME_LIMITS,
        additional_runtime_requirements: tuple[RuntimeRequirement, ...] = (),
    ) -> ManifestDeclaration:
        """Inspect class metadata without invoking business methods."""
        try:
            return cls._discover(
                owner,
                limits=limits,
                additional_runtime_requirements=(
                    additional_runtime_requirements
                ),
            )
        except ManifestValidationError as error:
            raise ManifestError(str(error)) from error

    @classmethod
    def _discover(
        cls,
        owner: type,
        *,
        limits: ProviderRuntimeLimits,
        additional_runtime_requirements: tuple[RuntimeRequirement, ...],
    ) -> ManifestDeclaration:
        """Build a declaration while the public boundary translates errors."""
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
        declared_requirements = _sequence(
            owner,
            "runtime_requirements",
            manifest_contract.MAX_RUNTIME_REQUIREMENTS,
        )
        if not isinstance(additional_runtime_requirements, tuple):
            raise ManifestError(
                "runtime_requirements: additional declarations must be a tuple"
            )
        combined_requirements = (
            declared_requirements + additional_runtime_requirements
        )
        if (
            len(combined_requirements)
            > manifest_contract.MAX_RUNTIME_REQUIREMENTS
        ):
            raise ManifestError("runtime_requirements: entry limit exceeded")
        requirements = {}
        for index, requirement in enumerate(combined_requirements):
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
        triggers, trigger_declarations, trigger_sources = _triggers(
            owner,
            limits,
        )
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
        contract_limits = _validation_limits(limits)
        content = validate_manifest_document(
            document,
            limits=contract_limits,
        )
        return cls(content, trigger_declarations, trigger_sources)

    def snapshot(self, identity: ProviderEndpointIdentity) -> ManifestSnapshot:
        """Construct the exchange after identity allocation and startup."""
        try:
            return self._snapshot(identity)
        except ManifestValidationError as error:
            raise ManifestError(str(error)) from error

    def _snapshot(
        self, identity: ProviderEndpointIdentity
    ) -> ManifestSnapshot:
        """Build a snapshot while the public boundary translates errors."""
        manifest = ParseDict(
            json.loads(self.document), manifest_pb2.ProviderManifest()
        )
        projected = MessageToDict(
            manifest, always_print_fields_with_no_presence=True
        )
        revision = compute_manifest_revision(
            projected,
            1,
            str(identity.provider_instance_id),
        )
        response = manifest_pb2.GetManifestResponse(
            provider_instance_id=str(identity.provider_instance_id),
            endpoint_generation=identity.endpoint_generation,
            manifest_schema_version=1,
            manifest_revision=revision,
            manifest=manifest,
            # Reserve the largest legal UTF-8 session header before serving.
            session_id=(
                "\U0001f600" * manifest_contract.MAX_SESSION_ID_CODE_POINTS
            ),
        )
        if response.ByteSize() > manifest_contract.MAX_RESPONSE_BYTES:
            raise ManifestError("manifest: response size limit exceeded")
        validate_manifest_response(response)
        response.ClearField("session_id")
        return ManifestSnapshot(
            response.SerializeToString(),
            self.trigger_declarations,
            self.trigger_source_methods,
        )


@dataclass(frozen=True, slots=True)
class ManifestSnapshot:
    """Retain an immutable serialized response template."""

    document: bytes
    trigger_declarations: tuple[Trigger, ...] = ()
    trigger_source_methods: tuple[tuple[str, str], ...] = ()

    @property
    def manifest_revision(self) -> str:
        """Return the immutable revision served by this snapshot."""
        return manifest_pb2.GetManifestResponse.FromString(
            self.document
        ).manifest_revision

    @property
    def operation_identifiers(self) -> frozenset[str]:
        """Return the operations declared by this immutable snapshot."""
        response = manifest_pb2.GetManifestResponse.FromString(self.document)
        return frozenset(response.manifest.operations)

    @property
    def trigger_identifiers(self) -> frozenset[str]:
        """Return the triggers declared by this immutable snapshot."""
        response = manifest_pb2.GetManifestResponse.FromString(self.document)
        return frozenset(response.manifest.triggers)

    @property
    def trigger_schemas(self) -> dict[str, dict[str, Any]]:
        """Return fresh JSON Schemas keyed by accepted trigger identifier."""
        response = manifest_pb2.GetManifestResponse.FromString(self.document)
        return {
            identifier: MessageToDict(declaration.payload_schema)
            for identifier, declaration in response.manifest.triggers.items()
        }

    def response(self, session_id: str) -> manifest_pb2.GetManifestResponse:
        """Return a fresh complete envelope bound to this validated call."""
        response = manifest_pb2.GetManifestResponse.FromString(self.document)
        response.session_id = session_id
        return response


def _validation_limits(
    limits: ProviderRuntimeLimits,
) -> ManifestValidationLimits:
    """Adapt tighter Provider budgets to the canonical validator."""
    return ManifestValidationLimits(
        max_json_nodes=limits.max_json_nodes,
        max_schema_nodes=limits.max_schema_nodes,
    )
