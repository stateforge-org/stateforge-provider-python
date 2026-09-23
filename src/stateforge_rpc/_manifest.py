"""Discover typed declarations and freeze one validated P1 snapshot."""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from typing import Any, get_type_hints

from google.protobuf.json_format import MessageToDict, ParseDict
from pydantic.json_schema import JsonSchemaMode
from stateforge_protocol.sfp.manifest.v1 import manifest_pb2

from stateforge_rpc._identity import ProviderEndpointIdentity
from stateforge_rpc._schema import (
    MAX_DEPTH,
    MAX_RESPONSE_BYTES,
    ManifestError,
    bounded_json,
    canonical_bytes,
    validate_schema,
    validate_structure,
)
from stateforge_rpc.declarations import (
    Platform,
    ProviderModel,
    RuntimeRequirement,
    Trigger,
    _Operation,
)

_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_MAX_ENTRIES = 1024
_MAX_ROLES = 64
_MAX_PLATFORMS = 256


def _model_schema(
    model: object, path: str, mode: JsonSchemaMode
) -> dict[str, Any]:
    if not isinstance(model, type) or not issubclass(model, ProviderModel):
        raise ManifestError(f"{path}: must be a ProviderModel subclass")
    try:
        schema = model.model_json_schema(mode=mode)
    except (TypeError, ValueError, RecursionError):
        raise ManifestError(f"{path}: cannot derive model schema") from None
    schema.setdefault("$schema", _DRAFT)
    schema.setdefault("type", "object")
    validate_schema(schema, path)
    return schema


def _sequence(owner: type, name: str, limit: int) -> tuple[Any, ...]:
    value = getattr(owner, name, ())
    if not isinstance(value, tuple) or len(value) > limit:
        raise ManifestError(f"{name}: must be a bounded tuple")
    return value


# Keep discovery and its rejection rules adjacent.
def _operations(owner: type) -> dict[str, Any]:  # noqa: PLR0912
    methods: dict[str, Any] = {}
    for base in reversed(owner.__mro__):
        for name, method in vars(base).items():
            prior = methods.get(name)
            if getattr(
                prior, "__stateforge_operation__", None
            ) is not None and not isinstance(
                getattr(method, "__stateforge_operation__", None), _Operation
            ):
                raise ManifestError(
                    "operations: overrides must redeclare metadata"
                )
            methods[name] = method
    declarations: dict[str, Any] = {}
    for method in methods.values():
        metadata = getattr(method, "__stateforge_operation__", None)
        if not isinstance(metadata, _Operation):
            continue
        path = f"operations[{len(declarations)}]"
        if len(declarations) >= _MAX_ENTRIES:
            raise ManifestError("operations: entry limit exceeded")
        validate_structure(metadata.identifier, "identifier", path)
        if metadata.identifier in declarations:
            raise ManifestError(f"{path}: duplicate operation identifier")
        if not inspect.iscoroutinefunction(method):
            raise ManifestError(f"{path}: operation method must be async")
        parameters = tuple(inspect.signature(method).parameters)
        if parameters != ("self", "request"):
            raise ManifestError(f"{path}: expected (self, request) signature")
        try:
            annotations = get_type_hints(method, localns=dict(vars(owner)))
        except (NameError, TypeError):
            raise ManifestError(
                f"{path}: unresolved model annotations"
            ) from None
        roles = metadata.implements
        if not isinstance(roles, tuple) or len(roles) > _MAX_ROLES:
            raise ManifestError(f"{path}.implements: must be a bounded tuple")
        for role in roles:
            validate_structure(role, "dottedIdentifier", f"{path}.implements")
        if len(set(roles)) != len(roles):
            raise ManifestError(f"{path}.implements: duplicate role")
        declarations[metadata.identifier] = {
            "inputSchema": _model_schema(
                annotations.get("request"), f"{path}.input", "validation"
            ),
            "resultSchema": _model_schema(
                annotations.get("return"), f"{path}.result", "serialization"
            ),
            "implements": sorted(roles),
        }
    return declarations


@dataclass(frozen=True, slots=True)
class ManifestDeclaration:
    """Freeze validated declaration bytes before author startup."""

    document: bytes

    @classmethod
    def discover(cls, owner: type) -> ManifestDeclaration:
        """Inspect class metadata without invoking business methods."""
        targets = _sequence(owner, "target_kinds", _MAX_ENTRIES)
        for target in targets:
            validate_structure(target, "identifier", "target_kinds")
        platforms = _sequence(owner, "platforms", _MAX_PLATFORMS)
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
            _sequence(owner, "runtime_requirements", _MAX_ENTRIES)
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
            _sequence(owner, "triggers", _MAX_ENTRIES)
        ):
            path = f"triggers[{index}]"
            if not isinstance(trigger, Trigger):
                raise ManifestError(f"{path}: expected Trigger")
            validate_structure(trigger.identifier, "identifier", path)
            if trigger.identifier in triggers:
                raise ManifestError(f"{path}: duplicate trigger identifier")
            triggers[trigger.identifier] = {
                "payloadSchema": _model_schema(
                    trigger.payload, path, "serialization"
                )
            }
        document = {
            "providerIdentity": getattr(owner, "identity", None),
            "implementationVersion": getattr(owner, "version", None),
            "displayName": getattr(owner, "display_name", None),
            "targetKinds": sorted(targets),
            "platforms": sorted(
                platform_documents,
                key=lambda item: (
                    item["operatingSystem"],
                    item["architecture"],
                ),
            ),
            "runtimeRequirements": requirements,
            "triggers": triggers,
            "operations": _operations(owner),
            "configurationSchema": _model_schema(
                getattr(owner, "configuration_model", ProviderModel),
                "configuration_schema",
                "validation",
            ),
        }
        bounded_json(document, "manifest", depth_limit=MAX_DEPTH + 4)
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
