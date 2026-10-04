"""Manifest declaration, schema security, resource, and revision evidence."""

import copy
import json
import runpy
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from google.protobuf.json_format import MessageToDict
from pydantic import ConfigDict, Field, SecretStr
from stateforge_protocol.sfp.manifest.v1 import contract as manifest_contract

from stateforge_rpc import (
    ManifestError,
    Platform,
    Provider,
    ProviderModel,
    RuntimeRequirement,
    Trigger,
    operation,
)
from stateforge_rpc._runtime.configuration import DEFAULT_RUNTIME_LIMITS
from stateforge_rpc._runtime.identity import ProviderEndpointIdentity
from stateforge_rpc._services.manifest.declaration import ManifestDeclaration
from stateforge_rpc._services.manifest.limits import (
    MAX_CANONICAL_REVISION_PREIMAGE_BYTES,
)
from stateforge_rpc._services.manifest.schema import (
    bounded_json,
    canonical_bytes,
    contract_validator,
    validate_schema,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "manifest"
_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_INSTANCE = UUID("7f7db7d8-68b4-4f71-9769-065b5c4f941c")


class _Input(ProviderModel):
    reference: str


class _Result(ProviderModel):
    resolved: str


class _Configuration(ProviderModel):
    token: SecretStr
    endpoint: str


class _Minimal(Provider):
    identity = "example.reference"
    display_name = "Reference Provider"
    version = "1.2.3-alpha.1+build.7"
    platforms = (Platform("linux", "x86_64"),)


class _Representative(_Minimal):
    configuration_model = _Configuration
    triggers = (Trigger("example.reference/changed@1", _Result),)
    runtime_requirements = (
        RuntimeRequirement("runtime.python", "Python interpreter", ">=3.11"),
    )

    @operation("example.reference/resolve@1")
    async def resolve(self, request: _Input) -> _Result:
        raise AssertionError("Manifest discovery must not invoke operations")

    @operation(
        "example.reference/prepare@1",
        implements=(
            "stateforge.backup.v1.prepare",
            "example.reference.custom",
        ),
    )
    async def prepare(self, request: _Input) -> _Result:
        raise AssertionError("No profile execution in R1")

    @operation(
        "example.reference/reconstruct@1",
        implements=("stateforge.disaster_recovery.v1.reconstruct",),
    )
    async def reconstruct(self, request: _Input) -> _Result:
        raise AssertionError("No DR execution in R1")


def _response(owner=_Representative, *, identity=_INSTANCE, generation=1):
    return (
        ManifestDeclaration.discover(owner)
        .snapshot(ProviderEndpointIdentity(identity, generation))
        .response("session")
    )


def test_minimal_and_representative_provider_authoring():
    minimal = _response(_Minimal)
    assert not minimal.manifest.operations
    assert not minimal.manifest.triggers
    assert not minimal.manifest.runtime_requirements
    response = _response()
    document = MessageToDict(
        response, always_print_fields_with_no_presence=True
    )
    declaration = document["manifest"]
    assert declaration["providerIdentity"] == _Representative.identity
    assert declaration["configurationSchema"]["properties"]["token"][
        "writeOnly"
    ]
    assert (
        declaration["runtimeRequirements"]["runtime.python"][
            "versionConstraint"
        ]
        == ">=3.11"
    )
    assert (
        declaration["triggers"]["example.reference/changed@1"][
            "payloadSchema"
        ]["type"]
        == "object"
    )
    assert set(declaration["operations"]["example.reference/prepare@1"]) == {
        "inputSchema",
        "resultSchema",
        "implements",
    }
    assert not declaration["operations"]["example.reference/resolve@1"][
        "implements"
    ]
    assert all(
        set(operation) == {"inputSchema", "resultSchema", "implements"}
        for operation in declaration["operations"].values()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("identity", "wrong"),
        ("identity", "example.Upper"),
        ("version", "1.0"),
        ("version", "1.0.0-01"),
        ("display_name", ""),
        ("display_name", "x" * 256),
        ("platforms", ()),
        ("platforms", (Platform("*", "x86_64"),)),
        ("platforms", (Platform("linux", "x86_64"),) * 2),
        (
            "platforms",
            (Platform("linux", "x86_64"),)
            * (manifest_contract.MAX_PLATFORMS + 1),
        ),
        ("platforms", ("linux",)),
        ("configuration_model", dict),
        ("runtime_requirements", (RuntimeRequirement("bad", "text"),)),
        ("runtime_requirements", (RuntimeRequirement("runtime.test", ""),)),
        (
            "runtime_requirements",
            (RuntimeRequirement("runtime.test", "x", "x" * 256),),
        ),
        (
            "runtime_requirements",
            (RuntimeRequirement("runtime.test", "x"),) * 2,
        ),
        (
            "runtime_requirements",
            (RuntimeRequirement("runtime.test", "x"),)
            * (manifest_contract.MAX_RUNTIME_REQUIREMENTS + 1),
        ),
        ("runtime_requirements", ("wrong",)),
        ("triggers", (Trigger("wrong", _Input),)),
        ("triggers", (Trigger("example.reference/changed@1", _Input),) * 2),
        (
            "triggers",
            (Trigger("example.reference/changed@1", _Input),)
            * (manifest_contract.MAX_TRIGGERS + 1),
        ),
        ("triggers", ("wrong",)),
    ],
)
def test_rejects_invalid_static_metadata(field, value):
    owner = type("Invalid", (_Minimal,), {field: value})
    with pytest.raises(ManifestError):
        _response(owner)


@pytest.mark.parametrize(
    ("identifier", "roles"),
    [
        ("wrong", ()),
        ("example.reference/resolve@0", ()),
        ("example.reference/resolve@01", ()),
        ("example.reference/resolve@1", ("wrong",)),
        ("example.reference/resolve@1", ("example.role.claim",) * 2),
        (
            "example.reference/resolve@1",
            ("example.role.claim",)
            * (manifest_contract.MAX_PROFILE_CLAIMS_PER_OPERATION + 1),
        ),
        ("example.reference/resolve@1", "example.role.claim"),
    ],
)
def test_rejects_invalid_operations_and_roles(identifier, roles):
    class Invalid(_Minimal):
        @operation(identifier, implements=roles)
        async def resolve(self, request: _Input) -> _Result:
            return _Result(resolved=request.reference)

    with pytest.raises(ManifestError):
        _response(Invalid)


def test_operation_inheritance_duplicates_and_overrides():
    class Duplicate(_Representative):
        @operation("example.reference/resolve@1")
        async def another(self, request: _Input) -> _Result:
            return _Result(resolved=request.reference)

    class Undeclared(_Representative):
        async def resolve(self, request: _Input) -> _Result:
            return _Result(resolved=request.reference)

    for owner in (Duplicate, Undeclared):
        with pytest.raises(ManifestError):
            _response(owner)
    assert _response(type("Inherited", (_Representative,), {})) == _response()


def test_inherited_operation_resolves_declaring_class_model_annotations():
    class Models(_Minimal):
        class Request(ProviderModel):
            reference: str

        class Result(ProviderModel):
            resolved: str

    class DeclaringProvider(Models):
        @operation("example.reference/inherited@1")
        async def inherited(self, request: "Request") -> "Result":  # noqa: F821
            return self.Result(resolved=request.reference)

    class InheritedProvider(DeclaringProvider):
        class Request(ProviderModel):
            wrong_model: bool

    document = MessageToDict(
        _response(InheritedProvider),
        always_print_fields_with_no_presence=True,
    )
    declaration = document["manifest"]["operations"][
        "example.reference/inherited@1"
    ]

    assert set(declaration["inputSchema"]["properties"]) == {"reference"}
    assert set(declaration["resultSchema"]["properties"]) == {"resolved"}


def test_rejects_sync_untyped_or_conflicting_operations():
    def sync(self, request: _Input) -> _Result:
        return _Result(resolved=request.reference)

    async def untyped(self, request):
        return request

    async def wrong(self):
        return _Result(resolved="value")

    for handler in (sync, untyped, wrong):
        owner = type(
            "Invalid",
            (_Minimal,),
            {"handler": operation("example.reference/resolve@1")(handler)},
        )
        with pytest.raises(ManifestError):
            _response(owner)
    with pytest.raises(ValueError, match="twice"):
        operation("example.reference/again@1")(sync)


def _schema(**overrides):
    return {"$schema": _DRAFT, "type": "object", **overrides}


def test_versioned_contract_loader_does_not_sniff_individual_fields(
    monkeypatch,
):
    class ContractResource:
        def joinpath(self, name):
            assert name == "manifest.schema.json"
            return self

        def read_text(self):
            return json.dumps(
                {
                    "$schema": _DRAFT,
                    "$defs": {"schemaDocument": {"type": "object"}},
                }
            )

    contract_validator.cache_clear()
    monkeypatch.setattr(
        "stateforge_rpc._services.manifest.schema.files",
        lambda package: ContractResource(),
    )
    try:
        contract_validator("schemaDocument").validate({})
    finally:
        contract_validator.cache_clear()


@pytest.mark.parametrize("keyword", ["$ref", "$dynamicRef"])
@pytest.mark.parametrize(
    "reference",
    [
        "https://invalid.example/schema",
        "file:///tmp/schema",
        "#/$defs/missing",
        "#missing",
        "#/title",
    ],
)
def test_rejects_remote_unresolved_or_non_schema_references(
    keyword, reference
):
    with pytest.raises(ManifestError):
        validate_schema(
            _schema(
                title="not a schema", properties={"x": {keyword: reference}}
            ),
            "configuration",
        )


@pytest.mark.parametrize("keyword", ["$id", "type", "required", "$schema"])
def test_rejects_invalid_or_base_changing_schemas(keyword):
    with pytest.raises(ManifestError):
        validate_schema(_schema(**{keyword: "invalid"}), "configuration")


@pytest.mark.parametrize("keyword", ["default", "examples", "const", "enum"])
@pytest.mark.parametrize(
    "placement",
    [
        "direct",
        "reference",
        "composition",
        "secret_reference",
        "ancestor",
        "child",
    ],
)
def test_rejects_indirect_secret_values_without_echoing_them(
    keyword, placement
):
    secret_value = "sensitive-canary-never-in-errors"  # noqa: S105
    annotation = {
        keyword: [secret_value]
        if keyword in {"examples", "enum"}
        else secret_value
    }
    secret = {"type": "string", "writeOnly": True}
    document = _schema(properties={"token": secret})
    if placement == "direct":
        secret.update(annotation)
    elif placement == "reference":
        secret["$ref"] = "#/$defs/value"
        document["$defs"] = {"value": annotation}
    elif placement == "composition":
        document["properties"]["token"] = {"allOf": [secret, annotation]}
    elif placement == "secret_reference":
        document["$defs"] = {"secret": secret}
        document["properties"]["token"] = {
            "$ref": "#/$defs/secret",
            **annotation,
        }
    elif placement == "ancestor":
        document.update(annotation)
    else:
        secret.update(type="object", properties={"part": annotation})
    with pytest.raises(ManifestError) as error:
        validate_schema(document, "configuration")
    assert secret_value not in str(error.value)


def test_dependent_schema_propagates_secret_policy_to_the_same_instance():
    secret_value = "sensitive-canary-never-in-errors"  # noqa: S105
    document = _schema(
        properties={
            "enabled": {"type": "boolean"},
            "label": {"type": "string", "default": secret_value},
        },
        dependentSchemas={"enabled": {"writeOnly": True}},
    )

    with pytest.raises(ManifestError) as error:
        validate_schema(document, "configuration")

    assert secret_value not in str(error.value)


def test_local_anchors_recursion_and_incidental_schema_data():
    document = _schema(
        **{
            "$defs": {
                "node": {
                    "$anchor": "node",
                    "type": "object",
                    "properties": {"next": {"$ref": "#node"}},
                }
            },
            "properties": {
                "node": {"$ref": "#/$defs/node"},
                "choice": {
                    "enum": [{"$ref": "literal-data", "$id": "literal"}]
                },
            },
        }
    )
    validate_schema(document, "input")
    validate_schema(
        _schema(properties={"anything": True, "nothing": False}), "input"
    )


def test_secret_model_default_fails_closed():
    class Unsafe(ProviderModel):
        token: str = Field(
            default="private", json_schema_extra={"writeOnly": True}
        )

    with pytest.raises(ManifestError):
        _response(
            type("Invalid", (_Minimal,), {"configuration_model": Unsafe})
        )


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), 2**53 + 1, "\ud800"]
)
def test_rejects_non_interoperable_json(value):
    with pytest.raises(ManifestError):
        validate_schema(_schema(examples=[value]), "input")


def test_rejects_excessive_nesting_and_bounded_serialization():
    document = _schema()
    cursor = document
    for _ in range(65):
        cursor["not"] = {}
        cursor = cursor["not"]
    with pytest.raises(ManifestError, match="nesting"):
        validate_schema(document, "input")
    with pytest.raises(ManifestError, match="resource"):
        bounded_json(
            {"x": "x" * (MAX_CANONICAL_REVISION_PREIMAGE_BYTES + 1)},
            "input",
        )
    with pytest.raises(ManifestError, match="preimage"):
        canonical_bytes(
            {"x": "\x00" * (MAX_CANONICAL_REVISION_PREIMAGE_BYTES // 2)}
        )
    with pytest.raises(ManifestError, match="resource"):
        bounded_json(
            [None] * (DEFAULT_RUNTIME_LIMITS.max_json_nodes + 1),
            "input",
        )
    with pytest.raises(ManifestError, match="non-JSON"):
        bounded_json({"x": object()}, "input")


def test_matches_unmodified_p1_cross_language_revision_vector():
    vector = json.loads((_FIXTURES / "response.json").read_text())
    declaration = ManifestDeclaration(canonical_bytes(vector["manifest"]))
    response = declaration.snapshot(
        ProviderEndpointIdentity(_INSTANCE, 4)
    ).response(vector["sessionId"])
    projected = MessageToDict(
        response, always_print_fields_with_no_presence=True
    )
    assert projected == vector
    assert (
        canonical_bytes(
            {
                key: projected[key]
                for key in (
                    "manifest",
                    "manifestSchemaVersion",
                    "providerInstanceId",
                )
            }
        )
        == (_FIXTURES / "revision-preimage.json").read_bytes()
    )
    assert response.manifest_revision == (
        "sha256:6bfdf3aedc2d4e45d77d4787cc0e744a488208b2510d81788291f51d24a623e8"
    )


def test_revision_order_generation_identity_and_snapshot_immutability():
    original = _response()
    assert (
        _response(generation=99).manifest_revision
        == original.manifest_revision
    )
    assert (
        _response(identity=uuid4()).manifest_revision
        != original.manifest_revision
    )
    changed = type("Changed", (_Representative,), {"display_name": "Changed"})
    assert _response(changed).manifest_revision != original.manifest_revision
    declaration = ManifestDeclaration.discover(_Representative)
    document = json.loads(declaration.document)
    reordered = dict(reversed(document.items()))
    snapshot = ManifestDeclaration(canonical_bytes(reordered)).snapshot(
        ProviderEndpointIdentity(_INSTANCE, 1)
    )
    first = snapshot.response("A")
    first.manifest.display_name = "tampered"
    second = snapshot.response("B")
    assert second.manifest == original.manifest
    assert second.manifest_revision == original.manifest_revision
    assert second.session_id == "B"
    changed_schema = copy.deepcopy(document)
    changed_schema["operations"]["example.reference/resolve@1"][
        "resultSchema"
    ]["description"] = "Updated contract"
    changed_snapshot = ManifestDeclaration(
        canonical_bytes(changed_schema)
    ).snapshot(ProviderEndpointIdentity(_INSTANCE, 1))
    assert (
        changed_snapshot.response("C").manifest_revision
        != original.manifest_revision
    )


def test_map_and_set_like_order_does_not_change_revision():
    class First(_Representative):
        platforms = (Platform("linux", "x86_64"), Platform("darwin", "arm64"))
        runtime_requirements = (
            RuntimeRequirement("runtime.a", "A"),
            RuntimeRequirement("runtime.b", "B"),
        )

    class Second(First):
        platforms = tuple(reversed(First.platforms))
        runtime_requirements = tuple(reversed(First.runtime_requirements))

    assert (
        _response(First).manifest_revision
        == _response(Second).manifest_revision
    )


def test_schema_array_order_remains_meaningful():
    class First(ProviderModel):
        model_config = ConfigDict(
            json_schema_extra={"examples": [{"n": 1}, {"n": 2}]}
        )

    class Second(First):
        model_config = ConfigDict(
            json_schema_extra={"examples": [{"n": 2}, {"n": 1}]}
        )

    first = type("FirstProvider", (_Minimal,), {"configuration_model": First})
    second = type(
        "SecondProvider", (_Minimal,), {"configuration_model": Second}
    )
    assert (
        _response(first).manifest_revision
        != _response(second).manifest_revision
    )


def test_operation_count_checked_before_schema_generation():
    async def handler(self, request: _Input) -> _Result:
        return _Result(resolved=request.reference)

    decorated = operation("example.reference/resolve@1")(handler)
    owner = type(
        "Oversized",
        (_Minimal,),
        {
            f"handler_{index}": decorated
            for index in range(manifest_contract.MAX_OPERATIONS + 1)
        },
    )
    with pytest.raises(ManifestError, match="entry limit"):
        _response(owner)


def test_combined_model_schema_budget_stops_discovery():
    class Large(ProviderModel):
        model_config = ConfigDict(
            json_schema_extra={"description": "x" * 400_000}
        )

    class Oversized(_Minimal):
        configuration_model = Large
        triggers = (
            Trigger("example.reference/first@1", Large),
            Trigger("example.reference/second@1", Large),
        )

    with pytest.raises(ManifestError, match="combined schema"):
        _response(Oversized)


def test_response_limit_checked_before_publication(monkeypatch):
    monkeypatch.setattr(
        "stateforge_rpc._services.manifest.declaration.MAX_RESPONSE_BYTES",
        128,
    )
    with pytest.raises(ManifestError, match="response size"):
        _response()


def test_local_schema_node_limit_and_nested_dialect():
    with pytest.raises(ManifestError, match="node limit"):
        validate_schema(
            _schema(
                **{
                    "$defs": {
                        f"n{i}": {}
                        for i in range(DEFAULT_RUNTIME_LIMITS.max_schema_nodes)
                    }
                }
            ),
            "input",
        )
    with pytest.raises(ManifestError, match="nested schema dialect"):
        validate_schema(
            _schema(
                properties={
                    "x": {"$schema": "https://json-schema.org/draft-07/schema"}
                }
            ),
            "input",
        )


def test_provider_owned_schema_limits_are_configurable():
    json_limits = replace(DEFAULT_RUNTIME_LIMITS, max_json_nodes=2)
    with pytest.raises(ManifestError, match="resource limit"):
        bounded_json({"value": None}, "input", limits=json_limits)

    schema_limits = replace(DEFAULT_RUNTIME_LIMITS, max_schema_nodes=1)
    with pytest.raises(ManifestError, match="schema node limit"):
        validate_schema(
            _schema(properties={"value": {}}),
            "input",
            limits=schema_limits,
        )


def test_unresolvable_type_annotations_and_invalid_model_generation():
    class Unresolved(_Minimal):
        @operation("example.reference/resolve@1")
        async def resolve(self, request: "MissingModel") -> _Result:  # noqa: F821
            raise AssertionError

    with pytest.raises(ManifestError, match="unresolved model"):
        _response(Unresolved)

    class InvalidModel(ProviderModel):
        @classmethod
        def model_json_schema(cls, **kwargs):
            raise ValueError("sensitive-canary")

    with pytest.raises(ManifestError, match="cannot derive") as error:
        _response(
            type("Invalid", (_Minimal,), {"configuration_model": InvalidModel})
        )
    assert "sensitive-canary" not in str(error.value)


def test_pydantic_json_schema_failures_use_the_manifest_error_boundary():
    class UnsupportedSchema(ProviderModel):
        callback: Callable[[], None]

    class IncompleteSchema(ProviderModel):
        missing: "MissingSchemaType"  # noqa: F821

    for schema_model in (UnsupportedSchema, IncompleteSchema):
        owner = type(
            "Invalid",
            (_Minimal,),
            {"configuration_model": schema_model},
        )

        with pytest.raises(ManifestError, match="cannot derive model schema"):
            _response(owner)


def test_documented_reference_example_builds_a_valid_manifest():
    example = runpy.run_path(
        str(Path(__file__).parents[1] / "examples" / "reference_provider.py")
    )
    response = _response(example["ReferenceProvider"])
    assert "example.reference/normalize@1" in response.manifest.operations
    assert "example.reference/changed@1" in response.manifest.triggers
