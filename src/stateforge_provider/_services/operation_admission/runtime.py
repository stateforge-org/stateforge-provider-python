"""Own atomic in-memory Operation Admission records and dispatch tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto

from google.protobuf.timestamp_pb2 import Timestamp
from stateforge_protocol.sfp.operation_admission.v1 import (
    operation_admission_pb2,
)

_LOGGER = logging.getLogger(__name__)
_Dispatch = Callable[[], Awaitable[None]]


class AdmissionRegistryFailure(Enum):
    """Classify an exact atomic-registry rejection."""

    CONFLICT = auto()
    EXPIRED = auto()
    UNAVAILABLE = auto()
    CAPACITY = auto()
    STOPPING = auto()


@dataclass(frozen=True, slots=True)
class AdmissionRegistryError(Exception):
    """Report a registry decision without carrying business payloads."""

    failure: AdmissionRegistryFailure


@dataclass(frozen=True, slots=True)
class AdmissionDecision:
    """Return one immutable record and whether this call inserted it."""

    record: operation_admission_pb2.OperationAdmissionRecord
    accepted_new: bool


@dataclass(slots=True)
class _Entry:
    """Retain one immutable record until its advertised expiry."""

    fingerprint: str
    record: operation_admission_pb2.OperationAdmissionRecord
    expires_at: datetime


class OperationAdmissionRuntime:
    """Converge concurrent retries before invoking Provider author code.

    Every mutation is synchronous and runs on the Provider event loop. No
    await occurs between the final lookup, record insertion, and dispatch-task
    creation.
    """

    def __init__(
        self,
        *,
        maximum_records: int,
        maximum_dispatches: int,
        record_retention_seconds: float,
        tombstone_retention_seconds: float,
    ) -> None:
        self._maximum_records = maximum_records
        self._maximum_dispatches = maximum_dispatches
        self._record_retention = timedelta(seconds=record_retention_seconds)
        self._tombstone_retention = timedelta(
            seconds=tombstone_retention_seconds
        )
        self._records: dict[str, _Entry] = {}
        self._tombstones: dict[str, datetime] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    def lookup(
        self,
        operation_id: str,
        fingerprint: str,
    ) -> AdmissionDecision | None:
        """Resolve retained state before new-admission preconditions."""
        now = datetime.now(UTC)
        self._prune(now)
        entry = self._records.get(operation_id)
        if entry is not None:
            if entry.fingerprint != fingerprint:
                raise AdmissionRegistryError(AdmissionRegistryFailure.CONFLICT)
            return AdmissionDecision(_copy_record(entry.record), False)
        if operation_id in self._tombstones:
            raise AdmissionRegistryError(AdmissionRegistryFailure.EXPIRED)
        return None

    def admit(
        self,
        *,
        operation_id: str,
        fingerprint: str,
        endpoint_generation: int,
        dispatch: _Dispatch,
    ) -> AdmissionDecision:
        """Atomically insert a record and schedule exactly one dispatch."""
        existing = self.lookup(operation_id, fingerprint)
        if existing is not None:
            return existing
        if self._closed:
            raise AdmissionRegistryError(AdmissionRegistryFailure.STOPPING)
        if (
            len(self._records) >= self._maximum_records
            or len(self._tasks) >= self._maximum_dispatches
        ):
            raise AdmissionRegistryError(AdmissionRegistryFailure.CAPACITY)

        admitted_at = datetime.now(UTC)
        expires_at = admitted_at + self._record_retention
        record = operation_admission_pb2.OperationAdmissionRecord(
            operation_id=operation_id,
            request_fingerprint=fingerprint,
            admitted_at=_timestamp(admitted_at),
            record_expires_at=_timestamp(expires_at),
            admitted_endpoint_generation=endpoint_generation,
        )
        self._records[operation_id] = _Entry(
            fingerprint=fingerprint,
            record=_copy_record(record),
            expires_at=expires_at,
        )
        task = asyncio.create_task(
            self._run_dispatch(operation_id, dispatch),
            name=f"stateforge-operation-{operation_id}",
        )
        self._tasks[operation_id] = task

        def task_done(completed: asyncio.Task[None]) -> None:
            self._task_done(operation_id, completed)

        task.add_done_callback(task_done)
        return AdmissionDecision(record, True)

    def begin_shutdown(self) -> None:
        """Reject new admissions while allowing retained resolution."""
        self._closed = True

    async def close(self) -> None:
        """Stop admission and cancel every active author dispatch."""
        self.begin_shutdown()
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_dispatch(
        self,
        operation_id: str,
        dispatch: _Dispatch,
    ) -> None:
        """Run author behavior without changing immutable admission state."""
        try:
            await dispatch()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.error(
                "Provider operation dispatch failed",
                extra={"operation_id": operation_id},
            )

    def _task_done(
        self,
        operation_id: str,
        task: asyncio.Task[None],
    ) -> None:
        """Release dispatch capacity without consuming task exceptions."""
        if self._tasks.get(operation_id) is task:
            del self._tasks[operation_id]

    def _prune(self, now: datetime) -> None:
        """Replace expired records with bounded expiry evidence."""
        expired = tuple(
            identifier
            for identifier, entry in self._records.items()
            if entry.expires_at <= now
        )
        for identifier in expired:
            del self._records[identifier]
            self._tombstones[identifier] = now + self._tombstone_retention
        for identifier, expires_at in tuple(self._tombstones.items()):
            if expires_at <= now:
                del self._tombstones[identifier]


def _timestamp(value: datetime) -> Timestamp:
    """Create an independent protobuf timestamp."""
    timestamp = Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _copy_record(
    record: operation_admission_pb2.OperationAdmissionRecord,
) -> operation_admission_pb2.OperationAdmissionRecord:
    """Return a message callers cannot use to mutate retained state."""
    return operation_admission_pb2.OperationAdmissionRecord.FromString(
        record.SerializeToString()
    )
