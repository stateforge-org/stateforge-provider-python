"""Verify installed R6 behavior through an independent Protocol peer."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from grpc_status import rpc_status
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)
from stateforge_protocol.sfp.manifest.v1 import (
    manifest_pb2,
    manifest_pb2_grpc,
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
    OperationProgressPolicy,
    OperationSideEffects,
    Platform,
    Provider,
    ProviderModel,
    operation,
)

_TERMINAL_STATES = {
    operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED,
    operation_lifecycle_pb2.OPERATION_STATE_FAILED,
    operation_lifecycle_pb2.OPERATION_STATE_CANCELLED,
}
_COMPLETE_PERCENTAGE = 100.0


class Input(ProviderModel):
    """Select one deterministic lifecycle path."""

    mode: str


class Result(ProviderModel):
    """Return one typed terminal result."""

    value: int


class LifecycleProvider(Provider):
    """Expose lifecycle behavior through only the public author API."""

    identity = "stateforge.test.operation_lifecycle"
    display_name = "StateForge Operation Lifecycle CI Provider"
    version = "0.1.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(self, runtime_directory: Path) -> None:
        """Bind deterministic author controls to scenario-owned paths."""
        super().__init__(
            discovery_directory=runtime_directory / "discovery",
            state_directory=runtime_directory / "state",
        )
        self.dispatches = 0
        self.success_started = asyncio.Event()
        self.success_release = asyncio.Event()
        self.cancel_started = asyncio.Event()
        self.cancellation_seen = asyncio.Event()
        self.cancellation_release = asyncio.Event()
        self.unsupported_started = asyncio.Event()
        self.unsupported_release = asyncio.Event()

    @operation(
        "stateforge.test/execute@1",
        cancellable=True,
        progress=OperationProgressPolicy.determinate(),
    )
    async def execute(
        self,
        request: Input,
        context: OperationContext,
    ) -> Result:
        """Exercise success, cancellation, and invalid progress."""
        self.dispatches += 1
        if request.mode == "invalid-progress":
            await context.report_progress("Half", percentage=50)
            await context.report_progress("Backwards", percentage=40)
        await context.report_progress("Started", percentage=0)
        if request.mode == "cancel":
            self.cancel_started.set()
            await context.wait_for_cancellation()
            self.cancellation_seen.set()
            await self.cancellation_release.wait()
            raise OperationCancelledError(
                OperationEffects(
                    side_effects=OperationSideEffects.PRESENT,
                    cleanup=OperationCleanup.COMPLETED,
                    explanation="Temporary work was removed.",
                )
            )
        self.success_started.set()
        await self.success_release.wait()
        await context.report_progress("Half", percentage=50)
        await context.report_progress("Finished", percentage=100)
        return Result(value=100)

    @operation("stateforge.test/unsupported@1")
    async def unsupported(
        self,
        request: Input,
        context: OperationContext,
    ) -> Result:
        """Keep one non-cancellable operation active for its decision."""
        del request, context
        self.dispatches += 1
        self.unsupported_started.set()
        await self.unsupported_release.wait()
        return Result(value=1)


def _timestamp(value: datetime) -> Timestamp:
    timestamp = Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


async def _descriptor(
    directory: Path,
    provider_task: asyncio.Task[None],
) -> dict[str, object]:
    async with asyncio.timeout(5):
        while True:
            paths = await asyncio.to_thread(
                lambda: tuple(directory.glob("*.sfp.json"))
            )
            if paths:
                return json.loads(await asyncio.to_thread(paths[0].read_text))
            if provider_task.done():
                await provider_task
            await asyncio.sleep(0.01)


async def _session(
    channel: grpc.aio.Channel,
    descriptor: dict[str, object],
) -> tuple[
    bootstrap_pb2.HandshakeResponse,
    manifest_pb2.GetManifestResponse,
]:
    handshake = await bootstrap_pb2_grpc.BootstrapServiceStub(
        channel
    ).Handshake(
        bootstrap_pb2.HandshakeRequest(
            agent_runtime=bootstrap_pb2.AgentRuntime(
                runtime_id=str(uuid4()),
                software_version="0.1.0",
            ),
            expected_provider_instance_id=descriptor["provider_instance_id"],
            expected_endpoint_generation=descriptor["endpoint_generation"],
            supported_sfp_versions=[
                bootstrap_pb2.ProtocolVersion(major=1, minor=0)
            ],
        ),
        timeout=3,
    )
    manifest = await manifest_pb2_grpc.ManifestServiceStub(
        channel
    ).GetManifest(
        manifest_pb2.GetManifestRequest(
            expected_provider_instance_id=handshake.provider_instance_id,
            expected_endpoint_generation=handshake.endpoint_generation,
            expected_session_id=handshake.session_id,
            supported_manifest_schema_versions=[1],
        ),
        timeout=3,
    )
    return handshake, manifest


def _start_request(
    handshake: bootstrap_pb2.HandshakeResponse,
    manifest: manifest_pb2.GetManifestResponse,
    *,
    mode: str,
    identifier: str = "stateforge.test/execute@1",
) -> operation_admission_pb2.StartOperationRequest:
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
                manifest_revision=manifest.manifest_revision,
            ),
            execution_context=Struct(),
        ),
        admission_mode=operation_admission_pb2.ADMISSION_MODE_ADMIT_OR_RESOLVE,
    )


def _watch_request(
    start: operation_admission_pb2.StartOperationRequest,
    *,
    after_sequence: int = 0,
) -> operation_lifecycle_pb2.WatchOperationRequest:
    return operation_lifecycle_pb2.WatchOperationRequest(
        session_binding=start.session_binding,
        operation_id=start.invocation.operation_id,
        expected_request_fingerprint=(
            admission_validation.compute_request_fingerprint(start.invocation)
        ),
        after_sequence=after_sequence,
    )


def _cancel_request(
    start: operation_admission_pb2.StartOperationRequest,
) -> operation_lifecycle_pb2.CancelOperationRequest:
    return operation_lifecycle_pb2.CancelOperationRequest(
        session_binding=start.session_binding,
        operation_id=start.invocation.operation_id,
        expected_request_fingerprint=(
            admission_validation.compute_request_fingerprint(start.invocation)
        ),
    )


async def _terminal(
    lifecycle: operation_lifecycle_pb2_grpc.OperationLifecycleServiceStub,
    request: operation_lifecycle_pb2.WatchOperationRequest,
) -> tuple[
    list[operation_lifecycle_pb2.WatchOperationResponse],
    operation_lifecycle_pb2.OperationSnapshot,
]:
    call = lifecycle.WatchOperation(request, timeout=5)
    responses: list[operation_lifecycle_pb2.WatchOperationResponse] = []
    previous_sequence: int | None = None
    while True:
        response = await call.read()
        if response is grpc.aio.EOF:
            break
        lifecycle_validation.validate_watch_exchange(
            request,
            response,
            previous_sequence=previous_sequence,
        )
        responses.append(response)
        previous_sequence = response.snapshot.sequence
        if response.snapshot.state in _TERMINAL_STATES:
            if await call.read() is not grpc.aio.EOF:
                raise RuntimeError("terminal Watch remained open")
            break
    if not responses:
        raise RuntimeError("Watch returned no lifecycle snapshot")
    return responses, responses[-1].snapshot


async def _expect_watch_error(
    lifecycle: operation_lifecycle_pb2_grpc.OperationLifecycleServiceStub,
    request: operation_lifecycle_pb2.WatchOperationRequest,
    code: grpc.StatusCode,
    reason: int,
) -> str:
    call = lifecycle.WatchOperation(request, timeout=3)
    try:
        await call.read()
    except grpc.aio.AioRpcError as error:
        if error.code() is not code:
            raise RuntimeError(
                f"expected {code.name}, got {error.code().name}"
            ) from error
        status = rpc_status.from_call(error)
        if status is None or not status.details:
            raise RuntimeError(
                "Lifecycle error omitted typed details"
            ) from error
        detail = operation_lifecycle_pb2.OperationLifecycleErrorDetail()
        if not status.details[0].Unpack(detail) or detail.reason != reason:
            raise RuntimeError("Lifecycle error detail mismatch") from error
        return error.code().name
    raise RuntimeError("Lifecycle Watch unexpectedly succeeded")


async def _run(  # noqa: PLR0912, PLR0915
    runtime_directory: Path,
) -> dict[str, object]:
    discovery = runtime_directory / "discovery"
    discovery.mkdir(parents=True, exist_ok=True)
    provider = LifecycleProvider(runtime_directory)
    provider_task = asyncio.create_task(provider.serve())
    channel: grpc.aio.Channel | None = None
    try:
        descriptor = await _descriptor(discovery, provider_task)
        transport = descriptor["transport"]
        if not isinstance(transport, dict):
            raise RuntimeError("Provider descriptor transport is invalid")
        socket_path = str(transport["socket_path"])
        channel = grpc.aio.insecure_channel(
            f"unix:{socket_path}",
            options=(
                (
                    "grpc.max_receive_message_length",
                    lifecycle_contract.MAX_RESPONSE_BYTES,
                ),
                ("grpc.max_send_message_length", 9 * 1024 * 1024),
            ),
        )
        await asyncio.wait_for(channel.channel_ready(), timeout=3)
        handshake, manifest = await _session(channel, descriptor)
        admission = operation_admission_pb2_grpc.OperationAdmissionServiceStub(
            channel
        )
        lifecycle = operation_lifecycle_pb2_grpc.OperationLifecycleServiceStub(
            channel
        )

        success = _start_request(handshake, manifest, mode="success")
        await admission.StartOperation(success, timeout=3)
        await asyncio.wait_for(provider.success_started.wait(), timeout=3)
        success_watch = _watch_request(success)
        success_call = lifecycle.WatchOperation(success_watch, timeout=5)
        initial = await success_call.read()
        lifecycle_validation.validate_watch_exchange(success_watch, initial)
        provider.success_release.set()
        success_responses = [initial]
        previous = initial.snapshot.sequence
        while initial.snapshot.state not in _TERMINAL_STATES:
            initial = await success_call.read()
            lifecycle_validation.validate_watch_exchange(
                success_watch,
                initial,
                previous_sequence=previous,
            )
            success_responses.append(initial)
            previous = initial.snapshot.sequence
        if await success_call.read() is not grpc.aio.EOF:
            raise RuntimeError("successful terminal Watch remained open")
        success_terminal = success_responses[-1].snapshot
        if MessageToDict(success_terminal.success.result) != {"value": 100.0}:
            raise RuntimeError("typed terminal result changed")
        if success_terminal.progress.percentage != _COMPLETE_PERCENTAGE:
            raise RuntimeError("determinate progress did not end at 100")

        replay_request = _watch_request(
            success,
            after_sequence=success_terminal.sequence,
        )
        replay_responses, replay_terminal = await _terminal(
            lifecycle, replay_request
        )
        lifecycle_validation.validate_terminal_replay(
            success_terminal, replay_terminal
        )

        cancellation = _start_request(handshake, manifest, mode="cancel")
        await admission.StartOperation(cancellation, timeout=3)
        await asyncio.wait_for(provider.cancel_started.wait(), timeout=3)
        requested = await lifecycle.CancelOperation(
            _cancel_request(cancellation), timeout=3
        )
        lifecycle_validation.validate_cancel_exchange(
            _cancel_request(cancellation), requested
        )
        await asyncio.wait_for(provider.cancellation_seen.wait(), timeout=3)
        repeated = await lifecycle.CancelOperation(
            _cancel_request(cancellation), timeout=3
        )
        if repeated.disposition != (
            operation_lifecycle_pb2.CANCELLATION_DISPOSITION_ALREADY_REQUESTED
        ):
            raise RuntimeError("repeated cancellation changed its decision")
        provider.cancellation_release.set()
        _, cancellation_terminal = await _terminal(
            lifecycle, _watch_request(cancellation)
        )
        if cancellation_terminal.state != (
            operation_lifecycle_pb2.OPERATION_STATE_CANCELLED
        ):
            raise RuntimeError("cooperative cancellation was not confirmed")

        unsupported = _start_request(
            handshake,
            manifest,
            mode="unsupported",
            identifier="stateforge.test/unsupported@1",
        )
        await admission.StartOperation(unsupported, timeout=3)
        await asyncio.wait_for(provider.unsupported_started.wait(), timeout=3)
        unsupported_response = await lifecycle.CancelOperation(
            _cancel_request(unsupported), timeout=3
        )
        if unsupported_response.disposition != (
            operation_lifecycle_pb2.CANCELLATION_DISPOSITION_UNSUPPORTED
        ):
            raise RuntimeError("unsupported cancellation was not rejected")
        provider.unsupported_release.set()
        await _terminal(lifecycle, _watch_request(unsupported))

        invalid = _start_request(handshake, manifest, mode="invalid-progress")
        await admission.StartOperation(invalid, timeout=3)
        _, invalid_terminal = await _terminal(
            lifecycle, _watch_request(invalid)
        )
        if invalid_terminal.failure.code != (
            "stateforge.operation.invalid_progress"
        ):
            raise RuntimeError("invalid progress was not normalized")

        stale = _watch_request(success)
        stale.session_binding.expected_session_id = "stale-session"
        stale_status = await _expect_watch_error(
            lifecycle,
            stale,
            grpc.StatusCode.FAILED_PRECONDITION,
            operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_SESSION_PRECONDITION_FAILED,
        )
        oversized = _watch_request(success)
        oversized.expected_request_fingerprint = "x" * (
            lifecycle_contract.MAX_REQUEST_BYTES + 1
        )
        oversized_status = await _expect_watch_error(
            lifecycle,
            oversized,
            grpc.StatusCode.INVALID_ARGUMENT,
            operation_lifecycle_pb2.LIFECYCLE_ERROR_REASON_INVALID_REQUEST,
        )

        provider.request_shutdown()
        await asyncio.wait_for(provider_task, timeout=5)
        if await asyncio.to_thread(Path(socket_path).exists):
            raise RuntimeError("Provider socket survived shutdown")
        if await asyncio.to_thread(
            lambda: tuple(discovery.glob("*.sfp.json"))
        ):
            raise RuntimeError("Provider descriptor survived shutdown")

        return {
            "installed_artifacts": {
                "stateforge-provider": version("stateforge-provider"),
                "stateforge-protocol": version("stateforge-protocol"),
            },
            "provider_instance_id": handshake.provider_instance_id,
            "endpoint_generation": handshake.endpoint_generation,
            "session_id": handshake.session_id,
            "success_sequences": [
                response.snapshot.sequence for response in success_responses
            ],
            "success_result": MessageToDict(success_terminal.success.result),
            "terminal_progress": success_terminal.progress.percentage,
            "terminal_replay_count": len(replay_responses),
            "cancellation_requested": (
                operation_lifecycle_pb2.CancellationDisposition.Name(
                    requested.disposition
                )
            ),
            "cancellation_repeated": (
                operation_lifecycle_pb2.CancellationDisposition.Name(
                    repeated.disposition
                )
            ),
            "cancellation_terminal": (
                operation_lifecycle_pb2.OperationState.Name(
                    cancellation_terminal.state
                )
            ),
            "unsupported_cancellation": (
                operation_lifecycle_pb2.CancellationDisposition.Name(
                    unsupported_response.disposition
                )
            ),
            "invalid_progress_code": invalid_terminal.failure.code,
            "stale_fence_status": stale_status,
            "oversized_request_status": oversized_status,
            "author_dispatches": provider.dispatches,
            "final_process_state": "stopped",
            "descriptor_removed": True,
            "socket_removed": True,
        }
    finally:
        provider.request_shutdown()
        if not provider_task.done():
            await asyncio.wait_for(provider_task, timeout=5)
        if channel is not None:
            await channel.close()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """Run the installed-wheel scenario and write bounded evidence."""
    arguments = _arguments()
    arguments.output.write_text(
        json.dumps(
            asyncio.run(_run(arguments.runtime_directory)),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
