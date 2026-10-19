"""Serve Provider-owned runtime requirement assessments over P2."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import uuid4

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from stateforge_protocol.sfp.capability_assessment.v1 import (
    capability_assessment_pb2,
    capability_assessment_pb2_grpc,
    contract,
    validation,
)

from stateforge_provider._runtime.grpc import ProcedureRegistration
from stateforge_provider._runtime.identity import ProviderEndpointIdentity
from stateforge_provider._runtime.sessions import Session, SessionRegistry
from stateforge_provider._services.capability_assessment.declaration import (
    BoundRequirementRegistry,
    RequirementDeclaration,
)
from stateforge_provider._services.health.service import ProviderHealthService
from stateforge_provider._services.manifest.declaration import ManifestSnapshot
from stateforge_provider.requirements import (
    RequirementCheckOutcome,
    RequirementCheckResult,
)
from stateforge_provider.version import ProtocolVersion

_LOGGER = logging.getLogger(__name__)

_SUPPORTED_WITH_REQUIREMENTS = (
    capability_assessment_pb2.SUPPORT_STATE_SUPPORTED_WITH_REQUIREMENTS
)
_INCOMPATIBLE_EXPLANATION = "A runtime requirement is incompatible"
_UNKNOWN_EXPLANATION = "Runtime requirement evidence is unavailable"


@dataclass(frozen=True, slots=True)
class _EvaluatedRequirement:
    """Pair validated declaration metadata with one author result."""

    declaration: RequirementDeclaration
    result: RequirementCheckResult


class _CheckError(Exception):
    """Hide author failure details from the remote RPC boundary."""


class CapabilityAssessmentService(
    capability_assessment_pb2_grpc.CapabilityAssessmentServiceServicer
):
    """Adapt private Provider checks to the canonical P2 wire contract."""

    def __init__(
        self,
        *,
        endpoint: ProviderEndpointIdentity,
        snapshot: ManifestSnapshot,
        sessions: SessionRegistry,
        health: ProviderHealthService,
        requirements: BoundRequirementRegistry,
    ) -> None:
        self._endpoint = endpoint
        self._manifest_revision = snapshot.manifest_revision
        self._declared_operations = snapshot.operation_identifiers
        self._sessions = sessions
        self._health = health
        self._requirements = requirements

    # Keep validation and error translation in one auditable RPC boundary.
    async def AssessCapabilities(  # noqa: N802, PLR0912
        self,
        request: capability_assessment_pb2.AssessCapabilitiesRequest,
        context: grpc.aio.ServicerContext[
            capability_assessment_pb2.AssessCapabilitiesRequest,
            capability_assessment_pb2.AssessCapabilitiesResponse,
        ],
    ) -> capability_assessment_pb2.AssessCapabilitiesResponse:
        """Evaluate each referenced requirement once without dispatching."""
        if request.ByteSize() > contract.MAX_REQUEST_BYTES:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Capability Assessment request limit exceeded",
            )
        try:
            validation.validate_assess_capabilities_request(request)
        except validation.CapabilityAssessmentValidationError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Invalid Capability Assessment request",
            )

        session = await self._validate_fences(request, context)
        if not self._health.is_serving():
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Provider is not ready for Capability Assessment",
            )

        try:
            requirement_ids = self._required_checks(request)
            results = await self._execute_checks(requirement_ids)
        except _CheckError:
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Provider requirement check failed",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Provider failed to evaluate Capability Assessment"
            )
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Capability Assessment response is unavailable",
            )

        if context.cancelled():
            raise asyncio.CancelledError
        if self._sessions.get(request.expected_session_id) is not session:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Capability Assessment session is no longer active",
            )
        if not self._health.is_serving():
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Provider readiness changed during Capability Assessment",
            )

        try:
            response = self._response(request, results)
            response_size = response.ByteSize()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Provider failed to construct Capability Assessment response"
            )
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Capability Assessment response is unavailable",
            )
        if response_size > contract.MAX_RESPONSE_BYTES:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Capability Assessment response limit exceeded",
            )
        try:
            validation.validate_assessment_exchange(request, response)
        except validation.CapabilityAssessmentValidationError:
            _LOGGER.exception(
                "Provider produced an invalid Capability Assessment response"
            )
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Capability Assessment response is unavailable",
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Provider failed to validate Capability Assessment response"
            )
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Capability Assessment response is unavailable",
            )
        return response

    async def _validate_fences(
        self,
        request: capability_assessment_pb2.AssessCapabilitiesRequest,
        context: grpc.aio.ServicerContext[
            capability_assessment_pb2.AssessCapabilitiesRequest,
            capability_assessment_pb2.AssessCapabilitiesResponse,
        ],
    ) -> Session:
        """Validate Provider-owned session, manifest, and operation state."""
        session = self._sessions.get(request.expected_session_id)
        if session is None or (
            request.expected_provider_instance_id
            != str(self._endpoint.provider_instance_id)
            or request.expected_endpoint_generation
            != self._endpoint.endpoint_generation
            or session.endpoint != self._endpoint
            or session.version != ProtocolVersion(1, 0)
        ):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Capability Assessment session is not active for this "
                "endpoint",
            )
        if request.expected_manifest_revision != self._manifest_revision:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Capability Assessment manifest revision is stale",
            )
        if any(
            identifier not in self._declared_operations
            for identifier in request.operation_identifiers
        ):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Capability Assessment operation is not declared",
            )
        return session

    def _required_checks(
        self,
        request: capability_assessment_pb2.AssessCapabilitiesRequest,
    ) -> tuple[str, ...]:
        """Collect unique checks in stable first-reference order."""
        identifiers: list[str] = []
        seen: set[str] = set()
        for operation in request.operation_identifiers:
            for identifier in self._requirements.operation_requirements[
                operation
            ]:
                if identifier not in seen:
                    seen.add(identifier)
                    identifiers.append(identifier)
        return tuple(identifiers)

    async def _execute_checks(
        self,
        identifiers: tuple[str, ...],
    ) -> dict[str, _EvaluatedRequirement]:
        """Run each distinct author check once and cancel peers on failure."""
        tasks = {
            identifier: asyncio.create_task(self._invoke_check(identifier))
            for identifier in identifiers
        }
        try:
            values = await asyncio.gather(*tasks.values())
        except BaseException:
            for task in tasks.values():
                task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
            raise
        return dict(zip(tasks, values, strict=True))

    async def _invoke_check(
        self,
        identifier: str,
    ) -> _EvaluatedRequirement:
        """Normalize one author check without leaking its failure remotely."""
        check = self._requirements.checks[identifier]
        try:
            result: object = await check()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception(
                "Provider requirement check failed",
                extra={"requirement_id": identifier},
            )
            raise _CheckError from None
        if not isinstance(result, RequirementCheckResult):
            _LOGGER.error(
                "Provider requirement check returned an invalid result",
                extra={"requirement_id": identifier},
            )
            raise _CheckError
        return _EvaluatedRequirement(
            self._requirements.declarations[identifier],
            result,
        )

    def _response(
        self,
        request: capability_assessment_pb2.AssessCapabilitiesRequest,
        results: dict[str, _EvaluatedRequirement],
    ) -> capability_assessment_pb2.AssessCapabilitiesResponse:
        """Build one deterministic request-correlated response."""
        timestamp = Timestamp()
        timestamp.GetCurrentTime()
        return capability_assessment_pb2.AssessCapabilitiesResponse(
            assessment_request_id=request.assessment_request_id,
            provider_instance_id=str(self._endpoint.provider_instance_id),
            endpoint_generation=self._endpoint.endpoint_generation,
            session_id=request.expected_session_id,
            manifest_revision=self._manifest_revision,
            assessment_id=str(uuid4()),
            assessment_timestamp=timestamp,
            findings=(
                self._finding(operation, results)
                for operation in request.operation_identifiers
            ),
        )

    def _finding(
        self,
        operation: str,
        results: dict[str, _EvaluatedRequirement],
    ) -> capability_assessment_pb2.CapabilityFinding:
        """Aggregate one operation using the locked precedence rules."""
        evaluated = tuple(
            results[identifier]
            for identifier in self._requirements.operation_requirements[
                operation
            ]
        )
        outcomes = {item.result.outcome for item in evaluated}
        reasons: tuple[capability_assessment_pb2.ReasonDetail, ...] = ()
        if RequirementCheckOutcome.INCOMPATIBLE in outcomes:
            support = capability_assessment_pb2.SUPPORT_STATE_UNSUPPORTED
            reasons = (
                _reason(
                    contract.REASON_CODE_REQUIREMENT_UNMET,
                    _explanation(
                        evaluated, RequirementCheckOutcome.INCOMPATIBLE
                    ),
                ),
            )
        elif RequirementCheckOutcome.UNKNOWN in outcomes:
            support = capability_assessment_pb2.SUPPORT_STATE_INDETERMINATE
            reasons = (
                _reason(
                    contract.REASON_CODE_INSUFFICIENT_EVIDENCE,
                    _explanation(evaluated, RequirementCheckOutcome.UNKNOWN),
                ),
            )
        elif RequirementCheckOutcome.UNSATISFIED in outcomes:
            support = _SUPPORTED_WITH_REQUIREMENTS
        else:
            support = capability_assessment_pb2.SUPPORT_STATE_SUPPORTED
        return capability_assessment_pb2.CapabilityFinding(
            operation_identifier=operation,
            support_state=support,
            requirement_findings=(
                _requirement_finding(item) for item in evaluated
            ),
            reasons=reasons,
        )


def _requirement_finding(
    evaluated: _EvaluatedRequirement,
) -> capability_assessment_pb2.RequirementFinding:
    """Adapt one typed author result to a bounded P2 finding."""
    state = {
        RequirementCheckOutcome.SATISFIED: (
            capability_assessment_pb2.REQUIREMENT_STATE_SATISFIED
        ),
        RequirementCheckOutcome.UNSATISFIED: (
            capability_assessment_pb2.REQUIREMENT_STATE_UNSATISFIED
        ),
        RequirementCheckOutcome.INCOMPATIBLE: (
            capability_assessment_pb2.REQUIREMENT_STATE_UNSATISFIED
        ),
        RequirementCheckOutcome.UNKNOWN: (
            capability_assessment_pb2.REQUIREMENT_STATE_UNKNOWN
        ),
    }[evaluated.result.outcome]
    declaration = evaluated.declaration
    return capability_assessment_pb2.RequirementFinding(
        requirement_id=declaration.identifier,
        state=state,
        description=declaration.description,
        version_constraint=declaration.version_constraint,
    )


def _explanation(
    evaluated: tuple[_EvaluatedRequirement, ...],
    outcome: RequirementCheckOutcome,
) -> str:
    """Select a bounded nonempty explanation for a normalized reason."""
    item = next(item for item in evaluated if item.result.outcome is outcome)
    if item.result.explanation:
        return item.result.explanation
    return {
        RequirementCheckOutcome.INCOMPATIBLE: _INCOMPATIBLE_EXPLANATION,
        RequirementCheckOutcome.UNKNOWN: _UNKNOWN_EXPLANATION,
    }[outcome]


def _reason(
    code: str,
    explanation: str,
) -> capability_assessment_pb2.ReasonDetail:
    """Build one canonical machine-readable reason."""
    return capability_assessment_pb2.ReasonDetail(
        reason_code=code,
        explanation=explanation,
    )


def registration(
    *,
    endpoint: ProviderEndpointIdentity,
    snapshot: ManifestSnapshot,
    sessions: SessionRegistry,
    health: ProviderHealthService,
    requirements: BoundRequirementRegistry,
) -> ProcedureRegistration:
    """Build the bounded P2 registration for one Provider generation."""
    service = CapabilityAssessmentService(
        endpoint=endpoint,
        snapshot=snapshot,
        sessions=sessions,
        health=health,
        requirements=requirements,
    )

    def install(server: grpc.aio.Server) -> None:
        capability_assessment_pb2_grpc.add_CapabilityAssessmentServiceServicer_to_server(
            service,
            server,
        )

    return ProcedureRegistration(
        name=contract.SERVICE_NAME,
        max_request_bytes=contract.MAX_REQUEST_BYTES,
        max_response_bytes=contract.MAX_RESPONSE_BYTES,
        install=install,
    )
