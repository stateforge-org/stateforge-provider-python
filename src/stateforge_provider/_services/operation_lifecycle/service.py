"""Serve retained operation state and cooperative cancellation over P5."""

from __future__ import annotations

import asyncio
from typing import NoReturn, TypeVar

import grpc
from stateforge_protocol.sfp.operation_admission.v1 import (
    operation_admission_pb2,
)
from stateforge_protocol.sfp.operation_lifecycle.v1 import (
    contract,
    operation_lifecycle_pb2,
    operation_lifecycle_pb2_grpc,
    validation,
)

from stateforge_provider._runtime.grpc import ProcedureRegistration
from stateforge_provider._runtime.identity import ProviderEndpointIdentity
from stateforge_provider._runtime.sessions import SessionRegistry
from stateforge_provider._services.operation_admission.runtime import (
    AdmissionRegistryError,
    AdmissionRegistryFailure,
    OperationAdmissionRuntime,
)
from stateforge_provider._services.operation_lifecycle.errors import (
    LifecycleFailureError,
)
from stateforge_provider._services.operation_lifecycle.runtime import (
    LifecycleCursorAheadError,
    LifecycleObserver,
    LifecycleObserverCapacityError,
    OperationLifecycleRecord,
)
from stateforge_provider.version import ProtocolVersion

_TERMINAL_STATES = frozenset(
    {
        operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED,
        operation_lifecycle_pb2.OPERATION_STATE_FAILED,
        operation_lifecycle_pb2.OPERATION_STATE_CANCELLED,
    }
)
_Request = TypeVar("_Request")
_Response = TypeVar("_Response")


class OperationLifecycleService(
    operation_lifecycle_pb2_grpc.OperationLifecycleServiceServicer
):
    """Observe or cancel work already admitted through P4."""

    def __init__(
        self,
        *,
        endpoint: ProviderEndpointIdentity,
        sessions: SessionRegistry,
        runtime: OperationAdmissionRuntime,
        delivery_timeout_seconds: float,
    ) -> None:
        self._endpoint = endpoint
        self._sessions = sessions
        self._runtime = runtime
        self._delivery_timeout_seconds = delivery_timeout_seconds

    async def WatchOperation(  # type: ignore[override]  # noqa: N802
        self,
        request: operation_lifecycle_pb2.WatchOperationRequest,
        context: grpc.aio.ServicerContext[
            operation_lifecycle_pb2.WatchOperationRequest,
            operation_lifecycle_pb2.WatchOperationResponse,
        ],
    ) -> None:
        """Replay current state and write newer complete snapshots."""
        operation_id = request.operation_id
        try:
            validation.validate_watch_operation_request(request)
        except validation.OperationLifecycleValidationError:
            await self._reject(
                context,
                _failure(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_INVALID_REQUEST,
                    "Invalid Operation Lifecycle Watch request",
                    operation_id,
                ),
            )
        try:
            self._validate_fences(request.session_binding, operation_id)
            record = self._resolve(
                operation_id,
                request.expected_request_fingerprint,
            )
        except LifecycleFailureError as failure:
            await self._reject(context, failure)
        observer: LifecycleObserver | None = None
        try:
            try:
                observer, snapshot = record.attach(request.after_sequence)
            except LifecycleCursorAheadError:
                await self._reject(
                    context,
                    _failure(
                        grpc.StatusCode.OUT_OF_RANGE,
                        operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_CURSOR_AHEAD,
                        "Operation cursor is newer than retained state",
                        operation_id,
                    ),
                )
            except LifecycleObserverCapacityError:
                await self._reject(
                    context,
                    _failure(
                        grpc.StatusCode.RESOURCE_EXHAUSTED,
                        operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_OBSERVER_CAPACITY_EXHAUSTED,
                        "Operation observer capacity is exhausted",
                        operation_id,
                    ),
                )
            previous_sequence = request.after_sequence
            while True:
                try:
                    self._validate_fences(
                        request.session_binding, operation_id
                    )
                except LifecycleFailureError as failure:
                    await self._reject(context, failure)
                response = operation_lifecycle_pb2.WatchOperationResponse(
                    provider_instance_id=str(
                        self._endpoint.provider_instance_id
                    ),
                    endpoint_generation=self._endpoint.endpoint_generation,
                    session_id=request.session_binding.expected_session_id,
                    snapshot=snapshot,
                    updates_skipped=(
                        previous_sequence > 0
                        and snapshot.sequence > previous_sequence + 1
                    ),
                )
                try:
                    validation.validate_watch_exchange(
                        request,
                        response,
                        previous_sequence=(
                            None
                            if previous_sequence == request.after_sequence
                            else previous_sequence
                        ),
                    )
                    async with asyncio.timeout(self._delivery_timeout_seconds):
                        await context.write(response)
                except TimeoutError:
                    await self._reject(
                        context,
                        _failure(
                            grpc.StatusCode.RESOURCE_EXHAUSTED,
                            operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_SLOW_OBSERVER,
                            "Operation observer delivery stalled",
                            operation_id,
                        ),
                    )
                if snapshot.state in _TERMINAL_STATES:
                    return
                previous_sequence = snapshot.sequence
                snapshot = await record.next_snapshot(
                    observer,
                    previous_sequence,
                )
        finally:
            if observer is not None:
                record.detach(observer)

    async def CancelOperation(  # noqa: N802
        self,
        request: operation_lifecycle_pb2.CancelOperationRequest,
        context: grpc.aio.ServicerContext[
            operation_lifecycle_pb2.CancelOperationRequest,
            operation_lifecycle_pb2.CancelOperationResponse,
        ],
    ) -> operation_lifecycle_pb2.CancelOperationResponse:
        """Return one atomic cooperative-cancellation decision."""
        operation_id = request.operation_id
        try:
            validation.validate_cancel_operation_request(request)
        except validation.OperationLifecycleValidationError:
            await self._reject(
                context,
                _failure(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_INVALID_REQUEST,
                    "Invalid Operation Lifecycle Cancel request",
                    operation_id,
                ),
            )
        try:
            self._validate_fences(request.session_binding, operation_id)
            record = self._resolve(
                operation_id,
                request.expected_request_fingerprint,
            )
        except LifecycleFailureError as failure:
            await self._reject(context, failure)
        disposition, snapshot = record.request_cancellation()
        response = operation_lifecycle_pb2.CancelOperationResponse(
            provider_instance_id=str(self._endpoint.provider_instance_id),
            endpoint_generation=self._endpoint.endpoint_generation,
            session_id=request.session_binding.expected_session_id,
            disposition=disposition,
            snapshot=snapshot,
        )
        try:
            validation.validate_cancel_exchange(request, response)
        except validation.OperationLifecycleValidationError:
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Provider produced an invalid Operation Lifecycle response",
            )
        return response

    def _resolve(
        self,
        operation_id: str,
        fingerprint: str,
    ) -> OperationLifecycleRecord:
        """Resolve one exact retained lifecycle record."""
        try:
            return self._runtime.resolve_lifecycle(operation_id, fingerprint)
        except AdmissionRegistryError as error:
            failures = {
                AdmissionRegistryFailure.CONFLICT: _failure(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_FINGERPRINT_MISMATCH,
                    "Operation fingerprint does not match retained state",
                    operation_id,
                ),
                AdmissionRegistryFailure.EXPIRED: _failure(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_OPERATION_RECORD_EXPIRED,
                    "Operation record has expired",
                    operation_id,
                ),
                AdmissionRegistryFailure.UNAVAILABLE: _failure(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_OPERATION_RECORD_UNAVAILABLE,
                    "Operation record is unavailable",
                    operation_id,
                ),
                AdmissionRegistryFailure.CAPACITY: _failure(
                    grpc.StatusCode.RESOURCE_EXHAUSTED,
                    operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_OBSERVER_CAPACITY_EXHAUSTED,
                    "Operation lifecycle capacity is exhausted",
                    operation_id,
                ),
                AdmissionRegistryFailure.STOPPING: _failure(
                    grpc.StatusCode.UNAVAILABLE,
                    operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_PROVIDER_UNAVAILABLE,
                    "Provider operation runtime is stopping",
                    operation_id,
                ),
            }
            raise failures[error.failure] from error

    def _validate_fences(
        self,
        binding: operation_admission_pb2.OperationSessionBinding,
        operation_id: str,
    ) -> None:
        """Require the exact active Provider endpoint and SFP session."""
        session = self._sessions.get(binding.expected_session_id)
        if session is None or (
            binding.expected_provider_instance_id
            != str(self._endpoint.provider_instance_id)
            or binding.expected_endpoint_generation
            != self._endpoint.endpoint_generation
            or session.endpoint != self._endpoint
            or session.version != ProtocolVersion(1, 0)
        ):
            raise _failure(
                grpc.StatusCode.FAILED_PRECONDITION,
                operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_SESSION_PRECONDITION_FAILED,
                "Operation Lifecycle session is stale or inactive",
                operation_id,
            )

    async def _reject(
        self,
        context: grpc.aio.ServicerContext[_Request, _Response],
        failure: LifecycleFailureError,
    ) -> NoReturn:
        """Abort one RPC with a bounded versioned error detail."""
        await context.abort_with_status(failure.status())
        raise AssertionError("gRPC abort returned")


def _failure(
    code: grpc.StatusCode,
    reason: operation_lifecycle_pb2.LifecycleErrorReason.ValueType,
    explanation: str,
    operation_id: str,
) -> LifecycleFailureError:
    """Build one sanitized lifecycle failure."""
    return LifecycleFailureError(code, reason, explanation, operation_id)


def registration(
    *,
    endpoint: ProviderEndpointIdentity,
    sessions: SessionRegistry,
    runtime: OperationAdmissionRuntime,
    delivery_timeout_seconds: float,
) -> ProcedureRegistration:
    """Build the bounded P5 registration for one Provider generation."""
    service = OperationLifecycleService(
        endpoint=endpoint,
        sessions=sessions,
        runtime=runtime,
        delivery_timeout_seconds=delivery_timeout_seconds,
    )
    return ProcedureRegistration(
        name=contract.SERVICE_NAME,
        max_request_bytes=contract.MAX_REQUEST_BYTES,
        max_response_bytes=contract.MAX_RESPONSE_BYTES,
        install=lambda server: (
            operation_lifecycle_pb2_grpc.add_OperationLifecycleServiceServicer_to_server(
                service, server
            )
        ),
    )
