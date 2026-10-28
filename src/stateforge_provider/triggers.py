"""Author-facing trigger publication declarations and outcomes."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Any, TypeVar
from uuid import UUID


class TriggerPublicationError(RuntimeError):
    """Report a local trigger publication failure without exposing payloads."""


class TriggerPublicationUnavailableError(TriggerPublicationError):
    """Report that the Provider trigger runtime is not accepting events."""


class TriggerQueueFullError(TriggerPublicationError):
    """Report that the bounded publication queue has no free capacity."""


class TriggerPayloadError(TriggerPublicationError, ValueError):
    """Report that a payload does not satisfy its declared trigger schema."""


class TriggerPublicationDisposition(StrEnum):
    """Describe the Agent's terminal disposition for one publication."""

    ACCEPTED_NEW = "accepted_new"
    ACCEPTED_DUPLICATE = "accepted_duplicate"
    REJECTED = "rejected"


class TriggerRejectionReason(StrEnum):
    """Expose the stable P3 publication-rejection vocabulary."""

    INVALID_PUBLICATION = "invalid_publication"
    TRIGGER_NOT_DECLARED = "trigger_not_declared"
    PAYLOAD_SCHEMA_VIOLATION = "payload_schema_violation"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    AGENT_CAPACITY_EXHAUSTED = "agent_capacity_exhausted"
    DELIVERY_RESPONSIBILITY_UNAVAILABLE = "delivery_responsibility_unavailable"


@dataclass(frozen=True, slots=True)
class TriggerRejection:
    """Describe a sanitized non-retryable Agent rejection."""

    reason: TriggerRejectionReason
    retryable: bool
    retry_after: timedelta | None = None
    explanation: str = ""


@dataclass(frozen=True, slots=True)
class TriggerPublicationOutcome:
    """Expose the terminal acknowledgement for one logical event."""

    publication_id: UUID
    disposition: TriggerPublicationDisposition
    rejection: TriggerRejection | None = None


@dataclass(frozen=True, slots=True)
class TriggerPublicationReceipt:
    """Track a locally queued publication without exposing wire details."""

    publication_id: UUID
    _completion: asyncio.Future[TriggerPublicationOutcome] = field(
        repr=False,
        compare=False,
    )

    async def outcome(self) -> TriggerPublicationOutcome:
        """Wait for the Agent's terminal acknowledgement disposition."""
        return await asyncio.shield(self._completion)


@dataclass(frozen=True, slots=True)
class _TriggerSource:
    """Retain one decorated source's stable trigger identifier."""

    identifier: str


_Handler = TypeVar("_Handler", bound=Callable[..., Any])


def trigger(identifier: str) -> Callable[[_Handler], _Handler]:
    """Declare an async-generator method as a continuous trigger source.

    The method must accept only ``self`` and return
    ``AsyncIterator[ProviderModelSubclass]``. Each yielded model becomes one
    immutable publication. The runtime derives the manifest declaration from
    the return annotation and applies bounded backpressure when disconnected.
    """

    def decorate(handler: _Handler) -> _Handler:
        if hasattr(handler, "__stateforge_trigger_source__"):
            raise ValueError("A trigger source cannot be declared twice")
        setattr(  # noqa: B010
            handler,
            "__stateforge_trigger_source__",
            _TriggerSource(identifier),
        )
        return handler

    return decorate


__all__ = [
    "TriggerPayloadError",
    "TriggerPublicationDisposition",
    "TriggerPublicationError",
    "TriggerPublicationOutcome",
    "TriggerPublicationReceipt",
    "TriggerPublicationUnavailableError",
    "TriggerQueueFullError",
    "TriggerRejection",
    "TriggerRejectionReason",
    "trigger",
]
