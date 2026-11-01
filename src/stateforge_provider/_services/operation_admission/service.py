"""Serve typed Provider operation admission over canonical SFP P4."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import NoReturn, cast
from uuid import UUID

import grpc
from google.protobuf.json_format import MessageToDict
from pydantic import JsonValue, ValidationError
from stateforge_protocol.sfp.operation_admission.v1 import (
    contract,
    operation_admission_pb2,
    operation_admission_pb2_grpc,
    validation,
)

from stateforge_provider._runtime.grpc import ProcedureRegistration
from stateforge_provider._runtime.identity import ProviderEndpointIdentity
from stateforge_provider._runtime.sessions import Session, SessionRegistry
from stateforge_provider._services.capability_assessment.declaration import (
    BoundRequirementRegistry,
)
from stateforge_provider._services.capability_assessment.evaluation import (
    RequirementEvaluationError,
    evaluate_requirements,
    required_checks,
)
from stateforge_provider._services.health.service import ProviderHealthService
from stateforge_provider._services.manifest.declaration import ManifestSnapshot
from stateforge_provider._services.operation_admission.declaration import (
    BoundOperation,
    BoundOperationRegistry,
)
from stateforge_provider._services.operation_admission.errors import (
    AdmissionFailureError,
)
from stateforge_provider._services.operation_admission.runtime import (
    AdmissionRegistryError,
    AdmissionRegistryFailure,
    OperationAdmissionRuntime,
)
from stateforge_provider.operations import OperationContext
from stateforge_provider.requirements import RequirementCheckOutcome
from stateforge_provider.version import ProtocolVersion

_LOGGER = logging.getLogger(__name__)
_RESOLVED_EXISTING = (
    operation_admission_pb2.ADMISSION_DISPOSITION_RESOLVED_EXISTING
)


class OperationAdmissionService(
    operation_admission_pb2_grpc.OperationAdmissionServiceServicer
):
    """Validate immutable invocations before exactly-once dispatch."""

    def __init__(
        self,
        *,
        endpoint: ProviderEndpointIdentity,
        snapshot: ManifestSnapshot,
        sessions: SessionRegistry,
        health: ProviderHealthService,
        requirements: BoundRequirementRegistry,
        operations: BoundOperationRegistry,
        runtime: OperationAdmissionRuntime,
    ) -> None:
        self._endpoint = endpoint
        self._manifest_revision = snapshot.manifest_revision
        self._sessions = sessions
        self._health = health
        self._requirements = requirements
        self._operations = operations
        self._runtime = runtime

    async def StartOperation(  # noqa: N802, PLR0912
        self,
        request: operation_admission_pb2.StartOperationRequest,
        context: grpc.aio.ServicerContext[
            operation_admission_pb2.StartOperationRequest,
            operation_admission_pb2.StartOperationResponse,
        ],
    ) -> operation_admission_pb2.StartOperationResponse:
        """Resolve or atomically admit one immutable operation invocation."""
        operation_id = request.invocation.operation_id
        try:
            validation.validate_start_operation_request(request)
        except validation.OperationAdmissionValidationError:
            await self._reject(
                context,
                AdmissionFailureError(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    operation_admission_pb2.ADMISSION_ERROR_REASON_INVALID_OPERATION_REQUEST,
                    "Invalid Operation Admission request",
                    operation_id,
                ),
            )

        invocation = request.invocation
        operation = self._operations.get(invocation.operation_identifier)
        if operation is None:
            await self._reject(
                context,
                AdmissionFailureError(
                    grpc.StatusCode.UNIMPLEMENTED,
                    operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_NOT_DECLARED,
                    "Operation is not declared by this Provider",
                    operation_id,
                ),
            )
        session = await self._validate_fences(request, context)
        try:
            self._validate_contract(invocation, operation)
            payload = self._validate_payload(invocation, operation)
        except AdmissionFailureError as failure:
            await self._reject(context, failure)
        fingerprint = validation.compute_request_fingerprint(invocation)

        try:
            existing = self._runtime.lookup(operation_id, fingerprint)
        except AdmissionRegistryError as error:
            await self._reject_registry(context, operation_id, error)
        if existing is not None:
            return await self._response(
                request,
                existing.record,
                False,
                context,
            )
        if (
            request.admission_mode
            == operation_admission_pb2.ADMISSION_MODE_RESOLVE_ONLY
        ):
            await self._reject(
                context,
                AdmissionFailureError(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_RECORD_UNAVAILABLE,
                    "Operation admission record is unavailable",
                    operation_id,
                ),
            )

        execution_deadline = invocation.execution_deadline.ToDatetime(
            tzinfo=UTC
        )
        if execution_deadline <= datetime.now(UTC):
            await self._reject(
                context,
                AdmissionFailureError(
                    grpc.StatusCode.DEADLINE_EXCEEDED,
                    operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_DEADLINE_EXPIRED,
                    "Operation execution deadline has elapsed",
                    operation_id,
                ),
            )
        if not self._health.is_serving():
            await self._reject_precondition(
                context, operation_id, "Provider is not currently serving"
            )

        try:
            identifiers = required_checks(
                self._requirements,
                (invocation.operation_identifier,),
            )
            evaluated = await evaluate_requirements(
                self._requirements, identifiers
            )
        except RequirementEvaluationError:
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Provider requirement evaluation failed",
            )
        if execution_deadline <= datetime.now(UTC):
            await self._reject(
                context,
                AdmissionFailureError(
                    grpc.StatusCode.DEADLINE_EXCEEDED,
                    operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_DEADLINE_EXPIRED,
                    "Operation execution deadline elapsed during admission",
                    operation_id,
                ),
            )
        incompatible = any(
            item.result.outcome is RequirementCheckOutcome.INCOMPATIBLE
            for item in evaluated.values()
        )
        if incompatible:
            await self._reject(
                context,
                AdmissionFailureError(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_INCOMPATIBLE,
                    "Operation is incompatible with the current runtime",
                    operation_id,
                ),
            )
        if any(
            item.result.outcome is not RequirementCheckOutcome.SATISFIED
            for item in evaluated.values()
        ):
            await self._reject_precondition(
                context,
                operation_id,
                "Operation runtime requirements are not satisfied",
            )
        if (
            self._sessions.get(request.session_binding.expected_session_id)
            is not session
            or not self._health.is_serving()
        ):
            await self._reject_precondition(
                context,
                operation_id,
                "Operation Admission prerequisites changed",
            )

        dispatch = self._dispatch(operation, invocation, payload)
        try:
            decision = self._runtime.admit(
                operation_id=operation_id,
                fingerprint=fingerprint,
                endpoint_generation=self._endpoint.endpoint_generation,
                dispatch=dispatch,
            )
        except AdmissionRegistryError as error:
            await self._reject_registry(context, operation_id, error)
        return await self._response(
            request,
            decision.record,
            decision.accepted_new,
            context,
        )

    async def _validate_fences(
        self,
        request: operation_admission_pb2.StartOperationRequest,
        context: grpc.aio.ServicerContext[
            operation_admission_pb2.StartOperationRequest,
            operation_admission_pb2.StartOperationResponse,
        ],
    ) -> Session:
        """Require the exact current endpoint, session, and manifest."""
        binding = request.session_binding
        session = self._sessions.get(binding.expected_session_id)
        if session is None or (
            binding.expected_provider_instance_id
            != str(self._endpoint.provider_instance_id)
            or binding.expected_endpoint_generation
            != self._endpoint.endpoint_generation
            or session.endpoint != self._endpoint
            or session.version != ProtocolVersion(1, 0)
            or request.invocation.contract.manifest_revision
            != self._manifest_revision
        ):
            await self._reject_precondition(
                context,
                request.invocation.operation_id,
                "Operation Admission session or manifest is stale",
            )
        return session

    def _validate_contract(
        self,
        invocation: operation_admission_pb2.OperationInvocation,
        operation: BoundOperation,
    ) -> None:
        """Validate requested profile claims against the accepted manifest."""
        if any(
            role not in operation.declaration.implements
            for role in invocation.contract.required_implementation_roles
        ):
            raise AdmissionFailureError(
                grpc.StatusCode.FAILED_PRECONDITION,
                operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_INCOMPATIBLE,
                "Operation requires an undeclared implementation role",
                invocation.operation_id,
            )

    def _validate_payload(
        self,
        invocation: operation_admission_pb2.OperationInvocation,
        operation: BoundOperation,
    ) -> object:
        """Validate and construct one typed author request without defaults."""
        payload = cast(dict[str, JsonValue], MessageToDict(invocation.payload))
        if not operation.input_validator.is_valid(payload):
            raise AdmissionFailureError(
                grpc.StatusCode.INVALID_ARGUMENT,
                operation_admission_pb2.ADMISSION_ERROR_REASON_INVALID_OPERATION_REQUEST,
                "Operation payload does not match its declared schema",
                invocation.operation_id,
            )
        try:
            return operation.declaration.request_model.model_validate(payload)
        except ValidationError:
            raise AdmissionFailureError(
                grpc.StatusCode.INVALID_ARGUMENT,
                operation_admission_pb2.ADMISSION_ERROR_REASON_INVALID_OPERATION_REQUEST,
                "Operation payload is invalid",
                invocation.operation_id,
            ) from None

    def _dispatch(
        self,
        operation: BoundOperation,
        invocation: operation_admission_pb2.OperationInvocation,
        payload: object,
    ) -> Callable[[], Awaitable[None]]:
        """Capture typed immutable inputs for post-record dispatch."""
        operation_context = OperationContext._create(
            operation_id=UUID(invocation.operation_id),
            execution_deadline=invocation.execution_deadline.ToDatetime(
                tzinfo=UTC
            ),
            execution_context=cast(
                dict[str, JsonValue],
                MessageToDict(invocation.execution_context),
            ),
        )

        async def dispatch() -> None:
            if operation.declaration.accepts_context:
                result = await operation.handler(payload, operation_context)
            else:
                result = await operation.handler(payload)
            if not isinstance(result, operation.declaration.result_model):
                raise TypeError("operation returned an invalid result type")
            serialized = result.model_dump(mode="json")
            if not operation.result_validator.is_valid(serialized):
                raise ValueError("operation result violates its schema")

        return dispatch

    async def _response(
        self,
        request: operation_admission_pb2.StartOperationRequest,
        record: operation_admission_pb2.OperationAdmissionRecord,
        accepted_new: bool,
        context: grpc.aio.ServicerContext[
            operation_admission_pb2.StartOperationRequest,
            operation_admission_pb2.StartOperationResponse,
        ],
    ) -> operation_admission_pb2.StartOperationResponse:
        """Build and validate one request-correlated admission response."""
        response = operation_admission_pb2.StartOperationResponse(
            provider_instance_id=str(self._endpoint.provider_instance_id),
            endpoint_generation=self._endpoint.endpoint_generation,
            session_id=request.session_binding.expected_session_id,
            manifest_revision=self._manifest_revision,
            disposition=(
                operation_admission_pb2.ADMISSION_DISPOSITION_ACCEPTED_NEW
                if accepted_new
                else _RESOLVED_EXISTING
            ),
            record=record,
        )
        try:
            validation.validate_admission_exchange(request, response)
        except validation.OperationAdmissionValidationError:
            _LOGGER.error("Provider produced an invalid admission response")
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Provider produced an invalid Operation Admission response",
            )
        return response

    async def _reject_precondition(
        self,
        context: grpc.aio.ServicerContext[
            operation_admission_pb2.StartOperationRequest,
            operation_admission_pb2.StartOperationResponse,
        ],
        operation_id: str,
        explanation: str,
    ) -> NoReturn:
        await self._reject(
            context,
            AdmissionFailureError(
                grpc.StatusCode.FAILED_PRECONDITION,
                operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_PRECONDITION_FAILED,
                explanation,
                operation_id,
            ),
        )

    async def _reject_registry(
        self,
        context: grpc.aio.ServicerContext[
            operation_admission_pb2.StartOperationRequest,
            operation_admission_pb2.StartOperationResponse,
        ],
        operation_id: str,
        error: AdmissionRegistryError,
    ) -> NoReturn:
        failure = {
            AdmissionRegistryFailure.CONFLICT: AdmissionFailureError(
                grpc.StatusCode.ALREADY_EXISTS,
                operation_admission_pb2.ADMISSION_ERROR_REASON_IDEMPOTENCY_CONFLICT,
                "Operation ID is bound to different immutable content",
                operation_id,
            ),
            AdmissionRegistryFailure.EXPIRED: AdmissionFailureError(
                grpc.StatusCode.FAILED_PRECONDITION,
                operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_RECORD_EXPIRED,
                "Operation admission record has expired",
                operation_id,
            ),
            AdmissionRegistryFailure.UNAVAILABLE: AdmissionFailureError(
                grpc.StatusCode.FAILED_PRECONDITION,
                operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_RECORD_UNAVAILABLE,
                "Operation admission record is unavailable",
                operation_id,
            ),
            AdmissionRegistryFailure.CAPACITY: AdmissionFailureError(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                operation_admission_pb2.ADMISSION_ERROR_REASON_PROVIDER_CAPACITY_EXHAUSTED,
                "Provider admission capacity is exhausted",
                operation_id,
                True,
            ),
            AdmissionRegistryFailure.STOPPING: AdmissionFailureError(
                grpc.StatusCode.UNAVAILABLE,
                operation_admission_pb2.ADMISSION_ERROR_REASON_PROVIDER_UNAVAILABLE,
                "Provider operation runtime is stopping",
                operation_id,
                True,
            ),
        }[error.failure]
        await self._reject(context, failure)

    async def _reject(
        self,
        context: grpc.aio.ServicerContext[
            operation_admission_pb2.StartOperationRequest,
            operation_admission_pb2.StartOperationResponse,
        ],
        failure: AdmissionFailureError,
    ) -> NoReturn:
        await context.abort_with_status(failure.status())
        raise AssertionError("gRPC abort returned")


def registration(
    *,
    endpoint: ProviderEndpointIdentity,
    snapshot: ManifestSnapshot,
    sessions: SessionRegistry,
    health: ProviderHealthService,
    requirements: BoundRequirementRegistry,
    operations: BoundOperationRegistry,
    runtime: OperationAdmissionRuntime,
) -> ProcedureRegistration:
    """Build the bounded P4 registration for one Provider generation."""
    service = OperationAdmissionService(
        endpoint=endpoint,
        snapshot=snapshot,
        sessions=sessions,
        health=health,
        requirements=requirements,
        operations=operations,
        runtime=runtime,
    )
    return ProcedureRegistration(
        name=contract.SERVICE_NAME,
        max_request_bytes=contract.MAX_REQUEST_BYTES,
        max_response_bytes=contract.MAX_RESPONSE_BYTES,
        install=lambda server: (
            operation_admission_pb2_grpc.add_OperationAdmissionServiceServicer_to_server(
                service, server
            )
        ),
    )
