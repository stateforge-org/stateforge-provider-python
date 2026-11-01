"""Own one admitted operation's state, observers, and author execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeAlias
from uuid import UUID

from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from jsonschema import Draft202012Validator
from pydantic import JsonValue
from stateforge_protocol.sfp.operation_admission.v1 import (
    operation_admission_pb2,
)
from stateforge_protocol.sfp.operation_lifecycle.v1 import (
    operation_lifecycle_pb2,
    validation,
)

from stateforge_provider.declarations import ProviderModel
from stateforge_provider.operations import (
    OperationCancelledError,
    OperationCleanup,
    OperationContext,
    OperationEffects,
    OperationFailedError,
    OperationProgressError,
    OperationProgressPolicy,
    OperationSideEffects,
    ProgressPercentageMode,
)

_LOGGER = logging.getLogger(__name__)
_Dispatch: TypeAlias = Callable[[OperationContext], Awaitable[ProviderModel]]
_TERMINAL_STATES = frozenset(
    {
        operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED,
        operation_lifecycle_pb2.OPERATION_STATE_FAILED,
        operation_lifecycle_pb2.OPERATION_STATE_CANCELLED,
    }
)
_CANCELLATION_REQUESTED = (
    operation_lifecycle_pb2.OPERATION_STATE_CANCELLATION_REQUESTED
)
_COMPLETE_PERCENTAGE = 100.0


class LifecycleRecordError(RuntimeError):
    """Report a local operation-record decision."""


class LifecycleObserverCapacityError(LifecycleRecordError):
    """Reject an observer when the operation is at capacity."""


class LifecycleCursorAheadError(LifecycleRecordError):
    """Reject a cursor newer than retained operation state."""


@dataclass(eq=False, slots=True)
class LifecycleObserver:
    """Retain one bounded current-state notification slot."""

    changed: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False


class OperationLifecycleRecord:
    """Coordinate one admitted operation without retaining event history."""

    def __init__(
        self,
        *,
        admission_record: operation_admission_pb2.OperationAdmissionRecord,
        operation_identifier: str,
        manifest_revision: str,
        result_model: type[ProviderModel],
        result_validator: Draft202012Validator,
        cancellable: bool,
        progress_policy: OperationProgressPolicy | None,
        maximum_observers: int,
    ) -> None:
        snapshot = operation_lifecycle_pb2.OperationSnapshot(
            admission_record=admission_record,
            operation_identifier=operation_identifier,
            manifest_revision=manifest_revision,
            sequence=1,
            state=operation_lifecycle_pb2.OPERATION_STATE_ACCEPTED,
            updated_at=admission_record.admitted_at,
        )
        validation.validate_operation_snapshot(snapshot)
        self._snapshot = snapshot.SerializeToString()
        self._result_model = result_model
        self._result_validator = result_validator
        self._cancellable = cancellable
        self._progress_policy = progress_policy
        self._maximum_observers = maximum_observers
        self._cancellation = asyncio.Event()
        self._observers: set[LifecycleObserver] = set()
        self._last_percentage: float | None = None

    @property
    def terminal(self) -> bool:
        """Return whether one immutable terminal outcome is retained."""
        return self.snapshot().state in _TERMINAL_STATES

    def snapshot(self) -> operation_lifecycle_pb2.OperationSnapshot:
        """Return an independent copy of the complete current state."""
        return operation_lifecycle_pb2.OperationSnapshot.FromString(
            self._snapshot
        )

    def attach(
        self,
        after_sequence: int,
    ) -> tuple[LifecycleObserver, operation_lifecycle_pb2.OperationSnapshot]:
        """Atomically subscribe and capture current state."""
        current = self.snapshot()
        if after_sequence > current.sequence:
            raise LifecycleCursorAheadError
        if len(self._observers) >= self._maximum_observers:
            raise LifecycleObserverCapacityError
        observer = LifecycleObserver()
        self._observers.add(observer)
        return observer, current

    async def next_snapshot(
        self,
        observer: LifecycleObserver,
        after_sequence: int,
    ) -> operation_lifecycle_pb2.OperationSnapshot:
        """Wait for current state to advance beyond one delivered sequence."""
        while not observer.closed:
            current = self.snapshot()
            if current.sequence > after_sequence:
                return current
            observer.changed.clear()
            current = self.snapshot()
            if current.sequence > after_sequence:
                return current
            await observer.changed.wait()
        raise asyncio.CancelledError

    def detach(self, observer: LifecycleObserver) -> None:
        """Detach one observer without changing business execution."""
        if observer in self._observers:
            self._observers.remove(observer)
        observer.closed = True
        observer.changed.set()

    def detach_all(self) -> None:
        """Detach every observer during bounded Provider shutdown."""
        for observer in tuple(self._observers):
            self.detach(observer)

    def request_cancellation(
        self,
    ) -> tuple[
        operation_lifecycle_pb2.CancellationDisposition.ValueType,
        operation_lifecycle_pb2.OperationSnapshot,
    ]:
        """Make one atomic cooperative-cancellation decision."""
        current = self.snapshot()
        if current.state in _TERMINAL_STATES:
            return (
                operation_lifecycle_pb2.CANCELLATION_DISPOSITION_ALREADY_TERMINAL,
                current,
            )
        if (
            current.state
            == operation_lifecycle_pb2.OPERATION_STATE_CANCELLATION_REQUESTED
        ):
            return (
                operation_lifecycle_pb2.CANCELLATION_DISPOSITION_ALREADY_REQUESTED,
                current,
            )
        if not self._cancellable:
            return (
                operation_lifecycle_pb2.CANCELLATION_DISPOSITION_UNSUPPORTED,
                current,
            )
        requested = self._state_snapshot(
            operation_lifecycle_pb2.OPERATION_STATE_CANCELLATION_REQUESTED
        )
        self._commit(requested)
        self._cancellation.set()
        return (
            operation_lifecycle_pb2.CANCELLATION_DISPOSITION_REQUESTED,
            self.snapshot(),
        )

    async def execute(
        self,
        *,
        operation_id: str,
        execution_deadline: datetime,
        execution_context: dict[str, JsonValue],
        dispatch: _Dispatch,
    ) -> None:
        """Run author behavior once and retain one normalized outcome."""
        if self._cancellation.is_set():
            self._commit_cancelled(
                OperationEffects(
                    side_effects=OperationSideEffects.NONE,
                    cleanup=OperationCleanup.NOT_REQUIRED,
                    explanation="Execution was prevented from starting.",
                )
            )
            return
        self._commit(
            self._state_snapshot(
                operation_lifecycle_pb2.OPERATION_STATE_RUNNING
            )
        )
        context = OperationContext._create(
            operation_id=UUID(operation_id),
            execution_deadline=execution_deadline,
            execution_context=execution_context,
            reporter=self._report_progress,
            cancellation=self._cancellation,
        )
        try:
            remaining = (
                execution_deadline - datetime.now(UTC)
            ).total_seconds()
            if remaining <= 0:
                raise TimeoutError
            async with asyncio.timeout(remaining):
                result = await dispatch(context)
            if datetime.now(UTC) >= execution_deadline:
                raise TimeoutError
            self._validate_completion_policy()
            self._commit_success(result)
        except OperationCancelledError as cancelled:
            if self.snapshot().state != _CANCELLATION_REQUESTED:
                self._commit_runtime_failure(
                    "Operation reported cancellation without a request."
                )
            else:
                self._commit_cancelled(cancelled.effects)
        except OperationFailedError as failed:
            self._commit_failure(
                failed.code,
                failed.explanation,
                failed.effects,
            )
        except OperationProgressError:
            self._commit_failure(
                "stateforge.operation.invalid_progress",
                "Operation progress violated its declared policy.",
                _unknown_effects(),
            )
        except TimeoutError:
            self._commit_failure(
                "stateforge.operation.execution_deadline_exceeded",
                "Operation execution exceeded its deadline.",
                _unknown_effects(),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.error(
                "Provider operation execution failed",
                extra={"operation_id": operation_id},
            )
            self._commit_runtime_failure(
                "Provider operation execution failed."
            )

    async def _report_progress(
        self,
        message: str,
        percentage: float | None,
    ) -> None:
        """Validate policy and commit one current-progress replacement."""
        current = self.snapshot()
        if current.state not in {
            operation_lifecycle_pb2.OPERATION_STATE_RUNNING,
            _CANCELLATION_REQUESTED,
        }:
            raise OperationProgressError(
                "progress can only be reported while execution is active"
            )
        policy = self._progress_policy
        if policy is not None:
            if policy.require_message and not message.strip():
                raise OperationProgressError("progress message is required")
            if (
                policy.percentage_mode is ProgressPercentageMode.REQUIRED
                and percentage is None
            ):
                raise OperationProgressError("progress percentage is required")
            if (
                policy.percentage_mode is ProgressPercentageMode.FORBIDDEN
                and percentage is not None
            ):
                raise OperationProgressError(
                    "progress percentage is forbidden"
                )
            if percentage is not None:
                if (
                    policy.require_zero_start
                    and self._last_percentage is None
                    and percentage != 0
                ):
                    raise OperationProgressError(
                        "first progress percentage must be zero"
                    )
                if (
                    policy.monotonic
                    and self._last_percentage is not None
                    and percentage < self._last_percentage
                ):
                    raise OperationProgressError(
                        "progress percentage cannot decrease"
                    )
        candidate = self._state_snapshot(current.state)
        candidate.progress.sequence = candidate.sequence
        candidate.progress.updated_at.CopyFrom(candidate.updated_at)
        candidate.progress.message = message
        if percentage is not None:
            candidate.progress.percentage = percentage
        self._commit(candidate)
        if percentage is not None:
            self._last_percentage = percentage

    def _validate_completion_policy(self) -> None:
        """Require optional progress evidence before successful completion."""
        policy = self._progress_policy
        if policy is None:
            return
        current = self.snapshot()
        if policy.require_progress_on_success and not current.HasField(
            "progress"
        ):
            raise OperationProgressError(
                "successful operation requires a progress update"
            )
        if (
            policy.require_100_on_success
            and self._last_percentage != _COMPLETE_PERCENTAGE
        ):
            raise OperationProgressError(
                "successful operation requires progress to reach 100"
            )

    def _commit_success(self, result: ProviderModel) -> None:
        """Validate a typed result against the originally bound schema."""
        if not isinstance(result, self._result_model):
            self._commit_invalid_result()
            return
        serialized = result.model_dump(mode="json")
        if not self._result_validator.is_valid(serialized):
            self._commit_invalid_result()
            return
        try:
            result_message = ParseDict(serialized, Struct())
            candidate = self._state_snapshot(
                operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED
            )
            candidate.success.result.CopyFrom(result_message)
            self._commit(candidate)
        except (
            TypeError,
            ValueError,
            validation.OperationLifecycleValidationError,
        ):
            self._commit_invalid_result()

    def _commit_invalid_result(self) -> None:
        """Replace unsafe author output with a sanitized terminal failure."""
        self._commit_failure(
            "stateforge.operation.invalid_result",
            "Operation returned an invalid result.",
            _unknown_effects(),
        )

    def _commit_runtime_failure(self, explanation: str) -> None:
        """Normalize an unexpected runtime or author failure."""
        self._commit_failure(
            "stateforge.operation.provider_error",
            explanation,
            _unknown_effects(),
        )

    def _commit_failure(
        self,
        code: str,
        explanation: str,
        effects: OperationEffects,
    ) -> None:
        """Commit one sanitized failure or fall back to provider_error."""
        candidate = self._state_snapshot(
            operation_lifecycle_pb2.OPERATION_STATE_FAILED
        )
        candidate.failure.code = code
        candidate.failure.explanation = explanation
        _copy_effects(effects, candidate.failure.effects)
        try:
            self._commit(candidate)
        except validation.OperationLifecycleValidationError:
            fallback = self._state_snapshot(
                operation_lifecycle_pb2.OPERATION_STATE_FAILED
            )
            fallback.failure.code = "stateforge.operation.provider_error"
            fallback.failure.explanation = (
                "Provider operation execution failed."
            )
            _copy_effects(_unknown_effects(), fallback.failure.effects)
            self._commit(fallback)

    def _commit_cancelled(self, effects: OperationEffects) -> None:
        """Commit cancellation only after execution has stopped."""
        candidate = self._state_snapshot(
            operation_lifecycle_pb2.OPERATION_STATE_CANCELLED
        )
        _copy_effects(effects, candidate.cancellation.effects)
        try:
            self._commit(candidate)
        except validation.OperationLifecycleValidationError:
            self._commit_runtime_failure(
                "Provider returned invalid cancellation evidence."
            )

    def _state_snapshot(
        self,
        state: operation_lifecycle_pb2.OperationState.ValueType,
    ) -> operation_lifecycle_pb2.OperationSnapshot:
        """Build the next complete state while retaining latest progress."""
        current = self.snapshot()
        candidate = operation_lifecycle_pb2.OperationSnapshot(
            admission_record=current.admission_record,
            operation_identifier=current.operation_identifier,
            manifest_revision=current.manifest_revision,
            sequence=current.sequence + 1,
            state=state,
            updated_at=_timestamp(datetime.now(UTC)),
        )
        if current.HasField("progress"):
            candidate.progress.CopyFrom(current.progress)
        return candidate

    def _commit(
        self,
        candidate: operation_lifecycle_pb2.OperationSnapshot,
    ) -> None:
        """Validate and atomically retain one adjacent state transition."""
        current = self.snapshot()
        validation.validate_snapshot_transition(current, candidate)
        self._snapshot = candidate.SerializeToString()
        for observer in tuple(self._observers):
            observer.changed.set()


def _timestamp(value: datetime) -> Timestamp:
    """Create an independent protobuf timestamp."""
    timestamp = Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _unknown_effects() -> OperationEffects:
    """Return conservative effects when execution evidence is unavailable."""
    return OperationEffects(
        side_effects=OperationSideEffects.UNKNOWN,
        cleanup=OperationCleanup.UNKNOWN,
        explanation="Side effects and cleanup are unknown.",
    )


def _copy_effects(
    source: OperationEffects,
    target: operation_lifecycle_pb2.OperationEffects,
) -> None:
    """Adapt author effects into the private Protocol representation."""
    side_effects = {
        OperationSideEffects.NONE: (
            operation_lifecycle_pb2.SIDE_EFFECT_STATE_NONE
        ),
        OperationSideEffects.PRESENT: (
            operation_lifecycle_pb2.SIDE_EFFECT_STATE_PRESENT
        ),
        OperationSideEffects.UNKNOWN: (
            operation_lifecycle_pb2.SIDE_EFFECT_STATE_UNKNOWN
        ),
    }
    cleanup = {
        OperationCleanup.NOT_REQUIRED: (
            operation_lifecycle_pb2.CLEANUP_STATE_NOT_REQUIRED
        ),
        OperationCleanup.COMPLETED: (
            operation_lifecycle_pb2.CLEANUP_STATE_COMPLETED
        ),
        OperationCleanup.INCOMPLETE: (
            operation_lifecycle_pb2.CLEANUP_STATE_INCOMPLETE
        ),
        OperationCleanup.UNKNOWN: (
            operation_lifecycle_pb2.CLEANUP_STATE_UNKNOWN
        ),
    }
    target.side_effects = side_effects[source.side_effects]
    target.cleanup = cleanup[source.cleanup]
    target.explanation = source.explanation
