"""Own atomic admitted-operation records and their lifecycle state."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum, auto

from google.protobuf.timestamp_pb2 import Timestamp
from jsonschema import Draft202012Validator
from pydantic import JsonValue
from stateforge_protocol.sfp.operation_admission.v1 import (
    operation_admission_pb2,
)
from stateforge_protocol.sfp.operation_lifecycle.v1 import (
    contract as lifecycle_contract,
)

from stateforge_provider._services.operation_lifecycle.runtime import (
    OperationLifecycleRecord,
)
from stateforge_provider.declarations import ProviderModel
from stateforge_provider.operations import (
    OperationContext,
    OperationProgressPolicy,
)

_LOGGER = logging.getLogger(__name__)
_Dispatch = Callable[[OperationContext], Awaitable[ProviderModel]]


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
    """Retain admission and lifecycle evidence under one identity."""

    fingerprint: str
    record: operation_admission_pb2.OperationAdmissionRecord
    expires_at: datetime
    lifecycle: OperationLifecycleRecord


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
        maximum_observers_per_operation: int = (
            lifecycle_contract.MAX_OBSERVERS_PER_OPERATION
        ),
    ) -> None:
        self._maximum_records = maximum_records
        self._maximum_dispatches = maximum_dispatches
        self._maximum_observers_per_operation = maximum_observers_per_operation
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
        operation_identifier: str,
        manifest_revision: str,
        result_model: type[ProviderModel],
        result_validator: Draft202012Validator,
        cancellable: bool,
        progress_policy: OperationProgressPolicy | None,
        execution_deadline: datetime,
        execution_context: dict[str, JsonValue],
        dispatch: _Dispatch,
    ) -> AdmissionDecision:
        """Atomically insert a record and schedule exactly one dispatch."""
        existing = self.lookup(operation_id, fingerprint)
        if existing is not None:
            return existing
        if self._closed:
            raise AdmissionRegistryError(AdmissionRegistryFailure.STOPPING)
        retained_identities = len(self._records) + len(self._tombstones)
        if (
            retained_identities >= self._maximum_records
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
        lifecycle = OperationLifecycleRecord(
            admission_record=record,
            operation_identifier=operation_identifier,
            manifest_revision=manifest_revision,
            result_model=result_model,
            result_validator=result_validator,
            cancellable=cancellable,
            progress_policy=progress_policy,
            maximum_observers=self._maximum_observers_per_operation,
        )
        self._records[operation_id] = _Entry(
            fingerprint=fingerprint,
            record=_copy_record(record),
            expires_at=expires_at,
            lifecycle=lifecycle,
        )
        task = asyncio.create_task(
            lifecycle.execute(
                operation_id=operation_id,
                execution_deadline=execution_deadline,
                execution_context=execution_context,
                dispatch=dispatch,
            ),
            name=f"stateforge-operation-{operation_id}",
        )
        self._tasks[operation_id] = task

        def task_done(completed: asyncio.Task[None]) -> None:
            self._task_done(operation_id, completed)

        task.add_done_callback(task_done)
        return AdmissionDecision(record, True)

    def resolve_lifecycle(
        self,
        operation_id: str,
        fingerprint: str,
    ) -> OperationLifecycleRecord:
        """Resolve lifecycle state for one exact admitted invocation."""
        now = datetime.now(UTC)
        self._prune(now)
        entry = self._records.get(operation_id)
        if entry is None:
            failure = (
                AdmissionRegistryFailure.EXPIRED
                if operation_id in self._tombstones
                else AdmissionRegistryFailure.UNAVAILABLE
            )
            raise AdmissionRegistryError(failure)
        if entry.fingerprint != fingerprint:
            raise AdmissionRegistryError(AdmissionRegistryFailure.CONFLICT)
        return entry.lifecycle

    def begin_shutdown(self) -> None:
        """Reject new admissions while allowing retained resolution."""
        self._closed = True

    async def close(self) -> None:
        """Stop admission and cancel every active author dispatch."""
        self.begin_shutdown()
        tasks = tuple(self._tasks.values())
        for entry in self._records.values():
            entry.lifecycle.detach_all()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _task_done(
        self,
        operation_id: str,
        task: asyncio.Task[None],
    ) -> None:
        """Release capacity and consume unexpected internal exceptions."""
        if self._tasks.get(operation_id) is task:
            del self._tasks[operation_id]
        if task.cancelled():
            return
        if task.exception() is not None:
            _LOGGER.error(
                "Provider operation runtime task failed",
                extra={"operation_id": operation_id},
            )

    def _prune(self, now: datetime) -> None:
        """Replace expired records with bounded expiry evidence."""
        expired = tuple(
            identifier
            for identifier, entry in self._records.items()
            if entry.expires_at <= now and entry.lifecycle.terminal
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
