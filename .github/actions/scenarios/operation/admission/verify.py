"""Verify R5 and R19 admission through an independent Protocol peer."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

import grpc
from google.protobuf.json_format import ParseDict, ParseError
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from grpc_status import rpc_status
from pydantic import Field
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
    validation,
)

from stateforge_provider import (
    OperationContext,
    Platform,
    Provider,
    ProviderModel,
    RequirementCheckResult,
    operation,
    requirement_check,
)
from stateforge_provider._services.operation_admission.service import (
    OperationAdmissionService,
)

_ACCEPTED_NEW = operation_admission_pb2.ADMISSION_DISPOSITION_ACCEPTED_NEW
_RESOLVED_EXISTING = (
    operation_admission_pb2.ADMISSION_DISPOSITION_RESOLVED_EXISTING
)
_RECORD_RETENTION_SECONDS = 0.2
_TOMBSTONE_RETENTION_SECONDS = 0.2
_PRUNE_GRACE_SECONDS = 0.05
_EXPECTED_LOST_RESPONSE_ATTEMPTS = 2


class Input(ProviderModel):
    """One typed request with a secret-bearing field."""

    value: int
    secret: str = Field(json_schema_extra={"writeOnly": True})


class Result(ProviderModel):
    """One typed operation result."""

    accepted: bool


class AdmissionProvider(Provider):
    """Expose one fenced operation through only the public author API."""

    identity = "stateforge.test.operation_admission"
    display_name = "StateForge Operation Admission CI Provider"
    version = "0.1.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(
        self,
        runtime_directory: Path,
        *,
        short_retention: bool = False,
    ) -> None:
        """Bind the fixture to scenario-owned runtime directories."""
        super().__init__(
            discovery_directory=runtime_directory / "discovery",
            state_directory=runtime_directory / "state",
        )
        if short_retention:
            self._configuration = replace(
                self._configuration,
                operation_record_retention_seconds=_RECORD_RETENTION_SECONDS,
                operation_tombstone_retention_seconds=(
                    _TOMBSTONE_RETENTION_SECONDS
                ),
            )
        self.requirement_satisfied = True
        self.dispatches = 0
        self.completed = asyncio.Event()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.context: OperationContext | None = None

    @requirement_check("runtime.ready", "Runtime is ready")
    async def ready(self) -> RequirementCheckResult:
        """Report the deterministic runtime prerequisite."""
        if self.requirement_satisfied:
            return RequirementCheckResult.satisfied()
        return RequirementCheckResult.unsatisfied("Runtime is not ready")

    @operation(
        "stateforge.test/execute@1",
        requires=("runtime.ready",),
        implements=("stateforge.test.v1.audited",),
    )
    async def execute(
        self,
        request: Input,
        context: OperationContext,
    ) -> Result:
        """Retain dispatch so concurrent retries converge visibly."""
        self.dispatches += 1
        self.context = context
        self.started.set()
        await self.release.wait()
        self.completed.set()
        return Result(accepted=request.value > 0)


def _timestamp(value: datetime) -> Timestamp:
    timestamp = Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _request(
    handshake: bootstrap_pb2.HandshakeResponse,
    manifest: manifest_pb2.GetManifestResponse,
    *,
    operation_id: str,
    value: int = 1,
    secret: str | None = None,
    generation: int | None = None,
    roles: tuple[str, ...] = ("stateforge.test.v1.audited",),
    payload_fields: dict[str, str | int | bool | None] | None = None,
    mode: operation_admission_pb2.AdmissionMode.ValueType = (
        operation_admission_pb2.ADMISSION_MODE_ADMIT_OR_RESOLVE
    ),
    deadline: datetime | None = None,
) -> operation_admission_pb2.StartOperationRequest:
    payload = Struct()
    ParseDict(
        payload_fields
        if payload_fields is not None
        else {"value": value, "secret": secret or "not-evidence"},
        payload,
    )
    execution_context = Struct()
    ParseDict(
        {"authority": "ci-policy", "nested": {"items": [1, 2]}},
        execution_context,
    )
    return operation_admission_pb2.StartOperationRequest(
        session_binding=operation_admission_pb2.OperationSessionBinding(
            expected_provider_instance_id=handshake.provider_instance_id,
            expected_endpoint_generation=(
                generation
                if generation is not None
                else handshake.endpoint_generation
            ),
            expected_session_id=handshake.session_id,
        ),
        invocation=operation_admission_pb2.OperationInvocation(
            operation_id=operation_id,
            operation_identifier="stateforge.test/execute@1",
            payload=payload,
            execution_deadline=_timestamp(
                deadline
                if deadline is not None
                else datetime.now(UTC) + timedelta(minutes=5)
            ),
            contract=operation_admission_pb2.OperationContractContext(
                manifest_revision=manifest.manifest_revision,
                required_implementation_roles=roles,
            ),
            execution_context=execution_context,
        ),
        admission_mode=mode,
    )


async def _verify_canonical_rejections(
    provider: AdmissionProvider,
    admission: grpc.aio.UnaryUnaryMultiCallable[
        operation_admission_pb2.StartOperationRequest,
        operation_admission_pb2.StartOperationResponse,
    ],
    handshake: bootstrap_pb2.HandshakeResponse,
    manifest: manifest_pb2.GetManifestResponse,
) -> dict[str, str | bool]:
    """Replay canonical malformed, schema, and deadline rejections."""
    statuses: dict[str, str | bool] = {}
    statuses["malformed_request_status"] = await _expect_error(
        admission,
        operation_admission_pb2.StartOperationRequest(),
        grpc.StatusCode.INVALID_ARGUMENT,
        operation_admission_pb2.ADMISSION_ERROR_REASON_INVALID_OPERATION_REQUEST,
    )
    before = provider.dispatches
    statuses["schema_payload_status"] = await _expect_error(
        admission,
        _request(
            handshake,
            manifest,
            operation_id=str(uuid4()),
            payload_fields={"value": "one", "secret": "not-evidence"},
        ),
        grpc.StatusCode.INVALID_ARGUMENT,
        operation_admission_pb2.ADMISSION_ERROR_REASON_INVALID_OPERATION_REQUEST,
    )
    array_rejected = False
    try:
        ParseDict(["not", "an", "object"], Struct())
    except (ParseError, ValueError):
        array_rejected = True
    if not array_rejected:
        raise RuntimeError("array payload parsed into an envelope field")
    statuses["array_payload_rejected_at_envelope"] = True
    identity = str(uuid4())
    statuses["deadline_status"] = await _expect_error(
        admission,
        _request(
            handshake,
            manifest,
            operation_id=identity,
            deadline=datetime.now(UTC) - timedelta(seconds=1),
        ),
        grpc.StatusCode.DEADLINE_EXCEEDED,
        operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_DEADLINE_EXPIRED,
    )
    statuses["deadline_record_absent_status"] = await _expect_error(
        admission,
        _request(
            handshake,
            manifest,
            operation_id=identity,
            mode=operation_admission_pb2.ADMISSION_MODE_RESOLVE_ONLY,
        ),
        grpc.StatusCode.FAILED_PRECONDITION,
        operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_RECORD_UNAVAILABLE,
    )
    if provider.dispatches != before:
        raise RuntimeError("canonical rejection dispatched the operation")
    return statuses


async def _verify_lost_response_replay(  # noqa: PLR0915
    base_directory: Path,
) -> dict[str, object]:
    """Lose one admitted response and prove identical replay resolves."""
    original = OperationAdmissionService.StartOperation
    attempts: list[bytes] = []
    drop_once = True

    async def start_operation(
        service: OperationAdmissionService,
        request: operation_admission_pb2.StartOperationRequest,
        context: grpc.aio.ServicerContext[
            operation_admission_pb2.StartOperationRequest,
            operation_admission_pb2.StartOperationResponse,
        ],
    ) -> operation_admission_pb2.StartOperationResponse:
        nonlocal drop_once
        attempts.append(request.SerializeToString(deterministic=True))
        response = await original(service, request, context)
        if drop_once:
            drop_once = False
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Injected response loss after durable admission",
            )
        return response

    OperationAdmissionService.StartOperation = start_operation
    provider_discovery = base_directory / "discovery"
    provider_discovery.mkdir(parents=True)
    provider = AdmissionProvider(base_directory)
    provider_task = asyncio.create_task(provider.serve())
    channel: grpc.aio.Channel | None = None
    try:
        discovery = base_directory / "discovery"
        descriptor = await _descriptor(discovery, provider_task)
        transport = descriptor["transport"]
        if not isinstance(transport, dict):
            raise RuntimeError("Provider descriptor transport is invalid")
        socket_path = str(transport["socket_path"])
        channel = grpc.aio.insecure_channel(f"unix:{socket_path}")
        await asyncio.wait_for(channel.channel_ready(), timeout=3)
        handshake, manifest = await _session(channel, descriptor)
        admission = operation_admission_pb2_grpc.OperationAdmissionServiceStub(
            channel
        ).StartOperation
        request = _request(handshake, manifest, operation_id=str(uuid4()))
        try:
            await admission(request, timeout=3)
        except grpc.aio.AioRpcError as error:
            if error.code() is not grpc.StatusCode.UNAVAILABLE:
                raise RuntimeError("wrong response-loss status") from error
        else:
            raise RuntimeError("first response was not lost")
        await asyncio.wait_for(provider.started.wait(), timeout=2)
        before = provider.dispatches
        replayed = await admission(request, timeout=3)
        validation.validate_admission_exchange(request, replayed)
        if replayed.disposition != _RESOLVED_EXISTING:
            raise RuntimeError("lost-response replay did not resolve existing")
        if (
            len(attempts) != _EXPECTED_LOST_RESPONSE_ATTEMPTS
            or attempts[0] != attempts[1]
        ):
            raise RuntimeError("lost-response replay changed request bytes")
        if provider.dispatches != before:
            raise RuntimeError("lost-response replay dispatched again")
        return {
            "request_fingerprint": replayed.record.request_fingerprint,
            "lost_response_attempts": len(attempts),
            "lost_response_replay_status": (
                operation_admission_pb2.AdmissionDisposition.Name(
                    replayed.disposition
                )
            ),
            "lost_response_replay_dispatches": provider.dispatches,
        }
    finally:
        OperationAdmissionService.StartOperation = original
        provider.request_shutdown()
        if not provider_task.done():
            await asyncio.wait_for(provider_task, timeout=5)
        if channel is not None:
            await channel.close()


async def _connect_provider(
    discovery_directory: Path,
    provider_task: asyncio.Task[None],
) -> tuple[
    grpc.aio.Channel,
    grpc.aio.UnaryUnaryMultiCallable[
        operation_admission_pb2.StartOperationRequest,
        operation_admission_pb2.StartOperationResponse,
    ],
    bootstrap_pb2.HandshakeResponse,
    manifest_pb2.GetManifestResponse,
    dict[str, object],
]:
    """Open one admission session to a serving fixture instance."""
    descriptor = await _descriptor(discovery_directory, provider_task)
    transport = descriptor["transport"]
    if not isinstance(transport, dict):
        raise RuntimeError("Provider descriptor transport is invalid")
    socket_path = str(transport["socket_path"])
    channel = grpc.aio.insecure_channel(f"unix:{socket_path}")
    await asyncio.wait_for(channel.channel_ready(), timeout=3)
    handshake, manifest = await _session(channel, descriptor)
    admission = operation_admission_pb2_grpc.OperationAdmissionServiceStub(
        channel
    ).StartOperation
    return channel, admission, handshake, manifest, descriptor


async def _verify_expiry_and_restart(  # noqa: PLR0912, PLR0915
    base_directory: Path,
) -> dict[str, object]:
    """Expire a retained record, reuse the identity, and restart."""
    provider_discovery = base_directory / "discovery"
    provider_discovery.mkdir(parents=True)
    provider: AdmissionProvider | None = None
    provider_task: asyncio.Task[None] | None = None
    restart_provider: AdmissionProvider | None = None
    restart_task: asyncio.Task[None] | None = None
    channel: grpc.aio.Channel | None = None
    restart_channel: grpc.aio.Channel | None = None
    try:
        provider = AdmissionProvider(base_directory, short_retention=True)
        provider_task = asyncio.create_task(provider.serve())
        (
            channel,
            admission,
            handshake,
            manifest,
            descriptor,
        ) = await _connect_provider(
            base_directory / "discovery",
            provider_task,
        )
        identity = str(uuid4())
        request = _request(handshake, manifest, operation_id=identity)
        admitted = await admission(request, timeout=3)
        validation.validate_admission_exchange(request, admitted)
        if admitted.disposition != _ACCEPTED_NEW:
            raise RuntimeError("expiry identity was not admitted")
        await asyncio.wait_for(provider.started.wait(), timeout=2)
        provider.release.set()
        await asyncio.wait_for(provider.completed.wait(), timeout=2)
        reuse_dispatches = provider.dispatches
        provider.started.clear()
        await asyncio.sleep(_RECORD_RETENTION_SECONDS + _PRUNE_GRACE_SECONDS)
        expired_status = await _expect_error(
            admission,
            _request(
                handshake,
                manifest,
                operation_id=identity,
                mode=operation_admission_pb2.ADMISSION_MODE_RESOLVE_ONLY,
            ),
            grpc.StatusCode.FAILED_PRECONDITION,
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_RECORD_EXPIRED,
        )
        await asyncio.sleep(
            _TOMBSTONE_RETENTION_SECONDS + _PRUNE_GRACE_SECONDS
        )
        reused = await admission(request, timeout=3)
        validation.validate_admission_exchange(request, reused)
        if reused.disposition != _ACCEPTED_NEW:
            raise RuntimeError("expiry identity reuse did not re-admit")
        await asyncio.wait_for(provider.started.wait(), timeout=2)
        if provider.dispatches != reuse_dispatches + 1:
            raise RuntimeError("expiry identity reuse dispatched unexpectedly")
        provider.request_shutdown()
        await asyncio.wait_for(provider_task, timeout=5)
        restart_provider = AdmissionProvider(
            base_directory, short_retention=True
        )
        restart_task = asyncio.create_task(restart_provider.serve())
        (
            restart_channel,
            restart_admission,
            restart_handshake,
            restart_manifest,
            restart_descriptor,
        ) = await _connect_provider(
            base_directory / "discovery",
            restart_task,
        )
        if int(restart_descriptor["endpoint_generation"]) <= int(
            descriptor["endpoint_generation"]
        ):
            raise RuntimeError("restart did not allocate a newer generation")
        unavailable_status = await _expect_error(
            restart_admission,
            _request(
                restart_handshake,
                restart_manifest,
                operation_id=identity,
                mode=operation_admission_pb2.ADMISSION_MODE_RESOLVE_ONLY,
            ),
            grpc.StatusCode.FAILED_PRECONDITION,
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_RECORD_UNAVAILABLE,
        )
        if restart_provider.dispatches != 0:
            raise RuntimeError("restart resolve dispatched the operation")
        transport = restart_descriptor["transport"]
        if not isinstance(transport, dict):
            raise RuntimeError("restart descriptor transport is invalid")
        restart_socket = str(transport["socket_path"])
        restart_provider.request_shutdown()
        await asyncio.wait_for(restart_task, timeout=5)
        if await asyncio.to_thread(Path(restart_socket).exists):
            raise RuntimeError("restart socket survived shutdown")
        return {
            "record_expiry_status": expired_status,
            "expiry_identity_reuse_status": (
                operation_admission_pb2.AdmissionDisposition.Name(
                    reused.disposition
                )
            ),
            "expiry_identity_reuse_dispatches": provider.dispatches,
            "restart_unavailable_status": unavailable_status,
            "restart_resolve_dispatches": restart_provider.dispatches,
        }
    finally:
        if provider is not None:
            provider.request_shutdown()
        if provider_task is not None and not provider_task.done():
            await asyncio.wait_for(provider_task, timeout=5)
        if restart_provider is not None:
            restart_provider.request_shutdown()
        if restart_task is not None and not restart_task.done():
            await asyncio.wait_for(restart_task, timeout=5)
        if channel is not None:
            await channel.close()
        if restart_channel is not None:
            await restart_channel.close()


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


async def _expect_error(
    call: grpc.aio.UnaryUnaryMultiCallable[
        operation_admission_pb2.StartOperationRequest,
        operation_admission_pb2.StartOperationResponse,
    ],
    request: operation_admission_pb2.StartOperationRequest,
    code: grpc.StatusCode,
    reason: int,
) -> str:
    try:
        await call(request, timeout=3)
    except grpc.aio.AioRpcError as error:
        if error.code() is not code:
            raise RuntimeError(
                f"expected {code.name}, got {error.code().name}"
            ) from error
        status = rpc_status.from_call(error)
        if status is None or not status.details:
            raise RuntimeError(
                "Operation Admission error omitted typed details"
            ) from error
        detail = operation_admission_pb2.OperationAdmissionErrorDetail()
        if not status.details[0].Unpack(detail) or detail.reason != reason:
            raise RuntimeError(
                "Operation Admission error detail mismatch"
            ) from error
        return error.code().name
    raise RuntimeError(
        f"Operation Admission unexpectedly accepted {code.name}"
    )


async def _run(  # noqa: PLR0912, PLR0915
    runtime_directory: Path,
) -> dict[str, object]:
    discovery = runtime_directory / "discovery"
    discovery.mkdir(parents=True)
    provider = AdmissionProvider(runtime_directory)
    provider_task = asyncio.create_task(provider.serve())
    channel: grpc.aio.Channel | None = None
    try:
        descriptor = await _descriptor(discovery, provider_task)
        transport = descriptor["transport"]
        if not isinstance(transport, dict):
            raise RuntimeError("Provider descriptor transport is invalid")
        socket_path = str(transport["socket_path"])
        channel = grpc.aio.insecure_channel(f"unix:{socket_path}")
        await asyncio.wait_for(channel.channel_ready(), timeout=3)
        handshake, manifest = await _session(channel, descriptor)
        admission = operation_admission_pb2_grpc.OperationAdmissionServiceStub(
            channel
        ).StartOperation

        stale_status = await _expect_error(
            admission,
            _request(
                handshake,
                manifest,
                operation_id=str(uuid4()),
                generation=handshake.endpoint_generation + 1,
            ),
            grpc.StatusCode.FAILED_PRECONDITION,
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_PRECONDITION_FAILED,
        )
        role_status = await _expect_error(
            admission,
            _request(
                handshake,
                manifest,
                operation_id=str(uuid4()),
                roles=("stateforge.test.v1.missing",),
            ),
            grpc.StatusCode.FAILED_PRECONDITION,
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_INCOMPATIBLE,
        )
        provider.requirement_satisfied = False
        requirement_status = await _expect_error(
            admission,
            _request(handshake, manifest, operation_id=str(uuid4())),
            grpc.StatusCode.FAILED_PRECONDITION,
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_PRECONDITION_FAILED,
        )
        provider.requirement_satisfied = True

        operation_id = str(uuid4())
        request = _request(handshake, manifest, operation_id=operation_id)
        responses = await asyncio.gather(
            *(admission(request, timeout=3) for _ in range(20))
        )
        await asyncio.wait_for(provider.started.wait(), timeout=2)
        if provider.dispatches != 1:
            raise RuntimeError(
                "identical concurrent requests dispatched twice"
            )
        accepted_new = sum(
            response.disposition
            == operation_admission_pb2.ADMISSION_DISPOSITION_ACCEPTED_NEW
            for response in responses
        )
        if accepted_new != 1:
            raise RuntimeError("atomic admission did not select one winner")
        for response in responses:
            validation.validate_admission_exchange(request, response)

        payload_marker = "must-not-appear-in-evidence"
        conflict_status = await _expect_error(
            admission,
            _request(
                handshake,
                manifest,
                operation_id=operation_id,
                value=2,
                secret=payload_marker,
            ),
            grpc.StatusCode.ALREADY_EXISTS,
            operation_admission_pb2.ADMISSION_ERROR_REASON_IDEMPOTENCY_CONFLICT,
        )
        provider.release.set()
        await asyncio.wait_for(provider.completed.wait(), timeout=2)
        terminal_request = operation_admission_pb2.StartOperationRequest()
        terminal_request.CopyFrom(request)
        terminal_request.admission_mode = (
            operation_admission_pb2.ADMISSION_MODE_RESOLVE_ONLY
        )
        terminal_response = await admission(terminal_request, timeout=3)
        validation.validate_admission_exchange(
            terminal_request,
            terminal_response,
        )
        if terminal_response.disposition != _RESOLVED_EXISTING:
            raise RuntimeError("terminal record replay did not resolve")
        if provider.dispatches != 1:
            raise RuntimeError("terminal record replay dispatched again")
        statuses = await _verify_canonical_rejections(
            provider,
            admission,
            handshake,
            manifest,
        )

        context = provider.context
        if context is None or not isinstance(
            context.execution_context, MappingProxyType
        ):
            raise RuntimeError("Provider author context is not immutable")

        provider.request_shutdown()
        await asyncio.wait_for(provider_task, timeout=5)
        if await asyncio.to_thread(Path(socket_path).exists):
            raise RuntimeError("Provider socket survived shutdown")
        remaining_descriptors = await asyncio.to_thread(
            lambda: tuple(discovery.glob("*.sfp.json"))
        )
        if remaining_descriptors:
            raise RuntimeError("Provider descriptor survived shutdown")

        lost = await _verify_lost_response_replay(runtime_directory / "lost")
        expiry = await _verify_expiry_and_restart(runtime_directory / "expiry")

        evidence = {
            "installed_artifacts": {
                "stateforge-provider": version("stateforge-provider"),
                "stateforge-protocol": version("stateforge-protocol"),
            },
            "provider_instance_id": handshake.provider_instance_id,
            "endpoint_generation": handshake.endpoint_generation,
            "session_id": handshake.session_id,
            "manifest_revision": manifest.manifest_revision,
            "operation_id": operation_id,
            "request_fingerprint": responses[0].record.request_fingerprint,
            "concurrent_requests": len(responses),
            "accepted_new": accepted_new,
            "resolved_existing": len(responses) - accepted_new,
            "author_dispatches": provider.dispatches,
            "stale_fence_status": stale_status,
            "missing_role_status": role_status,
            "requirement_status": requirement_status,
            "idempotency_conflict_status": conflict_status,
            "immutable_context": True,
            "final_process_state": "stopped",
            "descriptor_removed": True,
            "socket_removed": True,
            **statuses,
            **lost,
            **expiry,
        }
        serialized = json.dumps(evidence, sort_keys=True)
        if payload_marker in serialized:
            raise RuntimeError("secret leaked into scenario evidence")
        return evidence
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
    """Run the focused installed-wheel scenario and write its evidence."""
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
