"""Declaration tests for Provider-owned dynamic runtime requirements."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest
from google.protobuf.json_format import MessageToDict
from stateforge_protocol.sfp.capability_assessment.v1 import contract

from stateforge_provider import (
    ManifestError,
    Platform,
    Provider,
    ProviderModel,
    RequirementCheckResult,
    RuntimeRequirement,
    operation,
    requirement_check,
)
from stateforge_provider import declarations as public_declarations
from stateforge_provider._runtime.identity import ProviderEndpointIdentity
from stateforge_provider._services.capability_assessment import (
    declaration as capability_declaration,
)
from stateforge_provider._services.capability_assessment.declaration import (
    RequirementRegistry,
)
from stateforge_provider._services.manifest import (
    declaration as manifest_declaration,
)
from stateforge_provider._services.manifest.declaration import (
    ManifestDeclaration,
)

_INSTANCE = UUID("7f7db7d8-68b4-4f71-9769-065b5c4f941c")


class _Input(ProviderModel):
    value: str


class _Output(ProviderModel):
    accepted: bool


class _BaseProvider(Provider):
    identity = "example.capability"
    display_name = "Capability Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)


class _DeclaredProvider(_BaseProvider):
    runtime_requirements = (
        RuntimeRequirement("runtime.python", "Python runtime", ">=3.11"),
    )

    @requirement_check(
        "filesystem.var.writable",
        "Writable Provider state directory",
    )
    async def writable(self) -> RequirementCheckResult:
        return RequirementCheckResult.satisfied()

    @operation(
        "example.capability/write@1",
        requires=("filesystem.var.writable",),
    )
    async def write(self, request: _Input) -> _Output:
        return _Output(accepted=bool(request.value))


def _manifest(owner: type[Provider]):
    registry = RequirementRegistry.discover(owner)
    declaration = ManifestDeclaration.discover(
        owner,
        additional_runtime_requirements=registry.manifest_requirements,
    )
    response = declaration.snapshot(
        ProviderEndpointIdentity(_INSTANCE, 1)
    ).response("session")
    return registry, MessageToDict(
        response.manifest,
        always_print_fields_with_no_presence=True,
    )


def test_discovers_checks_references_and_manifest_metadata() -> None:
    registry, manifest = _manifest(_DeclaredProvider)

    assert registry.operation_requirements == (
        ("example.capability/write@1", ("filesystem.var.writable",)),
    )
    assert [item.identifier for item in registry.declarations] == [
        "filesystem.var.writable"
    ]
    assert manifest["runtimeRequirements"] == {
        "filesystem.var.writable": {
            "description": "Writable Provider state directory",
            "versionConstraint": "",
        },
        "runtime.python": {
            "description": "Python runtime",
            "versionConstraint": ">=3.11",
        },
    }
    assert (
        "requires" not in manifest["operations"]["example.capability/write@1"]
    )


@pytest.mark.parametrize(
    ("identifier", "description", "version_constraint"),
    [
        ("invalid", "Valid", ""),
        ("filesystem.var.writable", "", ""),
        ("filesystem.var.writable", "x" * 2_049, ""),
        ("filesystem.var.writable", "Valid", "x" * 256),
    ],
)
def test_rejects_noncanonical_or_oversized_check_metadata(
    identifier: str,
    description: str,
    version_constraint: str,
) -> None:
    class Invalid(_BaseProvider):
        @requirement_check(identifier, description, version_constraint)
        async def check(self) -> RequirementCheckResult:
            return RequirementCheckResult.satisfied()

    with pytest.raises(ManifestError):
        RequirementRegistry.discover(Invalid)


def test_rejects_duplicate_check_identifiers() -> None:
    class Duplicate(_BaseProvider):
        @requirement_check("runtime.shared", "First")
        async def first(self) -> RequirementCheckResult:
            return RequirementCheckResult.satisfied()

        @requirement_check("runtime.shared", "Second")
        async def second(self) -> RequirementCheckResult:
            return RequirementCheckResult.satisfied()

    with pytest.raises(ManifestError, match="duplicate requirement"):
        RequirementRegistry.discover(Duplicate)


@pytest.mark.parametrize(
    "references",
    [
        ("runtime.missing",),
        ("runtime.present", "runtime.present"),
        ("runtime.present",)
        * (contract.MAX_REQUIREMENT_FINDINGS_PER_OPERATION + 1),
        ["runtime.present"],
    ],
)
def test_rejects_invalid_operation_requirement_references(
    references: object,
) -> None:
    class Invalid(_BaseProvider):
        @requirement_check("runtime.present", "Present")
        async def present(self) -> RequirementCheckResult:
            return RequirementCheckResult.satisfied()

        @operation("example.capability/run@1", requires=references)
        async def run(self, request: _Input) -> _Output:
            return _Output(accepted=bool(request.value))

    with pytest.raises(ManifestError):
        RequirementRegistry.discover(Invalid)


def test_rejects_duplicate_static_and_checked_manifest_requirement() -> None:
    class Duplicate(_DeclaredProvider):
        runtime_requirements = (
            RuntimeRequirement(
                "filesystem.var.writable",
                "Duplicate static declaration",
            ),
        )

    registry = RequirementRegistry.discover(Duplicate)
    with pytest.raises(ManifestError, match="duplicate requirement"):
        ManifestDeclaration.discover(
            Duplicate,
            additional_runtime_requirements=registry.manifest_requirements,
        )


def test_rejects_invalid_check_signatures_and_return_annotations() -> None:
    def sync(self) -> RequirementCheckResult:
        return RequirementCheckResult.satisfied()

    async def argument(self, value: str) -> RequirementCheckResult:
        return RequirementCheckResult.satisfied()

    async def wrong_return(self) -> str:
        return "satisfied"

    for method in (sync, argument, wrong_return):
        owner = type(
            "Invalid",
            (_BaseProvider,),
            {
                "check": requirement_check(
                    "runtime.invalid",
                    "Invalid check",
                )(method)
            },
        )
        with pytest.raises(ManifestError):
            RequirementRegistry.discover(owner)


def test_rejects_erased_or_conflicting_inherited_metadata() -> None:
    class Erased(_DeclaredProvider):
        async def writable(self) -> RequirementCheckResult:
            return RequirementCheckResult.satisfied()

    class Conflict(_BaseProvider):
        @operation("example.capability/conflict@1")
        @requirement_check("runtime.conflict", "Conflict")
        async def conflict(self) -> RequirementCheckResult:
            return RequirementCheckResult.satisfied()

    for owner in (Erased, Conflict):
        with pytest.raises(ManifestError):
            RequirementRegistry.discover(owner)


def test_author_result_factories_are_typed_and_immutable() -> None:
    assert RequirementCheckResult.satisfied().outcome.value == "satisfied"
    assert RequirementCheckResult.unsatisfied("later").explanation == "later"
    assert RequirementCheckResult.incompatible("never").outcome.value == (
        "incompatible"
    )
    assert RequirementCheckResult.unknown("unclear").outcome.value == "unknown"
    with pytest.raises(TypeError):
        RequirementCheckResult("satisfied")  # type: ignore[arg-type]
    with pytest.raises(FrozenInstanceError):
        RequirementCheckResult.satisfied().explanation = "changed"  # type: ignore[misc]


def test_declaration_namespace_helper_has_one_owner() -> None:
    """Keep class reflection shared across declaration services."""
    assert (
        capability_declaration._mro_namespace
        is public_declarations._mro_namespace
    )
    assert (
        manifest_declaration._mro_namespace
        is public_declarations._mro_namespace
    )
    assert (
        capability_declaration._effective_methods
        is public_declarations._effective_methods
    )
    assert (
        manifest_declaration._effective_methods
        is public_declarations._effective_methods
    )
