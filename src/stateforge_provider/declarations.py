"""Declare Provider capabilities using typed Python metadata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict


class ProviderModel(BaseModel):
    """Describe an object input, result, configuration, or trigger payload.

    Uses Pydantic's typed fields and JSON Schema generation. Unknown fields
    are rejected by default. Declare secrets with ``SecretStr`` or a field
    marked ``writeOnly``; never supply secret defaults or examples.
    """

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True, slots=True, order=True)
class Platform:
    """Declare one supported operating-system/architecture pair."""

    operating_system: str
    architecture: str


@dataclass(frozen=True, slots=True)
class RuntimeRequirement:
    """Describe a prerequisite without probing or executing it.

    An empty version constraint declares no restriction. Nonempty syntax
    belongs to the dotted requirement identifier, not to this runtime.
    """

    identifier: str
    description: str
    version_constraint: str = ""


@dataclass(frozen=True, slots=True)
class Trigger:
    """Declare a versioned trigger and its typed payload."""

    identifier: str
    payload: type[ProviderModel]


@dataclass(frozen=True, slots=True)
class _Operation:
    identifier: str
    implements: tuple[str, ...]
    requires: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _RequirementCheck:
    identifier: str
    description: str
    version_constraint: str


_Handler = TypeVar("_Handler", bound=Callable[..., Any])


def _mro_namespace(owner: type) -> dict[str, Any]:
    """Collect the class namespace used where a method was declared."""
    namespace: dict[str, Any] = {}
    for base in reversed(owner.__mro__):
        namespace.update(vars(base))
    return namespace


def operation(
    identifier: str,
    *,
    implements: tuple[str, ...] = (),
    requires: tuple[str, ...] = (),
) -> Callable[[_Handler], _Handler]:
    """Declare an async method's versioned input/result contract.

    Annotate ``request`` and the return value with ProviderModel subclasses.
    This milestone discovers metadata only; it does not dispatch the method.
    ``implements`` contains versioned semantic/compliance profile claims. Each
    claim says the operation conforms to that profile's required schemas and
    behavior. Claims are not permissions or Control Plane contract identifiers
    and are never inferred from a method or model name.
    ``requires`` contains stable IDs declared by :func:`requirement_check`.
    The runtime evaluates each distinct check at most once per assessment.
    Inherited methods follow Python's MRO; overriding requires redeclaration.
    """

    def decorate(handler: _Handler) -> _Handler:
        if hasattr(handler, "__stateforge_operation__"):
            raise ValueError("An operation method cannot be declared twice")
        # Attach metadata while retaining the original callable's static type.
        setattr(  # noqa: B010
            handler,
            "__stateforge_operation__",
            _Operation(identifier, implements, requires),
        )
        return handler

    return decorate


def requirement_check(
    identifier: str,
    description: str,
    version_constraint: str = "",
) -> Callable[[_Handler], _Handler]:
    """Declare an asynchronous, read-only runtime prerequisite check.

    Decorate a Provider instance method with a ``(self)`` signature returning
    :class:`~stateforge_provider.RequirementCheckResult`. The runtime publishes
    the static description in the manifest and privately adapts results to
    Capability Assessment findings.
    """

    def decorate(handler: _Handler) -> _Handler:
        if hasattr(handler, "__stateforge_requirement_check__"):
            raise ValueError("A requirement check cannot be declared twice")
        setattr(  # noqa: B010
            handler,
            "__stateforge_requirement_check__",
            _RequirementCheck(identifier, description, version_constraint),
        )
        return handler

    return decorate
