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


_Handler = TypeVar("_Handler", bound=Callable[..., Any])


def operation(
    identifier: str, *, implements: tuple[str, ...] = ()
) -> Callable[[_Handler], _Handler]:
    """Declare an async method's versioned input/result contract.

    Annotate ``request`` and the return value with ProviderModel subclasses.
    This milestone discovers metadata only; it does not dispatch the method.
    Roles are explicit claims, never inferred from a method or model name.
    Inherited methods follow Python's MRO; overriding requires redeclaration.
    """

    def decorate(handler: _Handler) -> _Handler:
        if hasattr(handler, "__stateforge_operation__"):
            raise ValueError("An operation method cannot be declared twice")
        # Attach metadata while retaining the original callable's static type.
        setattr(  # noqa: B010
            handler,
            "__stateforge_operation__",
            _Operation(identifier, implements),
        )
        return handler

    return decorate
