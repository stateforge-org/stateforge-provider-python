"""Real-socket evidence for private Provider Capability Assessment."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from collections import Counter
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import grpc
import pytest
from google.protobuf.message import Message
from google.protobuf.struct_pb2 import Struct
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)
from stateforge_protocol.sfp.capability_assessment.v1 import (
    capability_assessment_pb2,
    capability_assessment_pb2_grpc,
)
from stateforge_protocol.sfp.capability_assessment.v1 import (
    contract as capability_contract,
)
from stateforge_protocol.sfp.capability_assessment.v1 import (
    validation as capability_validation,
)
from stateforge_protocol.sfp.manifest.v1 import (
    manifest_pb2,
    manifest_pb2_grpc,
)

from stateforge_provider import (
    HealthStatus,
    Platform,
    Provider,
    ProviderModel,
    RequirementCheckResult,
    operation,
    requirement_check,
)
from stateforge_provider._services.capability_assessment.service import (
    CapabilityAssessmentService,
)

_MAX_SINGLE_BYTE_VARINT = 0x7F
_VARINT_CONTINUATION_BIT = 0x80


class _Input(ProviderModel):
    value: str


class _Output(ProviderModel):
    accepted: bool


class _CapabilityProvider(Provider):
    identity = "example.capability"
    display_name = "Capability test Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(self, directory: Path) -> None:
        super().__init__(
            discovery_directory=directory,
            state_directory=directory / "state",
        )
        self.status = HealthStatus.healthy()
        self.checks: Counter[str] = Counter()
        self.operation_calls = 0
        self.invalid_result = False
        self.raise_check = False
        self.slow_started = asyncio.Event()
        self.slow_release = asyncio.Event()
        self.slow_cancelled = asyncio.Event()

    async def health(self) -> HealthStatus:
        return self.status

    @requirement_check("runtime.satisfied", "Satisfied prerequisite")
    async def satisfied(self) -> RequirementCheckResult:
        self.checks["satisfied"] += 1
        return RequirementCheckResult.satisfied()

    @requirement_check("runtime.unsatisfied", "Unmet prerequisite")
    async def unsatisfied(self) -> RequirementCheckResult:
        self.checks["unsatisfied"] += 1
        return RequirementCheckResult.unsatisfied()

    @requirement_check("runtime.incompatible", "Incompatible runtime")
    async def incompatible(self) -> RequirementCheckResult:
        self.checks["incompatible"] += 1
        return RequirementCheckResult.incompatible("Runtime is incompatible")

    @requirement_check("runtime.unknown", "Unobservable prerequisite")
    async def unknown(self) -> RequirementCheckResult:
        self.checks["unknown"] += 1
        return RequirementCheckResult.unknown("Evidence is unavailable")

    @requirement_check("runtime.invalid_result", "Typed result required")
    async def invalid(self) -> RequirementCheckResult:
        self.checks["invalid"] += 1
        if self.invalid_result:
            return object()  # type: ignore[return-value]
        return RequirementCheckResult.satisfied()

    @requirement_check("runtime.failure", "Failure remains local")
    async def failure(self) -> RequirementCheckResult:
        self.checks["failure"] += 1
        if self.raise_check:
            raise RuntimeError("sensitive author failure")
        return RequirementCheckResult.satisfied()

    @requirement_check("runtime.slow", "Slow prerequisite")
    async def slow(self) -> RequirementCheckResult:
        self.checks["slow"] += 1
        self.slow_started.set()
        try:
            await self.slow_release.wait()
        except asyncio.CancelledError:
            self.slow_cancelled.set()
            raise
        return RequirementCheckResult.satisfied()

    async def _operation(self, request: _Input) -> _Output:
        self.operation_calls += 1
        return _Output(accepted=bool(request.value))

    @operation(
        "example.capability/supported@1",
        requires=("runtime.satisfied",),
    )
    async def supported(self, request: _Input) -> _Output:
        return await self._operation(request)

    @operation(
        "example.capability/unmet@1",
        requires=("runtime.satisfied", "runtime.unsatisfied"),
    )
    async def unmet(self, request: _Input) -> _Output:
        return await self._operation(request)

    @operation(
        "example.capability/unsupported@1",
        requires=("runtime.unknown", "runtime.incompatible"),
    )
    async def unsupported(self, request: _Input) -> _Output:
        return await self._operation(request)

    @operation(
        "example.capability/indeterminate@1",
        requires=("runtime.unknown",),
    )
    async def indeterminate(self, request: _Input) -> _Output:
        return await self._operation(request)

    @operation("example.capability/empty@1")
    async def empty(self, request: _Input) -> _Output:
        return await self._operation(request)

    @operation(
        "example.capability/invalid@1",
        requires=("runtime.invalid_result",),
    )
    async def invalid_operation(self, request: _Input) -> _Output:
        return await self._operation(request)

    @operation(
        "example.capability/failure@1",
        requires=("runtime.failure",),
    )
    async def failure_operation(self, request: _Input) -> _Output:
        return await self._operation(request)

    @operation(
        "example.capability/slow@1",
        requires=("runtime.slow",),
    )
    async def slow_operation(self, request: _Input) -> _Output:
        return await self._operation(request)


@pytest.fixture
def endpoint_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="sfp-r3-", dir="/tmp"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@asynccontextmanager
async def _running(
    provider: _CapabilityProvider,
) -> AsyncIterator[
    tuple[
        capability_assessment_pb2_grpc.CapabilityAssessmentServiceStub,
        bootstrap_pb2_grpc.BootstrapServiceStub,
        manifest_pb2_grpc.ManifestServiceStub,
        dict[str, object],
    ]
]:
    task = asyncio.create_task(provider.serve())
    channel: grpc.aio.Channel | None = None
    try:
        async with asyncio.timeout(3):
            while not list(
                provider._configuration.discovery_directory.glob("*.sfp.json")
            ):
                if task.done():
                    await task
                await asyncio.sleep(0.001)
        descriptor = json.loads(provider._server.descriptor_path.read_text())
        channel = grpc.aio.insecure_channel(
            f"unix:{descriptor['transport']['socket_path']}",
            options=(
                (
                    "grpc.max_receive_message_length",
                    capability_contract.MAX_RESPONSE_BYTES,
                ),
                (
                    "grpc.max_send_message_length",
                    capability_contract.MAX_REQUEST_BYTES + 1,
                ),
            ),
        )
        await asyncio.wait_for(channel.channel_ready(), timeout=2)
        yield (
            capability_assessment_pb2_grpc.CapabilityAssessmentServiceStub(
                channel
            ),
            bootstrap_pb2_grpc.BootstrapServiceStub(channel),
            manifest_pb2_grpc.ManifestServiceStub(channel),
            descriptor,
        )
    finally:
        provider.request_shutdown()
        await asyncio.wait_for(task, timeout=3)
        if channel is not None:
            await channel.close()


async def _session(
    bootstrap: bootstrap_pb2_grpc.BootstrapServiceStub,
    manifest: manifest_pb2_grpc.ManifestServiceStub,
    descriptor: dict[str, object],
):
    handshake = await bootstrap.Handshake(
        bootstrap_pb2.HandshakeRequest(
            agent_runtime=bootstrap_pb2.AgentRuntime(
                runtime_id=str(uuid4()),
                software_version="1.0.0",
            ),
            expected_provider_instance_id=descriptor["provider_instance_id"],
            expected_endpoint_generation=descriptor["endpoint_generation"],
            supported_sfp_versions=[
                bootstrap_pb2.ProtocolVersion(major=1, minor=0)
            ],
        ),
        timeout=2,
    )
    snapshot = await manifest.GetManifest(
        manifest_pb2.GetManifestRequest(
            expected_provider_instance_id=handshake.provider_instance_id,
            expected_endpoint_generation=handshake.endpoint_generation,
            expected_session_id=handshake.session_id,
            supported_manifest_schema_versions=[1],
        ),
        timeout=2,
    )
    return handshake, snapshot


def _request(handshake, snapshot, operations, **overrides):
    return capability_assessment_pb2.AssessCapabilitiesRequest(
        **{
            "assessment_request_id": str(uuid4()),
            "expected_provider_instance_id": handshake.provider_instance_id,
            "expected_endpoint_generation": handshake.endpoint_generation,
            "expected_session_id": handshake.session_id,
            "expected_manifest_revision": snapshot.manifest_revision,
            "execution_context": Struct(),
            "operation_identifiers": operations,
            **overrides,
        }
    )


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
    """Pad a message with one ignored field to an exact wire size."""
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


@pytest.mark.asyncio
async def test_assesses_over_real_socket_with_deduplication_and_precedence(
    endpoint_directory: Path,
) -> None:
    provider = _CapabilityProvider(endpoint_directory)
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        operations = [
            "example.capability/indeterminate@1",
            "example.capability/supported@1",
            "example.capability/unmet@1",
            "example.capability/unsupported@1",
            "example.capability/empty@1",
        ]
        request = _request(handshake, snapshot, operations)
        response = await capability.AssessCapabilities(request, timeout=2)

    capability_validation.validate_assessment_exchange(request, response)
    assert [
        item.operation_identifier for item in response.findings
    ] == operations
    assert [item.support_state for item in response.findings] == [
        capability_assessment_pb2.SUPPORT_STATE_INDETERMINATE,
        capability_assessment_pb2.SUPPORT_STATE_SUPPORTED,
        capability_assessment_pb2.SUPPORT_STATE_SUPPORTED_WITH_REQUIREMENTS,
        capability_assessment_pb2.SUPPORT_STATE_UNSUPPORTED,
        capability_assessment_pb2.SUPPORT_STATE_SUPPORTED,
    ]
    assert provider.checks == {
        "satisfied": 1,
        "unsatisfied": 1,
        "incompatible": 1,
        "unknown": 1,
    }
    assert provider.operation_calls == 0
    unsupported = response.findings[3]
    assert unsupported.reasons[0].reason_code.endswith(
        "unsupported_vendor_state"
    )
    assert [
        item.requirement_id for item in unsupported.requirement_findings
    ] == [
        "runtime.unknown",
        "runtime.incompatible",
    ]


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("malformed", grpc.StatusCode.INVALID_ARGUMENT),
        ("session", grpc.StatusCode.FAILED_PRECONDITION),
        ("instance", grpc.StatusCode.FAILED_PRECONDITION),
        ("generation", grpc.StatusCode.FAILED_PRECONDITION),
        ("manifest", grpc.StatusCode.FAILED_PRECONDITION),
        ("operation", grpc.StatusCode.FAILED_PRECONDITION),
    ],
)
@pytest.mark.asyncio
async def test_maps_validation_and_contextual_fence_failures(
    endpoint_directory: Path,
    change: str,
    code: grpc.StatusCode,
) -> None:
    provider = _CapabilityProvider(endpoint_directory)
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        request = _request(
            handshake,
            snapshot,
            ["example.capability/supported@1"],
        )
        if change == "malformed":
            request.assessment_request_id = "not-a-uuid"
        elif change == "session":
            request.expected_session_id = "not-negotiated"
        elif change == "instance":
            request.expected_provider_instance_id = str(uuid4())
        elif change == "generation":
            request.expected_endpoint_generation += 1
        elif change == "manifest":
            request.expected_manifest_revision = "sha256:" + ("0" * 64)
        else:
            request.operation_identifiers[0] = "example.capability/missing@1"

        with pytest.raises(grpc.aio.AioRpcError) as error:
            await capability.AssessCapabilities(request, timeout=2)
        assert error.value.code() is code
        assert provider.checks == {}
        assert provider.operation_calls == 0


@pytest.mark.asyncio
async def test_rejects_not_ready_provider_before_running_checks(
    endpoint_directory: Path,
) -> None:
    provider = _CapabilityProvider(endpoint_directory)
    provider.status = HealthStatus.maintenance()
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await capability.AssessCapabilities(
                _request(
                    handshake,
                    snapshot,
                    ["example.capability/supported@1"],
                ),
                timeout=2,
            )
        assert error.value.code() is grpc.StatusCode.UNAVAILABLE
        assert provider.checks == {}


@pytest.mark.parametrize("failure", ["invalid", "exception"])
@pytest.mark.asyncio
async def test_invalid_author_results_are_sanitized_internal(
    endpoint_directory: Path,
    failure: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _CapabilityProvider(endpoint_directory)
    provider.invalid_result = failure == "invalid"
    provider.raise_check = failure == "exception"
    suffix = failure if failure == "invalid" else "failure"
    operation = f"example.capability/{suffix}@1"
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(grpc.aio.AioRpcError) as error,
        ):
            await capability.AssessCapabilities(
                _request(handshake, snapshot, [operation]),
                timeout=2,
            )
        assert error.value.code() is grpc.StatusCode.INTERNAL
        assert "sensitive author failure" not in error.value.details()
        if failure == "exception":
            assert "sensitive author failure" in caplog.text


@pytest.mark.asyncio
async def test_revalidates_readiness_after_checks(
    endpoint_directory: Path,
) -> None:
    provider = _CapabilityProvider(endpoint_directory)
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        call = asyncio.ensure_future(
            capability.AssessCapabilities(
                _request(
                    handshake,
                    snapshot,
                    ["example.capability/slow@1"],
                ),
                timeout=2,
            )
        )
        await asyncio.wait_for(provider.slow_started.wait(), timeout=1)
        provider.status = HealthStatus.maintenance()
        await provider.refresh_health()
        provider.slow_release.set()
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await call
        assert error.value.code() is grpc.StatusCode.UNAVAILABLE


@pytest.mark.asyncio
async def test_revalidates_session_after_checks(
    endpoint_directory: Path,
) -> None:
    provider = _CapabilityProvider(endpoint_directory)
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        call = asyncio.ensure_future(
            capability.AssessCapabilities(
                _request(
                    handshake,
                    snapshot,
                    ["example.capability/slow@1"],
                ),
                timeout=2,
            )
        )
        await asyncio.wait_for(provider.slow_started.wait(), timeout=1)
        sessions = provider._server._sessions
        assert sessions is not None
        sessions.clear()
        provider.slow_release.set()
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await call
        assert error.value.code() is grpc.StatusCode.FAILED_PRECONDITION


@pytest.mark.asyncio
async def test_rpc_deadline_cancels_in_flight_requirement_checks(
    endpoint_directory: Path,
) -> None:
    provider = _CapabilityProvider(endpoint_directory)
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await capability.AssessCapabilities(
                _request(
                    handshake,
                    snapshot,
                    ["example.capability/slow@1"],
                ),
                timeout=0.05,
            )
        assert error.value.code() is grpc.StatusCode.DEADLINE_EXCEEDED
        await asyncio.wait_for(provider.slow_cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_client_cancellation_stops_in_flight_requirement_checks(
    endpoint_directory: Path,
) -> None:
    provider = _CapabilityProvider(endpoint_directory)
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        call = capability.AssessCapabilities(
            _request(
                handshake,
                snapshot,
                ["example.capability/slow@1"],
            ),
            timeout=2,
        )
        await asyncio.wait_for(provider.slow_started.wait(), timeout=1)
        assert call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        await asyncio.wait_for(provider.slow_cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_enforces_exact_and_oversized_request_boundaries(
    endpoint_directory: Path,
) -> None:
    provider = _CapabilityProvider(endpoint_directory)
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        base = _request(
            handshake,
            snapshot,
            ["example.capability/supported@1"],
        )
        exact = _message_with_serialized_size(
            base,
            capability_contract.MAX_REQUEST_BYTES,
        )
        response = await capability.AssessCapabilities(exact, timeout=3)
        assert response.findings[0].operation_identifier == (
            "example.capability/supported@1"
        )

        oversized = _message_with_serialized_size(
            base,
            capability_contract.MAX_REQUEST_BYTES + 1,
        )
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await capability.AssessCapabilities(oversized, timeout=3)
        assert error.value.code() is grpc.StatusCode.RESOURCE_EXHAUSTED


@pytest.mark.parametrize(
    ("response_size", "expected_code"),
    [
        (capability_contract.MAX_RESPONSE_BYTES, None),
        (
            capability_contract.MAX_RESPONSE_BYTES + 1,
            grpc.StatusCode.RESOURCE_EXHAUSTED,
        ),
    ],
)
@pytest.mark.asyncio
async def test_enforces_response_boundaries(
    endpoint_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
    response_size: int,
    expected_code: grpc.StatusCode | None,
) -> None:
    original_response = CapabilityAssessmentService._response

    def padded_response(self, request, results):
        response = original_response(self, request, results)
        return _message_with_serialized_size(response, response_size)

    monkeypatch.setattr(
        CapabilityAssessmentService,
        "_response",
        padded_response,
    )
    provider = _CapabilityProvider(endpoint_directory)
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        call = capability.AssessCapabilities(
            _request(
                handshake,
                snapshot,
                ["example.capability/supported@1"],
            ),
            timeout=5,
        )
        if expected_code is None:
            response = await call
            assert response.ByteSize() == response_size
        else:
            with pytest.raises(grpc.aio.AioRpcError) as error:
                await call
            assert error.value.code() is expected_code


@pytest.mark.asyncio
async def test_delegates_request_and_response_validation_to_protocol(
    endpoint_directory: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _CapabilityProvider(endpoint_directory)
    async with _running(provider) as (
        capability,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        request = _request(
            handshake,
            snapshot,
            ["example.capability/supported@1"],
        )

        def reject_request(_request) -> None:
            raise capability_validation.CapabilityAssessmentValidationError(
                "canonical request"
            )

        monkeypatch.setattr(
            capability_validation,
            "validate_assess_capabilities_request",
            reject_request,
        )
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await capability.AssessCapabilities(request, timeout=2)
        assert error.value.code() is grpc.StatusCode.INVALID_ARGUMENT

        monkeypatch.undo()

        def reject_response(_request, _response) -> None:
            raise capability_validation.CapabilityAssessmentValidationError(
                "canonical response"
            )

        monkeypatch.setattr(
            capability_validation,
            "validate_assessment_exchange",
            reject_response,
        )
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await capability.AssessCapabilities(request, timeout=2)
        assert error.value.code() is grpc.StatusCode.INTERNAL
