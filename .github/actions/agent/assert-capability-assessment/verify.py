"""Verify Capability Assessment across installed Agent and Provider builds."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from uuid import UUID, uuid4

import grpc
from google.protobuf import struct_pb2
from google.protobuf.json_format import ParseDict
from google.protobuf.message import Message
from stateforge_agent._sfp import (
    CapabilityAssessment,
    CapabilityRequirementState,
    CapabilitySupportState,
    ProviderAvailabilityState,
    ProviderSession,
    ProviderSessionManager,
    SfpCapabilityAssessmentLimitError,
    SfpCapabilityAssessmentMalformedResponseError,
    SfpCapabilityAssessmentRequestError,
    SfpCapabilityAssessmentStaleError,
    SfpCapabilityAssessmentUnavailableError,
    SfpVersion,
)
from stateforge_agent._sfp._runtime.channel import create_provider_channel
from stateforge_agent._sfp._runtime.descriptor import (
    ProviderDescriptorError,
    ProviderEndpointDescriptor,
    load_provider_descriptor,
)
from stateforge_agent._sfp._services.capability_assessment import (
    CapabilityAssessmentClient,
    CapabilityAssessmentScope,
)
from stateforge_protocol.sfp.capability_assessment.v1 import (
    capability_assessment_pb2,
    capability_assessment_pb2_grpc,
    contract,
)

_DISCOVERY_DIRECTORY = Path("/run/stateforge-agent/providers")
_OPERATIONS = (
    "stateforge.test/inspect@1",
    "stateforge.test/snapshot@1",
    "stateforge.test/unsupported@1",
    "stateforge.test/indeterminate@1",
)
_EXPECTED_STATES = (
    CapabilitySupportState.SUPPORTED,
    CapabilitySupportState.SUPPORTED_WITH_REQUIREMENTS,
    CapabilitySupportState.UNSUPPORTED,
    CapabilitySupportState.INDETERMINATE,
)
_EXPECTED_RETRY_ATTEMPTS = 2
_CANCELLABLE_OPERATION = "stateforge.test/cancellable@1"
_BOUNDARY_OPERATIONS = tuple(
    f"stateforge.test/boundary_{index:02d}@1" for index in range(64)
)
_MAX_SINGLE_BYTE_VARINT = 0x7F
_VARINT_CONTINUATION_BIT = 0x80


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-instance-id", type=UUID, required=True)
    parser.add_argument("--descriptor-path", type=Path, required=True)
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument("--target-path", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--unit-name", required=True)
    return parser.parse_args()


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _events(path: Path) -> tuple[str, ...]:
    try:
        return tuple(path.read_text(encoding="utf-8").splitlines())
    except FileNotFoundError:
        return ()


async def _wait_for_event(path: Path, event: str) -> None:
    """Wait until the separate Provider process records one event."""
    async with asyncio.timeout(10):
        # The independently running Provider cannot signal this event loop.
        while event not in _events(path):  # noqa: ASYNC110
            await asyncio.sleep(0.01)


def _varint(value: int) -> bytes:
    """Encode one nonnegative protobuf integer for a test-only field."""
    encoded = bytearray()
    while value > _MAX_SINGLE_BYTE_VARINT:
        encoded.append(
            (value & _MAX_SINGLE_BYTE_VARINT) | _VARINT_CONTINUATION_BIT
        )
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _message_with_serialized_size(
    message: Message,
    target_size: int,
) -> Message:
    """Pad a protobuf with one ignored field to an exact wire size."""
    content = message.SerializeToString()
    tag = _varint((2_047 << 3) | 2)
    payload_size = target_size - len(content) - len(tag) - 1
    while True:
        encoded_size = _varint(payload_size)
        adjusted = target_size - len(content) - len(tag) - len(encoded_size)
        if adjusted == payload_size:
            break
        payload_size = adjusted
    if payload_size < 0:
        raise ValueError("target size is smaller than the message")
    result = type(message).FromString(
        content + tag + encoded_size + (b"x" * payload_size)
    )
    if result.ByteSize() != target_size:
        raise AssertionError("message does not match its target size")
    return result


def _signal_provider(unit_name: str, signal_name: str) -> None:
    subprocess.run(  # noqa: S603 - fixed executable and argument vector
        ["/usr/bin/systemctl", "kill", "--signal", signal_name, unit_name],
        check=True,
    )


def _restart_provider(unit_name: str) -> None:
    subprocess.run(  # noqa: S603 - fixed executable and argument vector
        ["/usr/bin/systemctl", "restart", unit_name],
        check=True,
    )


async def _wait_until_state(
    manager: ProviderSessionManager,
    provider_instance_id: UUID,
    state: ProviderAvailabilityState,
) -> None:
    async with asyncio.timeout(20):
        while True:
            status = manager.availability_status(provider_instance_id)
            if status is not None and status.state is state:
                return
            await asyncio.sleep(0.05)


async def _wait_for_new_descriptor(
    path: Path,
    *,
    previous_generation: int,
) -> ProviderEndpointDescriptor:
    async with asyncio.timeout(20):
        while True:
            try:
                descriptor = load_provider_descriptor(
                    path,
                    discovery_directory=_DISCOVERY_DIRECTORY,
                )
            except (FileNotFoundError, ProviderDescriptorError):
                await asyncio.sleep(0.05)
                continue
            if descriptor.endpoint_generation > previous_generation:
                return descriptor
            await asyncio.sleep(0.05)


def _support_states(
    assessment: CapabilityAssessment,
) -> tuple[CapabilitySupportState, ...]:
    return tuple(finding.support_state for finding in assessment.findings)


class _UnavailableOnceRequester:
    """Inject one retryable Agent-side boundary failure, then call Provider."""

    def __init__(self) -> None:
        self._client = CapabilityAssessmentClient()
        self.request_payloads: list[bytes] = []

    async def assess(
        self,
        channel: grpc.aio.Channel,
        request: capability_assessment_pb2.AssessCapabilitiesRequest,
        *,
        scope: CapabilityAssessmentScope,
    ) -> CapabilityAssessment:
        payload = request.SerializeToString(deterministic=True)
        self.request_payloads.append(payload)
        if len(self.request_payloads) == 1:
            raise SfpCapabilityAssessmentUnavailableError(
                "Injected transient boundary failure"
            )
        return await self._client.assess(channel, request, scope=scope)


def _manager(
    requester: _UnavailableOnceRequester,
) -> ProviderSessionManager:
    return ProviderSessionManager(
        agent_runtime_id=uuid4(),
        agent_software_version=version("stateforge-agent"),
        supported_sfp_versions=(SfpVersion(major=1, minor=0),),
        capability_assessment_attempts=2,
        capability_assessment_retry_initial_delay_seconds=0.01,
        capability_assessment_client=requester,
    )


async def _reject_invalid_locally(
    manager: ProviderSessionManager,
    provider_instance_id: UUID,
    requester: _UnavailableOnceRequester,
) -> None:
    attempts = len(requester.request_payloads)
    for identifier in ("invalid", "stateforge.test/not-declared@1"):
        try:
            await manager.assess_capabilities(
                provider_instance_id,
                (identifier,),
            )
        except SfpCapabilityAssessmentRequestError:
            pass
        else:
            raise AssertionError(
                "Agent accepted an invalid or undeclared operation"
            )
    if len(requester.request_payloads) != attempts:
        raise AssertionError("A locally rejected request reached Provider I/O")


async def _initial_assessment(
    manager: ProviderSessionManager,
    provider_instance_id: UUID,
    requester: _UnavailableOnceRequester,
    event_log: Path,
) -> CapabilityAssessment:
    before = _events(event_log)
    assessment = await manager.assess_capabilities(
        provider_instance_id,
        _OPERATIONS,
        execution_context={"scenario": "provider-r17"},
    )
    if len(requester.request_payloads) != _EXPECTED_RETRY_ATTEMPTS or (
        requester.request_payloads[0] != requester.request_payloads[1]
    ):
        raise AssertionError("Agent retry changed the assessment request")
    if _support_states(assessment) != _EXPECTED_STATES:
        raise AssertionError("Provider returned unexpected support states")
    if assessment.findings[1].requirements[1].state is not (
        CapabilityRequirementState.UNSATISFIED
    ):
        raise AssertionError("Unmet requirement evidence was not preserved")
    if assessment.findings[3].requirements[0].state is not (
        CapabilityRequirementState.UNKNOWN
    ):
        raise AssertionError("Unknown requirement evidence was not preserved")

    evaluated = _events(event_log)[len(before) :]
    expected_checks = (
        "requirement:runtime.target.readable",
        "requirement:runtime.pending",
        "requirement:runtime.incompatible",
        "requirement:runtime.unknown",
    )
    if any(evaluated.count(check) != 1 for check in expected_checks):
        raise AssertionError("Provider did not evaluate each requirement once")

    cached = await manager.cached_capability_assessment(
        provider_instance_id,
        _OPERATIONS,
        execution_context={"scenario": "provider-r17"},
    )
    changed = await manager.cached_capability_assessment(
        provider_instance_id,
        _OPERATIONS,
        execution_context={"scenario": "different-context"},
    )
    if cached is not assessment or changed is not None:
        raise AssertionError("Assessment cache escaped its exact scope")
    return assessment


def _context(value: dict[str, object]) -> struct_pb2.Struct:
    result = struct_pb2.Struct()
    ParseDict(value, result)
    return result


def _request(
    session: ProviderSession,
    *,
    execution_context: struct_pb2.Struct,
) -> capability_assessment_pb2.AssessCapabilitiesRequest:
    return capability_assessment_pb2.AssessCapabilitiesRequest(
        assessment_request_id=str(uuid4()),
        expected_provider_instance_id=str(session.provider_instance_id),
        expected_endpoint_generation=session.endpoint_generation,
        expected_session_id=session.session_id,
        expected_manifest_revision=session.manifest.key.revision,
        execution_context=execution_context,
        operation_identifiers=_OPERATIONS,
    )


def _scope(
    session: ProviderSession,
    *,
    execution_context: struct_pb2.Struct,
) -> CapabilityAssessmentScope:
    return CapabilityAssessmentScope(
        provider_instance_id=session.provider_instance_id,
        endpoint_generation=session.endpoint_generation,
        session_id=session.session_id,
        manifest_revision=session.manifest.key.revision,
        availability_generation=0,
        operation_identifiers=_OPERATIONS,
        execution_context_sha256=hashlib.sha256(
            execution_context.SerializeToString(deterministic=True)
        ).digest(),
    )


async def _reject_stale_fences(session: ProviderSession) -> list[str]:
    client = CapabilityAssessmentClient()
    context = _context({"scenario": "stale-fences"})
    cases: tuple[tuple[str, object], ...] = (
        ("expected_provider_instance_id", str(uuid4())),
        ("expected_endpoint_generation", session.endpoint_generation + 1),
        ("expected_session_id", str(uuid4())),
        ("expected_manifest_revision", "sha256:" + ("f" * 64)),
    )
    rejected: list[str] = []
    for field, value in cases:
        request = _request(session, execution_context=context)
        setattr(request, field, value)
        try:
            await client.assess(
                session._channel,
                request,
                scope=_scope(session, execution_context=context),
            )
        except SfpCapabilityAssessmentStaleError:
            rejected.append(field)
        else:
            raise AssertionError(f"Provider accepted stale fence: {field}")
    return rejected


async def _environment_change(
    manager: ProviderSessionManager,
    provider_instance_id: UUID,
    target: Path,
    original_mode: int,
) -> CapabilityAssessment:
    os.chmod(target, 0)
    restricted = await manager.assess_capabilities(
        provider_instance_id,
        _OPERATIONS,
        execution_context={"scenario": "restricted-target"},
    )
    status = manager.availability_status(provider_instance_id)
    if status is None or not status.eligible:
        raise AssertionError(
            "Operation evidence incorrectly changed Provider availability"
        )
    first = restricted.findings[0]
    if first.support_state is not (
        CapabilitySupportState.SUPPORTED_WITH_REQUIREMENTS
    ) or first.requirements[0].state is not (
        CapabilityRequirementState.UNSATISFIED
    ):
        raise AssertionError("Environment change did not refresh evidence")
    os.chmod(target, original_mode)
    return restricted


async def _cancel_assessment(
    manager: ProviderSessionManager,
    provider_instance_id: UUID,
    event_log: Path,
) -> CapabilityAssessment:
    """Cancel active Provider work and prove the session remains usable."""
    context = {"scenario": "cancelled-assessment"}
    assessment = asyncio.create_task(
        manager.assess_capabilities(
            provider_instance_id,
            (_CANCELLABLE_OPERATION,),
            execution_context=context,
        )
    )
    await _wait_for_event(
        event_log,
        "requirement:runtime.cancellable.started",
    )
    assessment.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await assessment
    if not assessment.cancelled():
        raise AssertionError("Agent cancellation did not cancel assessment")
    await _wait_for_event(
        event_log,
        "requirement:runtime.cancellable.cancelled",
    )
    if "requirement:runtime.cancellable.completed" in _events(event_log):
        raise AssertionError("Cancelled Provider check completed")
    cached = await manager.cached_capability_assessment(
        provider_instance_id,
        (_CANCELLABLE_OPERATION,),
        execution_context=context,
    )
    if cached is not None:
        raise AssertionError("Cancelled assessment entered the Agent cache")

    recovered = await manager.assess_capabilities(
        provider_instance_id,
        _OPERATIONS,
        execution_context={"scenario": "after-cancellation"},
    )
    if _support_states(recovered) != _EXPECTED_STATES:
        raise AssertionError("Provider did not recover after cancellation")
    status = manager.availability_status(provider_instance_id)
    if status is None or not status.eligible:
        raise AssertionError("Cancellation changed Provider availability")
    return recovered


async def _request_limits(
    session: ProviderSession,
    event_log: Path,
) -> None:
    """Exercise exact and oversized requests against the real Provider."""
    context = _context({"scenario": "request-limits"})
    request = _request(session, execution_context=context)
    channel = grpc.aio.insecure_channel(
        f"unix:{session.socket_path}",
        options=(
            (
                "grpc.max_send_message_length",
                contract.MAX_REQUEST_BYTES + 1,
            ),
            (
                "grpc.max_receive_message_length",
                contract.MAX_RESPONSE_BYTES,
            ),
        ),
    )
    stub = capability_assessment_pb2_grpc.CapabilityAssessmentServiceStub(
        channel
    )
    try:
        await channel.channel_ready()
        exact = _message_with_serialized_size(
            request,
            contract.MAX_REQUEST_BYTES,
        )
        response = await stub.AssessCapabilities(exact, timeout=10)
        if response.assessment_request_id != request.assessment_request_id:
            raise AssertionError("Exact-limit response lost correlation")

        before = _events(event_log)
        oversized = _message_with_serialized_size(
            request,
            contract.MAX_REQUEST_BYTES + 1,
        )
        try:
            await stub.AssessCapabilities(oversized, timeout=10)
        except grpc.aio.AioRpcError as error:
            if error.code() is not grpc.StatusCode.RESOURCE_EXHAUSTED:
                raise AssertionError(
                    "Oversized request returned the wrong status"
                ) from error
        else:
            raise AssertionError("Provider accepted an oversized request")
        if _events(event_log) != before:
            raise AssertionError("Oversized request invoked author checks")
    finally:
        await channel.close()


async def _response_limit(
    manager: ProviderSessionManager,
    provider_instance_id: UUID,
) -> CapabilityAssessment:
    """Force a valid Provider response beyond the canonical byte limit."""
    context = {"scenario": "response-limit"}
    try:
        await manager.assess_capabilities(
            provider_instance_id,
            _BOUNDARY_OPERATIONS,
            execution_context=context,
        )
    except SfpCapabilityAssessmentLimitError:
        pass
    else:
        raise AssertionError("Provider emitted an oversized response")
    cached = await manager.cached_capability_assessment(
        provider_instance_id,
        _BOUNDARY_OPERATIONS,
        execution_context=context,
    )
    if cached is not None:
        raise AssertionError("Oversized response entered the Agent cache")

    recovered = await manager.assess_capabilities(
        provider_instance_id,
        _OPERATIONS,
        execution_context={"scenario": "after-message-limits"},
    )
    if _support_states(recovered) != _EXPECTED_STATES:
        raise AssertionError("Provider did not recover after limit rejection")
    return recovered


async def _availability_cycle(
    manager: ProviderSessionManager,
    provider_instance_id: UUID,
    unit_name: str,
    initial: CapabilityAssessment,
) -> CapabilityAssessment:
    _signal_provider(unit_name, "SIGUSR1")
    await _wait_until_state(
        manager,
        provider_instance_id,
        ProviderAvailabilityState.NOT_SERVING,
    )
    try:
        await manager.assess_capabilities(
            provider_instance_id,
            _OPERATIONS,
            execution_context={"scenario": "not-serving"},
        )
    except SfpCapabilityAssessmentUnavailableError:
        pass
    else:
        raise AssertionError("Assessment ran while Provider was unavailable")

    _signal_provider(unit_name, "SIGUSR2")
    await _wait_until_state(
        manager,
        provider_instance_id,
        ProviderAvailabilityState.AVAILABLE,
    )
    cached = await manager.cached_capability_assessment(
        provider_instance_id,
        _OPERATIONS,
        execution_context={"scenario": "provider-r17"},
    )
    if cached is not None:
        raise AssertionError("Availability transition retained stale evidence")
    recovered = await manager.assess_capabilities(
        provider_instance_id,
        _OPERATIONS,
        execution_context={"scenario": "health-recovered"},
    )
    if _support_states(recovered) != _EXPECTED_STATES:
        raise AssertionError("Provider did not recover assessment behavior")
    if recovered.assessment_id == initial.assessment_id:
        raise AssertionError("Recovery reused an earlier assessment")
    return recovered


async def _malformed_response_is_rejected(session: ProviderSession) -> None:
    temporary_directory = Path(await asyncio.to_thread(tempfile.mkdtemp))
    socket = temporary_directory / "peer.sock"

    async def malformed(
        request: capability_assessment_pb2.AssessCapabilitiesRequest,
        context: grpc.aio.ServicerContext[
            capability_assessment_pb2.AssessCapabilitiesRequest,
            bytes,
        ],
    ) -> bytes:
        del request, context
        return b"\x80"

    method = grpc.unary_unary_rpc_method_handler(
        malformed,
        request_deserializer=(
            capability_assessment_pb2.AssessCapabilitiesRequest.FromString
        ),
        response_serializer=lambda value: value,
    )
    server = grpc.aio.server()
    server.add_generic_rpc_handlers(
        (
            grpc.method_handlers_generic_handler(
                "stateforge.sfp.capability_assessment.v1."
                "CapabilityAssessmentService",
                {"AssessCapabilities": method},
            ),
        )
    )
    server.add_insecure_port(f"unix:{socket}")
    await server.start()
    channel = create_provider_channel(f"unix:{socket}")
    try:
        await channel.channel_ready()
        context = _context({"scenario": "malformed-response"})
        try:
            await CapabilityAssessmentClient().assess(
                channel,
                _request(session, execution_context=context),
                scope=_scope(session, execution_context=context),
            )
        except SfpCapabilityAssessmentMalformedResponseError:
            pass
        else:
            raise AssertionError("Agent accepted a malformed response")
    finally:
        await channel.close()
        await server.stop(grace=None)
        await asyncio.to_thread(shutil.rmtree, temporary_directory, True)


async def _restart_and_reassess(
    manager: ProviderSessionManager,
    provider_instance_id: UUID,
    descriptor_path: Path,
    unit_name: str,
    previous_session: ProviderSession,
) -> CapabilityAssessment:
    _restart_provider(unit_name)
    descriptor = await _wait_for_new_descriptor(
        descriptor_path,
        previous_generation=previous_session.endpoint_generation,
    )
    session = await manager.establish(descriptor)
    await _wait_until_state(
        manager,
        provider_instance_id,
        ProviderAvailabilityState.AVAILABLE,
    )
    if session.provider_instance_id != provider_instance_id:
        raise AssertionError("Provider installation identity changed")
    if session.endpoint_generation <= previous_session.endpoint_generation:
        raise AssertionError("Provider restart did not advance generation")
    if session.session_id == previous_session.session_id:
        raise AssertionError("Provider restart reused an SFP session")

    cached = await manager.cached_capability_assessment(
        provider_instance_id,
        _OPERATIONS,
        execution_context={"scenario": "provider-r17"},
    )
    if cached is not None:
        raise AssertionError("Replacement session retained stale evidence")
    fresh = await manager.assess_capabilities(
        provider_instance_id,
        _OPERATIONS,
        execution_context={"scenario": "after-restart"},
    )
    if _support_states(fresh) != _EXPECTED_STATES:
        raise AssertionError("Restarted Provider returned unexpected evidence")
    return fresh


async def _run(arguments: argparse.Namespace) -> dict[str, object]:
    provider_instance_id: UUID = arguments.provider_instance_id
    descriptor = load_provider_descriptor(
        arguments.descriptor_path,
        discovery_directory=_DISCOVERY_DIRECTORY,
    )
    target: Path = arguments.target_path
    event_log: Path = arguments.event_log
    before = _digest(target)
    target_status = await asyncio.to_thread(target.stat)
    original_mode = stat.S_IMODE(target_status.st_mode)
    requester = _UnavailableOnceRequester()
    manager = _manager(requester)
    try:
        session = await manager.establish(descriptor)
        await _wait_until_state(
            manager,
            provider_instance_id,
            ProviderAvailabilityState.AVAILABLE,
        )
        await _reject_invalid_locally(
            manager,
            provider_instance_id,
            requester,
        )
        initial = await _initial_assessment(
            manager,
            provider_instance_id,
            requester,
            event_log,
        )
        stale_fences = await _reject_stale_fences(session)
        restricted = await _environment_change(
            manager,
            provider_instance_id,
            target,
            original_mode,
        )
        recovered = await _availability_cycle(
            manager,
            provider_instance_id,
            arguments.unit_name,
            initial,
        )
        cancelled = await _cancel_assessment(
            manager,
            provider_instance_id,
            event_log,
        )
        await _request_limits(session, event_log)
        limit_recovered = await _response_limit(
            manager,
            provider_instance_id,
        )
        await _malformed_response_is_rejected(session)
        restarted = await _restart_and_reassess(
            manager,
            provider_instance_id,
            arguments.descriptor_path,
            arguments.unit_name,
            session,
        )
        final_status = manager.availability_status(provider_instance_id)
        if final_status is None:
            raise AssertionError("Provider has no final availability state")
    finally:
        os.chmod(target, original_mode)
        with contextlib.suppress(subprocess.CalledProcessError):
            _signal_provider(arguments.unit_name, "SIGUSR2")
        await manager.close()

    after = _digest(target)
    if before != after:
        raise AssertionError("Capability Assessment mutated its target")
    events = _events(event_log)
    if any(event.startswith("operation:") for event in events):
        raise AssertionError("Capability Assessment dispatched an operation")

    final_session = restarted.scope
    return {
        "artifacts": {
            "agent": version("stateforge-agent"),
            "protocol": version("stateforge-protocol"),
            "provider": version("stateforge-provider"),
        },
        "initial": {
            "assessment_id": str(initial.assessment_id),
            "assessment_request_id": str(initial.request_id),
            "endpoint_generation": initial.scope.endpoint_generation,
            "findings": [
                {
                    "operation_identifier": finding.operation_identifier,
                    "requirement_states": [
                        requirement.state.value
                        for requirement in finding.requirements
                    ],
                    "support_state": finding.support_state.value,
                }
                for finding in initial.findings
            ],
            "manifest_revision": initial.scope.manifest_revision,
            "session_id": initial.scope.session_id,
        },
        "malformed_response_rejected": True,
        "cancellation": {
            "assessment_id_after_recovery": str(cancelled.assessment_id),
            "author_check_cancelled": True,
            "partial_evidence_cached": False,
            "provider_remained_available": True,
        },
        "provider_instance_id": str(provider_instance_id),
        "final_state": {
            "availability": final_status.state.value,
            "eligible": final_status.eligible,
        },
        "read_only": {
            "operation_dispatches": 0,
            "target_sha256": after,
        },
        "message_limits": {
            "exact_request_accepted": True,
            "max_request_bytes": contract.MAX_REQUEST_BYTES,
            "max_response_bytes": contract.MAX_RESPONSE_BYTES,
            "oversized_request_rejected_before_author_code": True,
            "oversized_response_rejected": True,
            "post_rejection_assessment_id": str(limit_recovered.assessment_id),
        },
        "readiness_recovery": {
            "assessment_id": str(recovered.assessment_id),
            "states": ["available", "not_serving", "available"],
        },
        "restart_recovery": {
            "assessment_id": str(restarted.assessment_id),
            "endpoint_generation": final_session.endpoint_generation,
            "session_id": final_session.session_id,
        },
        "restricted_environment": {
            "requirement_state": (
                restricted.findings[0].requirements[0].state.value
            ),
            "support_state": restricted.findings[0].support_state.value,
        },
        "retry": {
            "attempts": _EXPECTED_RETRY_ATTEMPTS,
            "request_preserved": True,
            "request_sha256": hashlib.sha256(
                requester.request_payloads[0]
            ).hexdigest(),
        },
        "stale_fences_rejected": stale_fences,
    }


def main() -> None:
    """Run the installed-package assertion and emit bounded JSON evidence."""
    sys.stdout.write(
        json.dumps(asyncio.run(_run(_arguments())), indent=2, sort_keys=True)
        + "\n"
    )


if __name__ == "__main__":
    main()
