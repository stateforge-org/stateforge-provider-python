"""Own bounded trigger sources, publications, retries, and receipts."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from jsonschema import Draft202012Validator
from stateforge_protocol.sfp.trigger_publication.v1 import (
    trigger_publication_pb2,
)
from stateforge_protocol.sfp.trigger_publication.v1.validation import (
    validate_publication_acknowledgement,
    validate_trigger_publication,
)

from stateforge_provider._services.manifest.declaration import (
    ManifestDeclaration,
)
from stateforge_provider.declarations import ProviderModel, Trigger
from stateforge_provider.triggers import (
    TriggerPayloadError,
    TriggerPublicationDisposition,
    TriggerPublicationOutcome,
    TriggerPublicationReceipt,
    TriggerPublicationUnavailableError,
    TriggerQueueFullError,
    TriggerRejection,
    TriggerRejectionReason,
)

_LOGGER = logging.getLogger(__name__)
_wire = trigger_publication_pb2
_ACCEPTED_NEW = _wire.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW
_ACCEPTED_DUPLICATE = (
    _wire.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_DUPLICATE
)
_REASON_INVALID = (
    trigger_publication_pb2.TRIGGER_REJECTION_REASON_INVALID_PUBLICATION
)
_REASON_NOT_DECLARED = (
    trigger_publication_pb2.TRIGGER_REJECTION_REASON_TRIGGER_NOT_DECLARED
)
_REASON_SCHEMA = (
    trigger_publication_pb2.TRIGGER_REJECTION_REASON_PAYLOAD_SCHEMA_VIOLATION
)
_REASON_CONFLICT = (
    trigger_publication_pb2.TRIGGER_REJECTION_REASON_IDEMPOTENCY_CONFLICT
)
_REASON_CAPACITY = (
    trigger_publication_pb2.TRIGGER_REJECTION_REASON_AGENT_CAPACITY_EXHAUSTED
)
_REASON_UNAVAILABLE = (
    _wire.TRIGGER_REJECTION_REASON_DELIVERY_RESPONSIBILITY_UNAVAILABLE
)


class DuplicateTriggerStreamError(RuntimeError):
    """Reject a second active stream for the same negotiated session."""


class TriggerAcknowledgementError(RuntimeError):
    """Reject an acknowledgement outside its current stream window."""


class TriggerStreamClosedError(RuntimeError):
    """Stop delivery after a stream lease or runtime closes."""


@dataclass(slots=True)
class _Publication:
    """Retain one immutable publication through every delivery attempt."""

    message: trigger_publication_pb2.TriggerPublication
    completion: asyncio.Future[TriggerPublicationOutcome] | None
    lease_id: UUID | None = None
    attempts: int = 0
    retry_at: float = 0.0


@dataclass(slots=True)
class TriggerStreamLease:
    """Own one stream's exact flow-control and acknowledgement window."""

    identifier: UUID
    session_id: str
    maximum_in_flight: int
    outstanding: set[str] = field(default_factory=set)
    closed: bool = False


class TriggerPublicationRuntime:
    """Bridge author events to the canonical P3 delivery state machine."""

    def __init__(
        self,
        declaration: ManifestDeclaration,
        *,
        queue_capacity: int,
        maximum_in_flight: int,
        retry_base_seconds: float,
        retry_max_seconds: float,
    ) -> None:
        self._declarations = {
            item.identifier: item for item in declaration.trigger_declarations
        }
        self._schemas = {
            identifier: Draft202012Validator(schema)
            for identifier, schema in declaration.trigger_schemas.items()
        }
        self._source_methods = declaration.trigger_source_methods
        self._queue_capacity = queue_capacity
        self._maximum_in_flight = maximum_in_flight
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds
        self._condition = asyncio.Condition()
        self._publications: dict[str, _Publication] = {}
        self._streams: dict[str, TriggerStreamLease] = {}
        self._source_tasks: set[asyncio.Task[None]] = set()
        self._stopping = False

    @property
    def maximum_in_flight(self) -> int:
        """Return the Provider's local P3 receive-window ceiling."""
        return self._maximum_in_flight

    async def publish(
        self,
        trigger: Trigger | str,
        payload: ProviderModel,
        *,
        observed_at: datetime | None = None,
    ) -> TriggerPublicationReceipt:
        """Validate and queue one callback-driven publication."""
        completion: asyncio.Future[TriggerPublicationOutcome] = (
            asyncio.get_running_loop().create_future()
        )
        # Retrieving the exception prevents an abandoned receipt from producing
        # an event-loop warning while preserving normal await semantics.
        completion.add_done_callback(_consume_future_exception)
        publication = self._publication(trigger, payload, observed_at)
        await self._enqueue(publication, completion, wait_for_capacity=False)
        return TriggerPublicationReceipt(
            UUID(publication.publication_id),
            completion,
        )

    async def start_sources(self, provider: object) -> None:
        """Start every decorated async-generator source after publication."""
        if self._stopping:
            raise TriggerPublicationUnavailableError(
                "Trigger publication runtime is stopping"
            )
        for identifier, method_name in self._source_methods:
            task = asyncio.create_task(
                self._run_source(provider, identifier, method_name),
                name=f"stateforge-trigger:{identifier}",
            )
            self._source_tasks.add(task)
            task.add_done_callback(self._source_tasks.discard)

    async def stop_sources(self) -> None:
        """Cancel and join every runtime-owned author source task."""
        tasks = tuple(self._source_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._source_tasks.clear()

    async def close(self) -> None:
        """Stop admission, wake streams, and fail unresolved receipts."""
        async with self._condition:
            if self._stopping:
                return
            self._stopping = True
            error = TriggerPublicationUnavailableError(
                "Provider stopped before publication acknowledgement"
            )
            for publication in self._publications.values():
                completion = publication.completion
                if completion is not None and not completion.done():
                    completion.set_exception(error)
            for stream in self._streams.values():
                stream.closed = True
            self._streams.clear()
            self._condition.notify_all()

    async def open_stream(
        self,
        session_id: str,
        requested_maximum: int,
    ) -> TriggerStreamLease:
        """Acquire one current-session delivery and acknowledgement window."""
        async with self._condition:
            if self._stopping:
                raise TriggerPublicationUnavailableError(
                    "Trigger publication runtime is stopping"
                )
            if session_id in self._streams:
                raise DuplicateTriggerStreamError
            lease = TriggerStreamLease(
                uuid4(),
                session_id,
                min(requested_maximum, self._maximum_in_flight),
            )
            self._streams[session_id] = lease
            return lease

    async def close_stream(self, lease: TriggerStreamLease) -> None:
        """Release one stream and make its unacknowledged events replayable."""
        loop = asyncio.get_running_loop()
        async with self._condition:
            if lease.closed:
                return
            lease.closed = True
            if self._streams.get(lease.session_id) is lease:
                self._streams.pop(lease.session_id, None)
            for publication_id in tuple(lease.outstanding):
                publication = self._publications.get(publication_id)
                if (
                    publication is not None
                    and publication.lease_id == lease.identifier
                ):
                    publication.lease_id = None
                    publication.retry_at = max(
                        publication.retry_at,
                        loop.time()
                        + self._exponential_retry_delay(publication),
                    )
            lease.outstanding.clear()
            self._condition.notify_all()

    async def next_publication(
        self,
        lease: TriggerStreamLease,
    ) -> trigger_publication_pb2.TriggerPublication:
        """Wait for and reserve the next retry-eligible publication."""
        loop = asyncio.get_running_loop()
        async with self._condition:
            while True:
                if self._stopping or lease.closed:
                    raise TriggerStreamClosedError
                now = loop.time()
                if len(lease.outstanding) < lease.maximum_in_flight:
                    for (
                        publication_id,
                        publication,
                    ) in self._publications.items():
                        if publication.lease_id is not None:
                            continue
                        if publication.retry_at > now:
                            continue
                        publication.lease_id = lease.identifier
                        publication.attempts += 1
                        lease.outstanding.add(publication_id)
                        return type(publication.message).FromString(
                            publication.message.SerializeToString()
                        )
                delay = min(
                    (
                        publication.retry_at - now
                        for publication in self._publications.values()
                        if publication.lease_id is None
                        and publication.retry_at > now
                    ),
                    default=None,
                )
                if delay is None:
                    await self._condition.wait()
                else:
                    try:
                        async with asyncio.timeout(delay):
                            await self._condition.wait()
                    except TimeoutError:
                        pass

    async def acknowledge(
        self,
        lease: TriggerStreamLease,
        acknowledgement: trigger_publication_pb2.TriggerAcknowledgement,
    ) -> None:
        """Apply one Agent decision without changing event content."""
        async with self._condition:
            publication_id = acknowledgement.publication_id
            publication = self._publications.get(publication_id)
            if (
                lease.closed
                or publication is None
                or publication_id not in lease.outstanding
                or publication.lease_id != lease.identifier
            ):
                raise TriggerAcknowledgementError
            validate_publication_acknowledgement(
                publication.message,
                acknowledgement,
            )
            lease.outstanding.remove(publication_id)
            disposition = acknowledgement.disposition
            if disposition in (_ACCEPTED_NEW, _ACCEPTED_DUPLICATE):
                self._publications.pop(publication_id)
                outcome = TriggerPublicationOutcome(
                    UUID(publication_id),
                    (
                        TriggerPublicationDisposition.ACCEPTED_NEW
                        if disposition == _ACCEPTED_NEW
                        else TriggerPublicationDisposition.ACCEPTED_DUPLICATE
                    ),
                )
                _complete(publication, outcome)
            elif acknowledgement.rejection.retryable:
                publication.lease_id = None
                publication.retry_at = (
                    asyncio.get_running_loop().time()
                    + self._retry_delay(publication, acknowledgement)
                )
            else:
                self._publications.pop(publication_id)
                rejection = _rejection(acknowledgement.rejection)
                _complete(
                    publication,
                    TriggerPublicationOutcome(
                        UUID(publication_id),
                        TriggerPublicationDisposition.REJECTED,
                        rejection,
                    ),
                )
                if publication.completion is None:
                    _LOGGER.warning(
                        "Decorated trigger publication was rejected",
                        extra={
                            "publication_id": publication_id,
                            "trigger_identifier": (
                                publication.message.trigger_identifier
                            ),
                            "reason": rejection.reason.value,
                        },
                    )
            self._condition.notify_all()

    def _publication(
        self,
        trigger: Trigger | str,
        payload: ProviderModel,
        observed_at: datetime | None,
    ) -> trigger_publication_pb2.TriggerPublication:
        """Build one schema-valid immutable wire publication."""
        identifier = (
            trigger.identifier if isinstance(trigger, Trigger) else trigger
        )
        declaration = self._declarations.get(identifier)
        if declaration is None:
            raise TriggerPayloadError(
                "Trigger is not declared by this Provider"
            )
        if isinstance(trigger, Trigger) and trigger != declaration:
            raise TriggerPayloadError(
                "Trigger declaration does not match the accepted manifest"
            )
        if not isinstance(payload, declaration.payload):
            raise TriggerPayloadError(
                "Trigger payload does not match its declared model"
            )
        projected = payload.model_dump(mode="json")
        if not isinstance(projected, dict):
            raise TriggerPayloadError(
                "Trigger payload must serialize as an object"
            )
        if not self._schemas[identifier].is_valid(projected):
            raise TriggerPayloadError(
                "Trigger payload does not satisfy its declared schema"
            )
        observed = observed_at or datetime.now(UTC)
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise TriggerPayloadError("observed_at must be timezone-aware")
        timestamp = Timestamp()
        timestamp.FromDatetime(observed)
        publication = trigger_publication_pb2.TriggerPublication(
            publication_id=str(uuid4()),
            trigger_identifier=identifier,
            observed_at=timestamp,
            payload=ParseDict(projected, Struct()),
        )
        try:
            validate_trigger_publication(publication)
        except ValueError:
            raise TriggerPayloadError(
                "Trigger payload exceeds the P3 contract limits"
            ) from None
        return publication

    async def _enqueue(
        self,
        publication: trigger_publication_pb2.TriggerPublication,
        completion: asyncio.Future[TriggerPublicationOutcome] | None,
        *,
        wait_for_capacity: bool,
    ) -> None:
        """Admit one event without ever dropping an older queued event."""
        async with self._condition:
            while len(self._publications) >= self._queue_capacity:
                if self._stopping:
                    raise TriggerPublicationUnavailableError(
                        "Trigger publication runtime is stopping"
                    )
                if not wait_for_capacity:
                    raise TriggerQueueFullError(
                        "Trigger publication queue capacity is exhausted"
                    )
                await self._condition.wait()
            if self._stopping:
                raise TriggerPublicationUnavailableError(
                    "Trigger publication runtime is stopping"
                )
            self._publications[publication.publication_id] = _Publication(
                publication,
                completion,
            )
            self._condition.notify_all()

    async def _run_source(
        self,
        provider: object,
        identifier: str,
        method_name: str,
    ) -> None:
        """Translate one decorated async generator into queued events."""
        try:
            source = getattr(provider, method_name)()
            if not isinstance(source, AsyncIterator):
                raise TypeError("trigger source did not return AsyncIterator")
            async for payload in source:
                publication = self._publication(identifier, payload, None)
                await self._enqueue(
                    publication,
                    None,
                    wait_for_capacity=True,
                )
        except asyncio.CancelledError:
            raise
        except TriggerPublicationUnavailableError:
            return
        except Exception:
            _LOGGER.error(
                "Provider trigger source stopped after an author failure",
                extra={"trigger_identifier": identifier},
            )

    def _retry_delay(
        self,
        publication: _Publication,
        acknowledgement: trigger_publication_pb2.TriggerAcknowledgement,
    ) -> float:
        """Select bounded Agent guidance or Provider exponential backoff."""
        if acknowledgement.rejection.HasField("retry_after"):
            return float(
                min(
                    acknowledgement.rejection.retry_after.ToTimedelta().total_seconds(),
                    self._retry_max_seconds,
                )
            )
        return self._exponential_retry_delay(publication)

    def _exponential_retry_delay(self, publication: _Publication) -> float:
        """Bound retry timing for rejections and transient stream loss."""
        exponent = min(publication.attempts - 1, 30)
        return float(
            min(
                self._retry_base_seconds * (2**exponent),
                self._retry_max_seconds,
            )
        )


def _complete(
    publication: _Publication,
    outcome: TriggerPublicationOutcome,
) -> None:
    """Resolve a callback receipt when the author requested one."""
    completion = publication.completion
    if completion is not None and not completion.done():
        completion.set_result(outcome)


def _consume_future_exception(
    future: asyncio.Future[TriggerPublicationOutcome],
) -> None:
    """Mark an abandoned receipt's exception as retrieved."""
    if not future.cancelled():
        future.exception()


def _rejection(
    rejection: trigger_publication_pb2.TriggerRejection,
) -> TriggerRejection:
    """Translate canonical wire details into protobuf-free public values."""
    reasons = {
        _REASON_INVALID: TriggerRejectionReason.INVALID_PUBLICATION,
        _REASON_NOT_DECLARED: TriggerRejectionReason.TRIGGER_NOT_DECLARED,
        _REASON_SCHEMA: TriggerRejectionReason.PAYLOAD_SCHEMA_VIOLATION,
        _REASON_CONFLICT: TriggerRejectionReason.IDEMPOTENCY_CONFLICT,
        _REASON_CAPACITY: TriggerRejectionReason.AGENT_CAPACITY_EXHAUSTED,
        _REASON_UNAVAILABLE: (
            TriggerRejectionReason.DELIVERY_RESPONSIBILITY_UNAVAILABLE
        ),
    }
    return TriggerRejection(
        reasons[rejection.reason],
        rejection.retryable,
        (
            rejection.retry_after.ToTimedelta()
            if rejection.HasField("retry_after")
            else None
        ),
        rejection.explanation,
    )
