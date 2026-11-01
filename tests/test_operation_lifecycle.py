"""Real-socket evidence for Provider Operation Lifecycle behavior."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import uuid4

import grpc
import pytest
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from grpc_status import rpc_status
from jsonschema import Draft202012Validator
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)
from stateforge_protocol.sfp.manifest.v1 import (
    manifest_pb2,
    manifest_pb2_grpc,
)
from stateforge_protocol.sfp.operation_admission.v1 import (
    contract as admission_contract,
)
from stateforge_protocol.sfp.operation_admission.v1 import (
    operation_admission_pb2,
    operation_admission_pb2_grpc,
)
from stateforge_protocol.sfp.operation_admission.v1 import (
    validation as admission_validation,
)
from stateforge_protocol.sfp.operation_lifecycle.v1 import (
    contract as lifecycle_contract,
)
from stateforge_protocol.sfp.operation_lifecycle.v1 import (
    operation_lifecycle_pb2,
    operation_lifecycle_pb2_grpc,
)
from stateforge_protocol.sfp.operation_lifecycle.v1 import (
    validation as lifecycle_validation,
)

from stateforge_provider import (
    OperationCancelledError,
    OperationCleanup,
    OperationContext,
    OperationEffects,
    OperationFailedError,
    OperationProgressPolicy,
    OperationSideEffects,
    Platform,
    ProgressPercentageMode,
    ProtocolVersion,
    Provider,
    ProviderModel,
    operation,
)
from stateforge_provider._runtime.identity import ProviderEndpointIdentity
from stateforge_provider._runtime.sessions import SessionRegistry
from stateforge_provider._services.manifest.declaration import (
    ManifestDeclaration,
)
from stateforge_provider._services.manifest.errors import ManifestError
from stateforge_provider._services.operation_admission.runtime import (
    AdmissionRegistryError,
    AdmissionRegistryFailure,
    OperationAdmissionRuntime,
)
from stateforge_provider._services.operation_lifecycle.runtime import (
    LifecycleObserverCapacityError,
    OperationLifecycleRecord,
)
from stateforge_provider._services.operation_lifecycle.service import (
    OperationLifecycleService,
)

_COMPLETE_PERCENTAGE = 100.0
_CANCELLING_PERCENTAGE = 50.0
_CANCELLATION_REQUEST_COUNT = 8
_REPEATED_CANCELLATION_COUNT = _CANCELLATION_REQUEST_COUNT - 1
_CURSOR_AHEAD = operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_CURSOR_AHEAD
_FINGERPRINT_MISMATCH = (
    operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_FINGERPRINT_MISMATCH
)
_SESSION_PRECONDITION_FAILED = (
    operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_SESSION_PRECONDITION_FAILED
)
_CANCELLATION_REQUEST_SEQUENCE = 2
_PRE_START_TERMINAL_SEQUENCE = 3
_COALESCED_TERMINAL_SEQUENCE = 5
_ALREADY_REQUESTED = (
    operation_lifecycle_pb2.CANCELLATION_DISPOSITION_ALREADY_REQUESTED
)


class _Input(ProviderModel):
    mode: str


class _Output(ProviderModel):
    value: int


class _LargeOutput(ProviderModel):
    value: str


class _LifecycleProvider(Provider):
    identity = "example.lifecycle"
    display_name = "Lifecycle test Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(self, directory: Path) -> None:
        super().__init__(
            discovery_directory=directory,
            state_directory=directory / "state",
        )
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancellation_seen = asyncio.Event()
        self.cancellation_release = asyncio.Event()
        self.context: OperationContext | None = None

    @operation(
        "example.lifecycle/run@1",
        cancellable=True,
        progress=OperationProgressPolicy.determinate(),
    )
    async def run_operation(
        self,
        request: _Input,
        context: OperationContext,
    ) -> _Output:
        self.calls += 1
        self.context = context
        if request.mode == "invalid-progress":
            await context.report_progress("Half", percentage=50)
            await context.report_progress("Backwards", percentage=40)
        if request.mode == "oversized-progress":
            await context.report_progress(
                "x" * (lifecycle_contract.MAX_EXPLANATION_CODE_POINTS + 1),
                percentage=0,
            )
        if request.mode == "no-100":
            await context.report_progress("Nearly done", percentage=90)
            return _Output(value=90)
        await context.report_progress("Started", percentage=0)
        self.started.set()
        if request.mode in {"cancel", "cancel-success"}:
            await context.wait_for_cancellation()
            self.cancellation_seen.set()
            await context.report_progress("Stopping safely", percentage=50)
            await self.cancellation_release.wait()
            if request.mode == "cancel-success":
                await context.report_progress("Finished", percentage=100)
                return _Output(value=100)
            raise OperationCancelledError(
                OperationEffects(
                    side_effects=OperationSideEffects.PRESENT,
                    cleanup=OperationCleanup.COMPLETED,
                    explanation="Temporary work was removed.",
                )
            )
        if request.mode == "failure":
            raise OperationFailedError(
                code="example.lifecycle.failed",
                explanation="The requested lifecycle test failed.",
                effects=OperationEffects(
                    side_effects=OperationSideEffects.NONE,
                    cleanup=OperationCleanup.NOT_REQUIRED,
                    explanation="No changes were made.",
                ),
            )
        if request.mode == "invalid-result":
            await context.report_progress("Finished", percentage=100)
            return cast(_Output, ProviderModel())
        await self.release.wait()
        await context.report_progress("Finished", percentage=100)
        return _Output(value=100)

    @operation("example.lifecycle/unsupported@1")
    async def unsupported(
        self,
        request: _Input,
        context: OperationContext,
    ) -> _Output:
        self.calls += 1
        self.context = context
        self.started.set()
        await self.release.wait()
        return _Output(value=1)

    @operation("example.lifecycle/flexible@1")
    async def flexible(
        self,
        request: _Input,
        context: OperationContext,
    ) -> _Output:
        del request
        self.calls += 1
        await context.report_progress("Phase one", percentage=100)
        await context.report_progress("Phase two", percentage=0)
        return _Output(value=2)

    @operation(
        "example.lifecycle/indeterminate@1",
        progress=OperationProgressPolicy.indeterminate(),
    )
    async def indeterminate(
        self,
        request: _Input,
        context: OperationContext,
    ) -> _Output:
        del request
        self.calls += 1
        await context.report_progress("Discovering resources")
        return _Output(value=3)

    @operation("example.lifecycle/oversized_result@1")
    async def oversized_result(
        self,
        request: _Input,
        context: OperationContext,
    ) -> _LargeOutput:
        del request, context
        self.calls += 1
        return _LargeOutput(
            value="x" * (lifecycle_contract.MAX_RESULT_STRING_CODE_POINTS + 1)
        )


@pytest.fixture
def endpoint_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="sfp-r6-", dir="/tmp"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@asynccontextmanager
async def _running(
    provider: _LifecycleProvider,
) -> AsyncIterator[tuple[object, ...]]:
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
                    lifecycle_contract.MAX_RESPONSE_BYTES,
                ),
                (
                    "grpc.max_send_message_length",
                    max(
                        lifecycle_contract.MAX_REQUEST_BYTES,
                        admission_contract.MAX_REQUEST_BYTES,
                    ),
                ),
            ),
        )
        await asyncio.wait_for(channel.channel_ready(), timeout=2)
        yield (
            operation_admission_pb2_grpc.OperationAdmissionServiceStub(
                channel
            ),
            operation_lifecycle_pb2_grpc.OperationLifecycleServiceStub(
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


async def _session(bootstrap, manifest, descriptor):
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


def _timestamp(value: datetime) -> Timestamp:
    timestamp = Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _start_request(
    handshake,
    snapshot,
    *,
    mode: str = "success",
    identifier: str = "example.lifecycle/run@1",
):
    payload = Struct()
    ParseDict({"mode": mode}, payload)
    return operation_admission_pb2.StartOperationRequest(
        session_binding=operation_admission_pb2.OperationSessionBinding(
            expected_provider_instance_id=handshake.provider_instance_id,
            expected_endpoint_generation=handshake.endpoint_generation,
            expected_session_id=handshake.session_id,
        ),
        invocation=operation_admission_pb2.OperationInvocation(
            operation_id=str(uuid4()),
            operation_identifier=identifier,
            payload=payload,
            execution_deadline=_timestamp(
                datetime.now(UTC) + timedelta(minutes=5)
            ),
            contract=operation_admission_pb2.OperationContractContext(
                manifest_revision=snapshot.manifest_revision,
            ),
            execution_context=Struct(),
        ),
        admission_mode=(
            operation_admission_pb2.ADMISSION_MODE_ADMIT_OR_RESOLVE
        ),
    )


def _watch_request(start, handshake, *, after_sequence: int = 0):
    return operation_lifecycle_pb2.WatchOperationRequest(
        session_binding=start.session_binding,
        operation_id=start.invocation.operation_id,
        expected_request_fingerprint=(
            admission_validation.compute_request_fingerprint(start.invocation)
        ),
        after_sequence=after_sequence,
    )


def _cancel_request(start):
    return operation_lifecycle_pb2.CancelOperationRequest(
        session_binding=start.session_binding,
        operation_id=start.invocation.operation_id,
        expected_request_fingerprint=(
            admission_validation.compute_request_fingerprint(start.invocation)
        ),
    )


async def _terminal(call, request, *, previous_sequence=None):
    responses = []
    previous = previous_sequence
    while True:
        response = await call.read()
        if response is grpc.aio.EOF:
            break
        lifecycle_validation.validate_watch_exchange(
            request,
            response,
            previous_sequence=previous,
        )
        responses.append(response)
        previous = response.snapshot.sequence
        if response.snapshot.state in {
            operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED,
            operation_lifecycle_pb2.OPERATION_STATE_FAILED,
            operation_lifecycle_pb2.OPERATION_STATE_CANCELLED,
        }:
            assert await call.read() is grpc.aio.EOF
            break
    return responses


def _detail(error: grpc.aio.AioRpcError):
    status = rpc_status.from_call(error)
    assert status is not None
    packed = status.details[0]
    detail = operation_lifecycle_pb2.OperationLifecycleErrorDetail()
    assert packed.Unpack(detail)
    lifecycle_validation.validate_lifecycle_error_detail(detail)
    return detail


@pytest.mark.asyncio
async def test_progress_success_late_replay_and_no_redispatch(
    endpoint_directory: Path,
) -> None:
    provider = _LifecycleProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        lifecycle,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        start = _start_request(handshake, snapshot)
        await admission.StartOperation(start, timeout=2)
        await asyncio.wait_for(provider.started.wait(), timeout=1)

        request = _watch_request(start, handshake)
        call = lifecycle.WatchOperation(request, timeout=2)
        first = await call.read()
        assert first.snapshot.state == (
            operation_lifecycle_pb2.OPERATION_STATE_RUNNING
        )
        assert first.snapshot.progress.percentage == 0

        provider.release.set()
        responses = [
            first,
            *(
                await _terminal(
                    call,
                    request,
                    previous_sequence=first.snapshot.sequence,
                )
            ),
        ]
        terminal = responses[-1].snapshot
        assert terminal.state == (
            operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED
        )
        assert MessageToDict(terminal.success.result) == {"value": 100.0}
        assert terminal.progress.percentage == _COMPLETE_PERCENTAGE

        replay_request = _watch_request(
            start,
            handshake,
            after_sequence=terminal.sequence,
        )
        replay_call = lifecycle.WatchOperation(replay_request, timeout=2)
        replay = await replay_call.read()
        assert replay.snapshot == terminal
        assert await replay_call.read() is grpc.aio.EOF
        assert provider.calls == 1


@pytest.mark.asyncio
async def test_cancellation_dispositions_and_confirmed_terminal(
    endpoint_directory: Path,
) -> None:
    provider = _LifecycleProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        lifecycle,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        start = _start_request(handshake, snapshot, mode="cancel")
        await admission.StartOperation(start, timeout=2)
        await asyncio.wait_for(provider.started.wait(), timeout=1)

        request = _cancel_request(start)
        decisions = await asyncio.gather(
            *(
                lifecycle.CancelOperation(request, timeout=2)
                for _ in range(_CANCELLATION_REQUEST_COUNT)
            )
        )
        assert (
            sum(
                item.disposition
                == operation_lifecycle_pb2.CANCELLATION_DISPOSITION_REQUESTED
                for item in decisions
            )
            == 1
        )
        assert (
            sum(item.disposition == _ALREADY_REQUESTED for item in decisions)
            == _REPEATED_CANCELLATION_COUNT
        )
        requested = next(
            item
            for item in decisions
            if item.disposition
            == operation_lifecycle_pb2.CANCELLATION_DISPOSITION_REQUESTED
        )
        assert requested.disposition == (
            operation_lifecycle_pb2.CANCELLATION_DISPOSITION_REQUESTED
        )
        assert requested.snapshot.state == (
            operation_lifecycle_pb2.OPERATION_STATE_CANCELLATION_REQUESTED
        )
        await asyncio.wait_for(provider.cancellation_seen.wait(), timeout=1)
        repeated = next(
            item
            for item in decisions
            if item.disposition == _ALREADY_REQUESTED
        )
        assert repeated.snapshot.sequence >= requested.snapshot.sequence
        assert repeated.snapshot.state == (
            operation_lifecycle_pb2.OPERATION_STATE_CANCELLATION_REQUESTED
        )

        provider.cancellation_release.set()
        watch = _watch_request(start, handshake)
        terminal = (
            await _terminal(lifecycle.WatchOperation(watch, timeout=2), watch)
        )[-1].snapshot
        assert terminal.state == (
            operation_lifecycle_pb2.OPERATION_STATE_CANCELLED
        )
        assert terminal.cancellation.effects.side_effects == (
            operation_lifecycle_pb2.SIDE_EFFECT_STATE_PRESENT
        )
        assert terminal.progress.percentage == _CANCELLING_PERCENTAGE
        completed = await lifecycle.CancelOperation(request, timeout=2)
        assert completed.disposition == (
            operation_lifecycle_pb2.CANCELLATION_DISPOSITION_ALREADY_TERMINAL
        )


@pytest.mark.asyncio
async def test_success_can_win_after_cancellation_is_requested(
    endpoint_directory: Path,
) -> None:
    provider = _LifecycleProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        lifecycle,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        start = _start_request(handshake, snapshot, mode="cancel-success")
        await admission.StartOperation(start, timeout=2)
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        requested = await lifecycle.CancelOperation(
            _cancel_request(start), timeout=2
        )
        assert requested.disposition == (
            operation_lifecycle_pb2.CANCELLATION_DISPOSITION_REQUESTED
        )
        await asyncio.wait_for(provider.cancellation_seen.wait(), timeout=1)
        provider.cancellation_release.set()
        watch = _watch_request(start, handshake)
        terminal = (
            await _terminal(lifecycle.WatchOperation(watch, timeout=2), watch)
        )[-1].snapshot
        assert terminal.state == (
            operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED
        )


@pytest.mark.asyncio
async def test_unsupported_cancellation_does_not_signal_execution(
    endpoint_directory: Path,
) -> None:
    provider = _LifecycleProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        lifecycle,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        start = _start_request(
            handshake,
            snapshot,
            identifier="example.lifecycle/unsupported@1",
        )
        await admission.StartOperation(start, timeout=2)
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        response = await lifecycle.CancelOperation(
            _cancel_request(start), timeout=2
        )
        assert response.disposition == (
            operation_lifecycle_pb2.CANCELLATION_DISPOSITION_UNSUPPORTED
        )
        assert provider.context is not None
        assert not provider.context.cancellation_requested
        provider.release.set()


@pytest.mark.parametrize(
    ("mode", "code"),
    [
        ("invalid-progress", "stateforge.operation.invalid_progress"),
        ("oversized-progress", "stateforge.operation.invalid_progress"),
        ("no-100", "stateforge.operation.invalid_progress"),
        ("invalid-result", "stateforge.operation.invalid_result"),
        ("failure", "example.lifecycle.failed"),
    ],
)
@pytest.mark.asyncio
async def test_normalizes_terminal_failures(
    endpoint_directory: Path,
    mode: str,
    code: str,
) -> None:
    provider = _LifecycleProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        lifecycle,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        start = _start_request(handshake, snapshot, mode=mode)
        await admission.StartOperation(start, timeout=2)
        request = _watch_request(start, handshake)
        terminal = (
            await _terminal(
                lifecycle.WatchOperation(request, timeout=2), request
            )
        )[-1].snapshot
        assert terminal.state == operation_lifecycle_pb2.OPERATION_STATE_FAILED
        assert terminal.failure.code == code
        assert terminal.failure.explanation


@pytest.mark.parametrize(
    ("identifier", "expected_progress"),
    [
        ("example.lifecycle/flexible@1", 0),
        ("example.lifecycle/indeterminate@1", None),
    ],
)
@pytest.mark.asyncio
async def test_optional_and_indeterminate_progress_policies(
    endpoint_directory: Path,
    identifier: str,
    expected_progress: int | None,
) -> None:
    provider = _LifecycleProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        lifecycle,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        start = _start_request(
            handshake,
            snapshot,
            identifier=identifier,
        )
        await admission.StartOperation(start, timeout=2)
        request = _watch_request(start, handshake)
        terminal = (
            await _terminal(
                lifecycle.WatchOperation(request, timeout=2), request
            )
        )[-1].snapshot
        assert terminal.state == (
            operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED
        )
        if expected_progress is None:
            assert not terminal.progress.HasField("percentage")
        else:
            assert terminal.progress.percentage == expected_progress


@pytest.mark.asyncio
async def test_watch_cancellation_does_not_cancel_business_execution(
    endpoint_directory: Path,
) -> None:
    provider = _LifecycleProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        lifecycle,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        start = _start_request(handshake, snapshot)
        await admission.StartOperation(start, timeout=2)
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        request = _watch_request(start, handshake)
        call = lifecycle.WatchOperation(request)
        await call.read()
        call.cancel()
        await asyncio.sleep(0)
        assert provider.context is not None
        assert not provider.context.cancellation_requested

        provider.release.set()
        reconnect, _ = await _session(bootstrap, manifest, descriptor)
        request.session_binding.expected_session_id = reconnect.session_id
        terminal = (
            await _terminal(
                lifecycle.WatchOperation(request, timeout=2), request
            )
        )[-1].snapshot
        assert terminal.state == (
            operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED
        )
        assert provider.calls == 1


@pytest.mark.parametrize("failure", ["cursor", "fingerprint", "session"])
@pytest.mark.asyncio
async def test_structured_watch_rejections(
    endpoint_directory: Path,
    failure: str,
) -> None:
    provider = _LifecycleProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        lifecycle,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        start = _start_request(handshake, snapshot)
        await admission.StartOperation(start, timeout=2)
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        request = _watch_request(start, handshake)
        if failure == "cursor":
            request.after_sequence = 999
        elif failure == "fingerprint":
            request.expected_request_fingerprint = "sha256:" + ("f" * 64)
        else:
            request.session_binding.expected_session_id = "stale-session"
        call = lifecycle.WatchOperation(request, timeout=2)
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await call.read()
        detail = _detail(captured.value)
        expected = {
            "cursor": _CURSOR_AHEAD,
            "fingerprint": _FINGERPRINT_MISMATCH,
            "session": _SESSION_PRECONDITION_FAILED,
        }[failure]
        assert detail.reason == expected
        provider.release.set()


@pytest.mark.parametrize(
    ("failure", "code", "reason"),
    [
        (
            "invalid",
            grpc.StatusCode.INVALID_ARGUMENT,
            operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_INVALID_REQUEST,
        ),
        (
            "fingerprint",
            grpc.StatusCode.FAILED_PRECONDITION,
            _FINGERPRINT_MISMATCH,
        ),
        (
            "session",
            grpc.StatusCode.FAILED_PRECONDITION,
            _SESSION_PRECONDITION_FAILED,
        ),
        (
            "unavailable",
            grpc.StatusCode.FAILED_PRECONDITION,
            operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_OPERATION_RECORD_UNAVAILABLE,
        ),
    ],
)
@pytest.mark.asyncio
async def test_structured_cancel_rejections(
    endpoint_directory: Path,
    failure: str,
    code: grpc.StatusCode,
    reason: int,
) -> None:
    provider = _LifecycleProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        lifecycle,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        start = _start_request(handshake, snapshot)
        await admission.StartOperation(start, timeout=2)
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        request = _cancel_request(start)
        if failure == "invalid":
            request.operation_id = ""
        elif failure == "fingerprint":
            request.expected_request_fingerprint = "sha256:" + ("f" * 64)
        elif failure == "session":
            request.session_binding.expected_session_id = "stale-session"
        else:
            request.operation_id = str(uuid4())
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await lifecycle.CancelOperation(request, timeout=2)
        assert captured.value.code() is code
        assert _detail(captured.value).reason == reason
        provider.release.set()


@pytest.mark.asyncio
async def test_oversized_watch_request_and_result_are_rejected_safely(
    endpoint_directory: Path,
) -> None:
    provider = _LifecycleProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        lifecycle,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        start = _start_request(
            handshake,
            snapshot,
            identifier="example.lifecycle/oversized_result@1",
        )
        await admission.StartOperation(start, timeout=2)
        watch = _watch_request(start, handshake)
        terminal = (
            await _terminal(lifecycle.WatchOperation(watch, timeout=2), watch)
        )[-1].snapshot
        assert terminal.state == operation_lifecycle_pb2.OPERATION_STATE_FAILED
        assert terminal.failure.code == "stateforge.operation.invalid_result"

        oversized = _watch_request(start, handshake)
        oversized.expected_request_fingerprint = "x" * (
            lifecycle_contract.MAX_REQUEST_BYTES + 1
        )
        call = lifecycle.WatchOperation(oversized, timeout=2)
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await call.read()
        assert captured.value.code() is grpc.StatusCode.INVALID_ARGUMENT
        assert _detail(captured.value).reason == (
            operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_INVALID_REQUEST
        )


def test_progress_policy_presets_and_declaration_require_context() -> None:
    determinate = OperationProgressPolicy.determinate()
    assert determinate.percentage_mode is ProgressPercentageMode.REQUIRED
    assert determinate.monotonic
    assert determinate.require_100_on_success
    indeterminate = OperationProgressPolicy.indeterminate()
    assert indeterminate.percentage_mode is ProgressPercentageMode.FORBIDDEN
    assert indeterminate.require_message

    class _InvalidProvider(_LifecycleProvider):
        @operation(
            "example.lifecycle/invalid@1",
            cancellable=True,
        )
        async def invalid(self, request: _Input) -> _Output:
            return _Output(value=1)

    with pytest.raises(ManifestError, match="require OperationContext"):
        ManifestDeclaration.discover(_InvalidProvider)


def test_rejects_contradictory_progress_policy() -> None:
    with pytest.raises(ValueError, match="percentages are forbidden"):
        OperationProgressPolicy(
            percentage_mode=ProgressPercentageMode.FORBIDDEN,
            monotonic=True,
        )


def _runtime_record(
    *,
    cancellable: bool = True,
    maximum_observers: int = 1,
) -> OperationLifecycleRecord:
    admitted = datetime.now(UTC)
    return OperationLifecycleRecord(
        admission_record=operation_admission_pb2.OperationAdmissionRecord(
            operation_id=str(uuid4()),
            request_fingerprint="sha256:" + ("a" * 64),
            admitted_at=_timestamp(admitted),
            record_expires_at=_timestamp(admitted + timedelta(minutes=5)),
            admitted_endpoint_generation=1,
        ),
        operation_identifier="example.lifecycle/run@1",
        manifest_revision="sha256:" + ("b" * 64),
        result_model=_Output,
        result_validator=Draft202012Validator(
            _Output.model_json_schema(mode="serialization")
        ),
        cancellable=cancellable,
        progress_policy=None,
        maximum_observers=maximum_observers,
    )


@pytest.mark.asyncio
async def test_pre_start_cancellation_prevents_dispatch() -> None:
    record = _runtime_record()
    calls = 0

    async def dispatch(_context: OperationContext) -> ProviderModel:
        nonlocal calls
        calls += 1
        return _Output(value=1)

    disposition, requested = record.request_cancellation()
    assert disposition == (
        operation_lifecycle_pb2.CANCELLATION_DISPOSITION_REQUESTED
    )
    assert requested.sequence == _CANCELLATION_REQUEST_SEQUENCE
    await record.execute(
        operation_id=requested.admission_record.operation_id,
        execution_deadline=datetime.now(UTC) + timedelta(minutes=1),
        execution_context={},
        dispatch=dispatch,
    )
    terminal = record.snapshot()
    assert calls == 0
    assert terminal.state == (
        operation_lifecycle_pb2.OPERATION_STATE_CANCELLED
    )
    assert terminal.sequence == _PRE_START_TERMINAL_SEQUENCE
    assert terminal.cancellation.effects.side_effects == (
        operation_lifecycle_pb2.SIDE_EFFECT_STATE_NONE
    )


@pytest.mark.asyncio
async def test_observer_capacity_and_current_state_coalescing() -> None:
    record = _runtime_record(maximum_observers=1)
    observer, accepted = record.attach(0)
    with pytest.raises(LifecycleObserverCapacityError):
        record.attach(0)

    async def dispatch(context: OperationContext) -> ProviderModel:
        await context.report_progress("First", percentage=10)
        await context.report_progress("Second", percentage=20)
        return _Output(value=2)

    await record.execute(
        operation_id=accepted.admission_record.operation_id,
        execution_deadline=datetime.now(UTC) + timedelta(minutes=1),
        execution_context={},
        dispatch=dispatch,
    )
    current = await record.next_snapshot(observer, accepted.sequence)
    assert current.state == operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED
    assert current.sequence == _COALESCED_TERMINAL_SEQUENCE
    assert current.progress.message == "Second"
    record.detach(observer)


@pytest.mark.asyncio
async def test_observers_are_isolated_and_shutdown_detaches_waiters() -> None:
    record = _runtime_record(maximum_observers=2)
    first, accepted = record.attach(0)
    second, _ = record.attach(0)
    record.detach(first)

    waiting = asyncio.create_task(
        record.next_snapshot(second, accepted.sequence)
    )
    await asyncio.sleep(0)
    record.detach_all()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert first.closed
    assert second.closed


@pytest.mark.asyncio
async def test_active_record_survives_expiry_then_maps_to_expired() -> None:
    release = asyncio.Event()

    async def dispatch(_context: OperationContext) -> ProviderModel:
        await release.wait()
        return _Output(value=1)

    runtime = OperationAdmissionRuntime(
        maximum_records=1,
        maximum_dispatches=1,
        record_retention_seconds=0.01,
        tombstone_retention_seconds=1,
    )
    operation_id = str(uuid4())
    fingerprint = "sha256:" + ("d" * 64)
    decision = runtime.admit(
        operation_id=operation_id,
        fingerprint=fingerprint,
        endpoint_generation=1,
        operation_identifier="example.lifecycle/run@1",
        manifest_revision="sha256:" + ("e" * 64),
        result_model=_Output,
        result_validator=Draft202012Validator(
            _Output.model_json_schema(mode="serialization")
        ),
        cancellable=False,
        progress_policy=None,
        execution_deadline=datetime.now(UTC) + timedelta(minutes=1),
        execution_context={},
        dispatch=dispatch,
    )
    await asyncio.sleep(0.02)
    assert runtime.resolve_lifecycle(operation_id, fingerprint).snapshot()
    assert runtime.lookup(operation_id, fingerprint) is not None

    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    with pytest.raises(AdmissionRegistryError) as captured:
        runtime.resolve_lifecycle(operation_id, fingerprint)
    assert captured.value.failure is AdmissionRegistryFailure.EXPIRED
    assert decision.accepted_new
    await runtime.close()


@pytest.mark.asyncio
async def test_slow_observer_is_detached_without_stopping_execution() -> None:
    release = asyncio.Event()

    async def dispatch(_context: OperationContext) -> ProviderModel:
        await release.wait()
        return _Output(value=1)

    endpoint = ProviderEndpointIdentity(uuid4(), 1)
    sessions = SessionRegistry(endpoint)
    session_id = sessions.negotiate(ProtocolVersion(1, 0))
    runtime = OperationAdmissionRuntime(
        maximum_records=1,
        maximum_dispatches=1,
        record_retention_seconds=60,
        tombstone_retention_seconds=60,
    )
    operation_id = str(uuid4())
    fingerprint = "sha256:" + ("f" * 64)
    runtime.admit(
        operation_id=operation_id,
        fingerprint=fingerprint,
        endpoint_generation=1,
        operation_identifier="example.lifecycle/run@1",
        manifest_revision="sha256:" + ("a" * 64),
        result_model=_Output,
        result_validator=Draft202012Validator(
            _Output.model_json_schema(mode="serialization")
        ),
        cancellable=False,
        progress_policy=None,
        execution_deadline=datetime.now(UTC) + timedelta(minutes=1),
        execution_context={},
        dispatch=dispatch,
    )
    service = OperationLifecycleService(
        endpoint=endpoint,
        sessions=sessions,
        runtime=runtime,
        delivery_timeout_seconds=0.01,
    )
    request = operation_lifecycle_pb2.WatchOperationRequest(
        session_binding=operation_admission_pb2.OperationSessionBinding(
            expected_provider_instance_id=str(endpoint.provider_instance_id),
            expected_endpoint_generation=endpoint.endpoint_generation,
            expected_session_id=session_id,
        ),
        operation_id=operation_id,
        expected_request_fingerprint=fingerprint,
    )

    class _AbortedError(Exception):
        def __init__(self, status) -> None:
            self.status = status

    class _StalledContext:
        async def write(self, _response) -> None:
            await asyncio.Event().wait()

        async def abort_with_status(self, status) -> None:
            raise _AbortedError(status)

    with pytest.raises(_AbortedError) as captured:
        await service.WatchOperation(request, _StalledContext())  # type: ignore[arg-type]
    assert captured.value.status.code is grpc.StatusCode.RESOURCE_EXHAUSTED
    assert not runtime.resolve_lifecycle(operation_id, fingerprint).terminal
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert runtime.resolve_lifecycle(operation_id, fingerprint).terminal
    await runtime.close()


@pytest.mark.asyncio
async def test_execution_deadline_produces_sanitized_failure() -> None:
    record = _runtime_record(cancellable=False)
    cancelled = asyncio.Event()

    async def dispatch(_context: OperationContext) -> ProviderModel:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return _Output(value=1)

    operation_id = record.snapshot().admission_record.operation_id
    await record.execute(
        operation_id=operation_id,
        execution_deadline=datetime.now(UTC) + timedelta(milliseconds=10),
        execution_context={},
        dispatch=dispatch,
    )
    assert cancelled.is_set()
    terminal = record.snapshot()
    assert terminal.state == operation_lifecycle_pb2.OPERATION_STATE_FAILED
    assert terminal.failure.code == (
        "stateforge.operation.execution_deadline_exceeded"
    )


@pytest.mark.asyncio
async def test_author_timeout_is_not_reported_as_execution_deadline() -> None:
    record = _runtime_record(cancellable=False)

    async def dispatch(_context: OperationContext) -> ProviderModel:
        raise TimeoutError("an operation dependency timed out")

    operation_id = record.snapshot().admission_record.operation_id
    await record.execute(
        operation_id=operation_id,
        execution_deadline=datetime.now(UTC) + timedelta(minutes=1),
        execution_context={},
        dispatch=dispatch,
    )
    terminal = record.snapshot()
    assert terminal.state == operation_lifecycle_pb2.OPERATION_STATE_FAILED
    assert terminal.failure.code == "stateforge.operation.provider_error"
