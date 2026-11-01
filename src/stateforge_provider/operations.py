"""Expose typed author-facing operation execution context."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import TypeAlias
from uuid import UUID

from pydantic import JsonValue

FrozenJsonValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | tuple["FrozenJsonValue", ...]
    | Mapping[str, "FrozenJsonValue"]
    | None
)


@dataclass(frozen=True, slots=True)
class OperationContext:
    """Describe one admitted operation without exposing SFP internals.

    Attributes:
        operation_id: Agent-assigned immutable operation identity.
        execution_deadline: Absolute deadline for the business attempt.
        execution_context: Read-only approved execution metadata.
    """

    operation_id: UUID
    execution_deadline: datetime
    execution_context: Mapping[str, FrozenJsonValue]

    @classmethod
    def _create(
        cls,
        operation_id: UUID,
        execution_deadline: datetime,
        execution_context: dict[str, JsonValue],
    ) -> OperationContext:
        """Create a context with recursively immutable JSON values."""
        frozen = {
            key: _freeze_json(value)
            for key, value in execution_context.items()
        }
        return cls(
            operation_id,
            execution_deadline,
            MappingProxyType(frozen),
        )


def _freeze_json(value: JsonValue) -> FrozenJsonValue:
    """Freeze nested JSON containers before exposing them to author code."""
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


__all__ = ["FrozenJsonValue", "OperationContext"]
