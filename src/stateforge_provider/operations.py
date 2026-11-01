"""Expose typed author-facing operation execution context."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
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

_ProgressReporter: TypeAlias = Callable[[str, float | None], Awaitable[None]]
_MAX_PERCENTAGE = 100.0


class ProgressPercentageMode(Enum):
    """Control whether an operation reports determinate progress."""

    OPTIONAL = "optional"
    REQUIRED = "required"
    FORBIDDEN = "forbidden"


@dataclass(frozen=True, slots=True)
class OperationProgressPolicy:
    """Apply optional author-selected progress consistency checks.

    Omitting ``progress=`` from :func:`stateforge_provider.operation` keeps
    the protocol's flexible behavior. A policy can make percentages
    determinate, monotonic, or required to finish at 100 before success.
    """

    percentage_mode: ProgressPercentageMode = ProgressPercentageMode.OPTIONAL
    monotonic: bool = False
    require_zero_start: bool = False
    require_100_on_success: bool = False
    require_progress_on_success: bool = False
    require_message: bool = False

    def __post_init__(self) -> None:
        """Reject contradictory progress requirements."""
        if not isinstance(self.percentage_mode, ProgressPercentageMode):
            raise TypeError("percentage_mode must be ProgressPercentageMode")
        for name in (
            "monotonic",
            "require_zero_start",
            "require_100_on_success",
            "require_progress_on_success",
            "require_message",
        ):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")
        if self.percentage_mode is ProgressPercentageMode.FORBIDDEN and (
            self.monotonic
            or self.require_zero_start
            or self.require_100_on_success
        ):
            raise ValueError(
                "percentage checks cannot be used when percentages are "
                "forbidden"
            )

    @classmethod
    def determinate(cls) -> OperationProgressPolicy:
        """Require monotonic percentages ending at 100 on success."""
        return cls(
            percentage_mode=ProgressPercentageMode.REQUIRED,
            monotonic=True,
            require_100_on_success=True,
        )

    @classmethod
    def indeterminate(cls) -> OperationProgressPolicy:
        """Require message-only progress without percentages."""
        return cls(
            percentage_mode=ProgressPercentageMode.FORBIDDEN,
            require_message=True,
        )


class OperationProgressError(ValueError):
    """Report a rejected author progress update."""


class OperationSideEffects(Enum):
    """Describe residual effects after an operation stops."""

    NONE = "none"
    PRESENT = "present"
    UNKNOWN = "unknown"


class OperationCleanup(Enum):
    """Describe cleanup completed before a terminal outcome."""

    NOT_REQUIRED = "not_required"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class OperationEffects:
    """Describe side effects and cleanup without implying rollback."""

    side_effects: OperationSideEffects
    cleanup: OperationCleanup
    explanation: str

    def __post_init__(self) -> None:
        """Reject malformed author-facing effects."""
        if not isinstance(self.side_effects, OperationSideEffects):
            raise TypeError("side_effects must be OperationSideEffects")
        if not isinstance(self.cleanup, OperationCleanup):
            raise TypeError("cleanup must be OperationCleanup")
        if not isinstance(self.explanation, str) or not self.explanation:
            raise ValueError("explanation must be a non-empty string")


@dataclass(frozen=True, slots=True)
class OperationFailedError(Exception):
    """End an operation with a stable sanitized business failure."""

    code: str
    explanation: str
    effects: OperationEffects


@dataclass(frozen=True, slots=True)
class OperationCancelledError(Exception):
    """Confirm that cooperatively cancelled execution has stopped."""

    effects: OperationEffects


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
    _reporter: _ProgressReporter
    _cancellation: asyncio.Event

    @property
    def cancellation_requested(self) -> bool:
        """Return whether cooperative cancellation has been requested."""
        return self._cancellation.is_set()

    async def wait_for_cancellation(self) -> None:
        """Wait until cooperative cancellation is requested."""
        await self._cancellation.wait()

    async def report_progress(
        self,
        message: str = "",
        *,
        percentage: float | None = None,
    ) -> None:
        """Commit one sanitized current-progress update.

        Raises:
            OperationProgressError: The update violates the operation's
                protocol bounds or optional author-selected progress policy.
        """
        if not isinstance(message, str):
            raise OperationProgressError("progress message must be a string")
        normalized_percentage: float | None = None
        if percentage is not None:
            if (
                isinstance(percentage, bool)
                or not isinstance(percentage, (int, float))
                or not math.isfinite(percentage)
                or not 0 <= percentage <= _MAX_PERCENTAGE
            ):
                raise OperationProgressError(
                    "progress percentage must be finite and between 0 and 100"
                )
            normalized_percentage = float(percentage)
        if not message and normalized_percentage is None:
            raise OperationProgressError(
                "progress requires a message or percentage"
            )
        await self._reporter(message, normalized_percentage)

    @classmethod
    def _create(
        cls,
        operation_id: UUID,
        execution_deadline: datetime,
        execution_context: dict[str, JsonValue],
        reporter: _ProgressReporter,
        cancellation: asyncio.Event,
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
            reporter,
            cancellation,
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


__all__ = [
    "FrozenJsonValue",
    "OperationCancelledError",
    "OperationCleanup",
    "OperationContext",
    "OperationEffects",
    "OperationFailedError",
    "OperationProgressError",
    "OperationProgressPolicy",
    "OperationSideEffects",
    "ProgressPercentageMode",
]
