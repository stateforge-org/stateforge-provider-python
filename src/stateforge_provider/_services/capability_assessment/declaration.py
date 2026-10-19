"""Discover requirement checks and operation associations."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import get_type_hints

from stateforge_protocol.sfp.capability_assessment.v1 import (
    contract as capability_contract,
)
from stateforge_protocol.sfp.manifest.v1.validation import (
    ManifestValidationError,
    validate_structure,
)

from stateforge_provider._services.manifest.errors import ManifestError
from stateforge_provider.declarations import (
    RuntimeRequirement,
    _effective_methods,
    _mro_namespace,
    _Operation,
    _RequirementCheck,
)
from stateforge_provider.requirements import RequirementCheckResult

_BoundCheck = Callable[[], Awaitable[RequirementCheckResult]]


@dataclass(frozen=True, slots=True)
class RequirementDeclaration:
    """Retain one validated check declaration and its method name."""

    identifier: str
    description: str
    version_constraint: str
    method_name: str

    def manifest_requirement(self) -> RuntimeRequirement:
        """Return the static metadata published through manifest schema 1."""
        return RuntimeRequirement(
            self.identifier,
            self.description,
            self.version_constraint,
        )


@dataclass(frozen=True, slots=True)
class RequirementRegistry:
    """Freeze checks and Provider-owned operation associations."""

    declarations: tuple[RequirementDeclaration, ...]
    operation_requirements: tuple[tuple[str, tuple[str, ...]], ...]

    @classmethod
    def discover(cls, owner: type) -> RequirementRegistry:
        """Inspect one Provider class without invoking author code."""
        try:
            return cls._discover(owner)
        except ManifestValidationError as error:
            raise ManifestError(str(error)) from error

    @classmethod
    def _discover(  # noqa: PLR0912
        cls, owner: type
    ) -> RequirementRegistry:
        methods, metadata_erased = _effective_methods(
            owner,
            metadata_attribute="__stateforge_requirement_check__",
            metadata_type=_RequirementCheck,
        )
        if metadata_erased:
            raise ManifestError(
                "requirement_checks: overrides must redeclare metadata"
            )
        declarations: list[RequirementDeclaration] = []
        identifiers: set[str] = set()
        for method_name, (method, declaring_class) in methods.items():
            metadata = getattr(
                method, "__stateforge_requirement_check__", None
            )
            if not isinstance(metadata, _RequirementCheck):
                continue
            path = f"requirement_checks[{len(declarations)}]"
            if isinstance(
                getattr(method, "__stateforge_operation__", None), _Operation
            ):
                raise ManifestError(
                    f"{path}: a method cannot be both a requirement check "
                    "and an operation"
                )
            validate_structure(metadata.identifier, "dottedIdentifier", path)
            validate_structure(
                {
                    "description": metadata.description,
                    "versionConstraint": metadata.version_constraint,
                },
                "runtimeRequirement",
                path,
            )
            if metadata.identifier in identifiers:
                raise ManifestError(
                    f"{path}: duplicate requirement identifier"
                )
            if not inspect.iscoroutinefunction(method):
                raise ManifestError(f"{path}: requirement check must be async")
            if tuple(inspect.signature(method).parameters) != ("self",):
                raise ManifestError(f"{path}: expected (self) signature")
            try:
                annotations = get_type_hints(
                    method,
                    localns=_mro_namespace(declaring_class),
                )
            except (NameError, TypeError):
                raise ManifestError(
                    f"{path}: unresolved result annotation"
                ) from None
            if annotations.get("return") is not RequirementCheckResult:
                raise ManifestError(
                    f"{path}: return annotation must be RequirementCheckResult"
                )
            identifiers.add(metadata.identifier)
            declarations.append(
                RequirementDeclaration(
                    identifier=metadata.identifier,
                    description=metadata.description,
                    version_constraint=metadata.version_constraint,
                    method_name=method_name,
                )
            )

        operations: list[tuple[str, tuple[str, ...]]] = []
        operation_identifiers: set[str] = set()
        for method, _ in methods.values():
            metadata = getattr(method, "__stateforge_operation__", None)
            if not isinstance(metadata, _Operation):
                continue
            path = f"operations[{len(operations)}].requires"
            requirements = metadata.requires
            if (
                not isinstance(requirements, tuple)
                or len(requirements)
                > capability_contract.MAX_REQUIREMENT_FINDINGS_PER_OPERATION
            ):
                raise ManifestError(f"{path}: must be a bounded tuple")
            for identifier in requirements:
                validate_structure(identifier, "dottedIdentifier", path)
            if len(set(requirements)) != len(requirements):
                raise ManifestError(f"{path}: duplicate requirement reference")
            missing = tuple(
                identifier
                for identifier in requirements
                if identifier not in identifiers
            )
            if missing:
                raise ManifestError(f"{path}: unknown requirement reference")
            if metadata.identifier in operation_identifiers:
                raise ManifestError(
                    "operations: duplicate operation identifier"
                )
            operation_identifiers.add(metadata.identifier)
            operations.append((metadata.identifier, requirements))

        return cls(tuple(declarations), tuple(operations))

    @property
    def manifest_requirements(self) -> tuple[RuntimeRequirement, ...]:
        """Return static metadata for P1 manifest publication."""
        return tuple(
            declaration.manifest_requirement()
            for declaration in self.declarations
        )

    def bind(self, provider: object) -> BoundRequirementRegistry:
        """Bind validated method names to one Provider instance."""
        checks: dict[str, _BoundCheck] = {}
        for declaration in self.declarations:
            method = getattr(provider, declaration.method_name)
            if not callable(method):
                raise ManifestError(
                    "requirement_checks: declared method is unavailable"
                )
            checks[declaration.identifier] = method
        return BoundRequirementRegistry(
            declarations={item.identifier: item for item in self.declarations},
            checks=checks,
            operation_requirements=dict(self.operation_requirements),
        )


@dataclass(frozen=True, slots=True)
class BoundRequirementRegistry:
    """Resolve checks and associations for one running Provider instance."""

    declarations: dict[str, RequirementDeclaration]
    checks: dict[str, _BoundCheck]
    operation_requirements: dict[str, tuple[str, ...]]
