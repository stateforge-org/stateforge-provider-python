"""Real-socket evidence for Provider Operation Admission and idempotency."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

import grpc
import pytest
from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from grpc_status import rpc_status
from jsonschema import Draft202012Validator
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
    contract as admission_contract,
)
from stateforge_protocol.sfp.operation_admission.v1 import (
    operation_admission_pb2,
    operation_admission_pb2_grpc,
)
from stateforge_protocol.sfp.operation_admission.v1 import (
    validation as admission_validation,
)

from stateforge_provider import (
    HealthStatus,
    OperationContext,
    Platform,
    Provider,
    ProviderModel,
    RequirementCheckResult,
    operation,
    requirement_check,
)
from stateforge_provider._services.manifest.declaration import (
    ManifestDeclaration,
)
from stateforge_provider._services.operation_admission.runtime import (
    AdmissionRegistryError,
    AdmissionRegistryFailure,
    OperationAdmissionRuntime,
)

_PRECONDITION_FAILED = operation_admission_pb2.AdmissionErrorReason.Value(
    "ADMISSION_ERROR_REASON_OPERATION_PRECONDITION_FAILED"
)
_DEADLINE_EXPIRED = operation_admission_pb2.AdmissionErrorReason.Value(
    "ADMISSION_ERROR_REASON_OPERATION_DEADLINE_EXPIRED"
)


class _Input(ProviderModel):
    """Describe an operation request with one secret-bearing field."""

    value: int
    secret: str = Field(json_schema_extra={"writeOnly": True})


class _Output(ProviderModel):
    accepted: bool


class _AdmissionProvider(Provider):
    identity = "example.admission"
    display_name = "Admission test Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(self, directory: Path) -> None:
        super().__init__(
            discovery_directory=directory,
            state_directory=directory / "state",
        )
        self.status = HealthStatus.healthy()
        self.requirement = RequirementCheckResult.satisfied()
        self.pause_requirement = False
        self.requirement_started = asyncio.Event()
        self.requirement_release = asyncio.Event()
        self.calls = 0
        self.contexts: list[OperationContext] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.fail_dispatch = False

    async def health(self) -> HealthStatus:
        return self.status

    @requirement_check("runtime.ready", "Runtime is ready")
    async def ready(self) -> RequirementCheckResult:
        if self.pause_requirement:
            self.requirement_started.set()
            await self.requirement_release.wait()
        return self.requirement

    @operation(
        "example.admission/run@1",
        requires=("runtime.ready",),
        implements=("example.operation.v1.audited",),
    )
    async def run_operation(
        self,
        request: _Input,
        context: OperationContext,
    ) -> _Output:
        self.calls += 1
        self.contexts.append(context)
        self.started.set()
        if self.fail_dispatch:
            raise RuntimeError(f"secret author failure: {request.secret}")
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return _Output(accepted=request.value > 0)

    @operation("example.admission/legacy@1")
    async def legacy(self, request: _Input) -> _Output:
        return _Output(accepted=request.value > 0)


@pytest.fixture
def endpoint_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="sfp-r5-", dir="/tmp"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


@asynccontextmanager
async def _running(
    provider: _AdmissionProvider,
) -> AsyncIterator[
    tuple[
        operation_admission_pb2_grpc.OperationAdmissionServiceStub,
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
                    admission_contract.MAX_RESPONSE_BYTES,
                ),
                (
                    "grpc.max_send_message_length",
                    admission_contract.MAX_REQUEST_BYTES + 1,
                ),
            ),
        )
        await asyncio.wait_for(channel.channel_ready(), timeout=2)
        yield (
            operation_admission_pb2_grpc.OperationAdmissionServiceStub(
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


def _request(
    handshake,
    snapshot,
    *,
    operation_id: str | None = None,
    operation_identifier: str = "example.admission/run@1",
    payload: dict[str, object] | None = None,
    deadline: datetime | None = None,
    roles: tuple[str, ...] = ("example.operation.v1.audited",),
    mode: int = operation_admission_pb2.ADMISSION_MODE_ADMIT_OR_RESOLVE,
):
    payload_message = Struct()
    ParseDict(payload or {"value": 1, "secret": "hidden"}, payload_message)
    context = Struct()
    ParseDict({"authority": "policy-1", "nested": {"items": [1, 2]}}, context)
    return operation_admission_pb2.StartOperationRequest(
        session_binding=operation_admission_pb2.OperationSessionBinding(
            expected_provider_instance_id=handshake.provider_instance_id,
            expected_endpoint_generation=handshake.endpoint_generation,
            expected_session_id=handshake.session_id,
        ),
        invocation=operation_admission_pb2.OperationInvocation(
            operation_id=operation_id or str(uuid4()),
            operation_identifier=operation_identifier,
            payload=payload_message,
            execution_deadline=_timestamp(
                deadline or datetime.now(UTC) + timedelta(minutes=5)
            ),
            contract=operation_admission_pb2.OperationContractContext(
                manifest_revision=snapshot.manifest_revision,
                required_implementation_roles=roles,
            ),
            execution_context=context,
        ),
        admission_mode=mode,
    )


def _detail(error: grpc.aio.AioRpcError):
    status = rpc_status.from_call(error)
    assert status is not None
    packed = status.details[0]
    detail = operation_admission_pb2.OperationAdmissionErrorDetail()
    assert packed.Unpack(detail)
    admission_validation.validate_admission_rejection(
        detail, grpc_status=error.code().name
    )
    return detail


@pytest.mark.asyncio
async def test_concurrent_identical_requests_dispatch_once_over_real_socket(
    endpoint_directory: Path,
) -> None:
    provider = _AdmissionProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        request = _request(handshake, snapshot)
        responses = await asyncio.gather(
            *(admission.StartOperation(request, timeout=2) for _ in range(20))
        )
        await asyncio.wait_for(provider.started.wait(), timeout=1)

        assert provider.calls == 1
        assert (
            sum(
                item.disposition
                == operation_admission_pb2.ADMISSION_DISPOSITION_ACCEPTED_NEW
                for item in responses
            )
            == 1
        )
        assert {item.record.request_fingerprint for item in responses} == {
            admission_validation.compute_request_fingerprint(
                request.invocation
            )
        }
        for response in responses:
            admission_validation.validate_admission_exchange(request, response)

        context = provider.contexts[0]
        assert str(context.operation_id) == request.invocation.operation_id
        assert isinstance(context.execution_context, MappingProxyType)
        with pytest.raises(TypeError):
            context.execution_context["authority"] = "changed"  # type: ignore[index]
        nested = context.execution_context["nested"]
        assert isinstance(nested, MappingProxyType)

        provider.release.set()


@pytest.mark.asyncio
async def test_existing_record_resolves_before_deadline_and_readiness_checks(
    endpoint_directory: Path,
) -> None:
    provider = _AdmissionProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        request = _request(
            handshake,
            snapshot,
            deadline=datetime.now(UTC) + timedelta(milliseconds=50),
        )
        accepted = await admission.StartOperation(request, timeout=2)
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        await asyncio.sleep(0.06)
        provider.status = HealthStatus.maintenance()
        await provider.refresh_health()
        resolved = await admission.StartOperation(request, timeout=2)

        assert accepted.disposition == (
            operation_admission_pb2.ADMISSION_DISPOSITION_ACCEPTED_NEW
        )
        assert resolved.disposition == (
            operation_admission_pb2.ADMISSION_DISPOSITION_RESOLVED_EXISTING
        )
        assert provider.calls == 1
        provider.release.set()


@pytest.mark.asyncio
async def test_deadline_is_rechecked_after_requirement_evaluation(
    endpoint_directory: Path,
) -> None:
    provider = _AdmissionProvider(endpoint_directory)
    provider.pause_requirement = True
    async with _running(provider) as (
        admission,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        request = _request(
            handshake,
            snapshot,
            deadline=datetime.now(UTC) + timedelta(milliseconds=50),
        )
        pending = asyncio.ensure_future(admission.StartOperation(request))
        await asyncio.wait_for(provider.requirement_started.wait(), timeout=1)
        await asyncio.sleep(0.06)
        provider.requirement_release.set()

        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await pending
        assert captured.value.code() is grpc.StatusCode.DEADLINE_EXCEEDED
        assert _detail(captured.value).reason == _DEADLINE_EXPIRED
        assert provider.calls == 0


@pytest.mark.asyncio
async def test_changed_content_conflicts_with_structured_safe_error(
    endpoint_directory: Path,
) -> None:
    provider = _AdmissionProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        operation_id = str(uuid4())
        original = _request(handshake, snapshot, operation_id=operation_id)
        await admission.StartOperation(original, timeout=2)
        changed = _request(
            handshake,
            snapshot,
            operation_id=operation_id,
            payload={"value": 2, "secret": "must-not-leak"},
        )
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await admission.StartOperation(changed, timeout=2)

        assert captured.value.code() is grpc.StatusCode.ALREADY_EXISTS
        detail = _detail(captured.value)
        assert detail.reason == (
            operation_admission_pb2.ADMISSION_ERROR_REASON_IDEMPOTENCY_CONFLICT
        )
        assert detail.operation_id == operation_id
        assert "must-not-leak" not in captured.value.details()
        provider.release.set()


@pytest.mark.asyncio
async def test_stale_session_is_rejected_before_declaration_lookup(
    endpoint_directory: Path,
) -> None:
    provider = _AdmissionProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        request = _request(
            handshake,
            snapshot,
            operation_identifier="example.admission/missing@1",
        )
        request.session_binding.expected_session_id = "stale-session"

        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await admission.StartOperation(request, timeout=2)

        assert captured.value.code() is grpc.StatusCode.FAILED_PRECONDITION
        assert _detail(captured.value).reason == _PRECONDITION_FAILED
        assert provider.calls == 0


@pytest.mark.parametrize(
    ("change", "expected_code", "expected_reason"),
    [
        (
            "missing",
            grpc.StatusCode.UNIMPLEMENTED,
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_NOT_DECLARED,
        ),
        (
            "payload",
            grpc.StatusCode.INVALID_ARGUMENT,
            operation_admission_pb2.ADMISSION_ERROR_REASON_INVALID_OPERATION_REQUEST,
        ),
        (
            "role",
            grpc.StatusCode.FAILED_PRECONDITION,
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_INCOMPATIBLE,
        ),
        (
            "session",
            grpc.StatusCode.FAILED_PRECONDITION,
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_PRECONDITION_FAILED,
        ),
        (
            "deadline",
            grpc.StatusCode.DEADLINE_EXCEEDED,
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_DEADLINE_EXPIRED,
        ),
        (
            "resolve",
            grpc.StatusCode.FAILED_PRECONDITION,
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_RECORD_UNAVAILABLE,
        ),
    ],
)
@pytest.mark.asyncio
async def test_rejects_before_creating_a_record(
    endpoint_directory: Path,
    change: str,
    expected_code: grpc.StatusCode,
    expected_reason,
) -> None:
    provider = _AdmissionProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        request = _request(handshake, snapshot)
        if change == "missing":
            request.invocation.operation_identifier = (
                "example.admission/missing@1"
            )
        elif change == "payload":
            request.invocation.payload.Clear()
            request.invocation.payload.update(
                {"value": "wrong", "secret": "hidden"}
            )
        elif change == "role":
            request.invocation.contract.required_implementation_roles[:] = [
                "example.operation.v1.missing"
            ]
        elif change == "session":
            request.session_binding.expected_session_id = "stale-session"
        elif change == "deadline":
            request.invocation.execution_deadline.CopyFrom(
                _timestamp(datetime.now(UTC) - timedelta(seconds=1))
            )
        else:
            request.admission_mode = (
                operation_admission_pb2.ADMISSION_MODE_RESOLVE_ONLY
            )
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await admission.StartOperation(request, timeout=2)

        assert captured.value.code() is expected_code
        assert _detail(captured.value).reason == expected_reason
        assert provider.calls == 0


@pytest.mark.parametrize("outcome", ["unmet", "incompatible"])
@pytest.mark.asyncio
async def test_revalidates_current_requirements_before_admission(
    endpoint_directory: Path,
    outcome: str,
) -> None:
    provider = _AdmissionProvider(endpoint_directory)
    provider.requirement = (
        RequirementCheckResult.unsatisfied("not ready")
        if outcome == "unmet"
        else RequirementCheckResult.incompatible("not supported")
    )
    async with _running(provider) as (
        admission,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        with pytest.raises(grpc.aio.AioRpcError) as captured:
            await admission.StartOperation(
                _request(handshake, snapshot), timeout=2
            )

        assert captured.value.code() is grpc.StatusCode.FAILED_PRECONDITION
        assert _detail(captured.value).reason == (
            operation_admission_pb2.ADMISSION_ERROR_REASON_OPERATION_INCOMPATIBLE
            if outcome == "incompatible"
            else _PRECONDITION_FAILED
        )
        assert provider.calls == 0


@pytest.mark.asyncio
async def test_shutdown_cancels_admitted_author_dispatch(
    endpoint_directory: Path,
) -> None:
    provider = _AdmissionProvider(endpoint_directory)
    async with _running(provider) as (
        admission,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        await admission.StartOperation(
            _request(handshake, snapshot), timeout=2
        )
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        provider.request_shutdown()
        await asyncio.wait_for(provider.cancelled.wait(), timeout=1)


@pytest.mark.asyncio
async def test_dispatch_failure_is_local_and_record_still_resolves(
    endpoint_directory: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _AdmissionProvider(endpoint_directory)
    provider.fail_dispatch = True
    async with _running(provider) as (
        admission,
        bootstrap,
        manifest,
        descriptor,
    ):
        handshake, snapshot = await _session(bootstrap, manifest, descriptor)
        request = _request(
            handshake,
            snapshot,
            payload={"value": 1, "secret": "private-value"},
        )
        with caplog.at_level(logging.ERROR):
            accepted = await admission.StartOperation(request, timeout=2)
            await asyncio.wait_for(provider.started.wait(), timeout=1)
            await asyncio.sleep(0)
            resolved = await admission.StartOperation(request, timeout=2)

        assert accepted.disposition == (
            operation_admission_pb2.ADMISSION_DISPOSITION_ACCEPTED_NEW
        )
        assert resolved.disposition == (
            operation_admission_pb2.ADMISSION_DISPOSITION_RESOLVED_EXISTING
        )
        assert provider.calls == 1
        assert "private-value" not in caplog.text


@pytest.mark.asyncio
async def test_runtime_retains_expiry_tombstone_and_bounds_capacity() -> None:
    first_release = asyncio.Event()

    async def blocked(_context: OperationContext) -> ProviderModel:
        await first_release.wait()
        return _Output(accepted=True)

    result_validator = Draft202012Validator(
        _Output.model_json_schema(mode="serialization")
    )

    def admit(
        runtime: OperationAdmissionRuntime,
        operation_id: str,
        fingerprint: str,
    ):
        return runtime.admit(
            operation_id=operation_id,
            fingerprint=fingerprint,
            endpoint_generation=1,
            operation_identifier="example.admission/run@1",
            manifest_revision="sha256:" + ("a" * 64),
            result_model=_Output,
            result_validator=result_validator,
            cancellable=False,
            progress_policy=None,
            execution_deadline=datetime.now(UTC) + timedelta(minutes=1),
            execution_context={},
            dispatch=blocked,
        )

    runtime = OperationAdmissionRuntime(
        maximum_records=1,
        maximum_dispatches=1,
        record_retention_seconds=0.01,
        tombstone_retention_seconds=0.01,
    )
    first = admit(
        runtime,
        str(uuid4()),
        "sha256:" + ("1" * 64),
    )
    with pytest.raises(AdmissionRegistryError) as capacity:
        admit(
            runtime,
            str(uuid4()),
            "sha256:" + ("2" * 64),
        )
    assert capacity.value.failure is AdmissionRegistryFailure.CAPACITY

    first_release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    await asyncio.sleep(0.02)
    with pytest.raises(AdmissionRegistryError) as expired:
        runtime.lookup(
            first.record.operation_id,
            first.record.request_fingerprint,
        )
    assert expired.value.failure is AdmissionRegistryFailure.EXPIRED

    second_operation_id = str(uuid4())
    second_fingerprint = "sha256:" + ("2" * 64)
    with pytest.raises(AdmissionRegistryError) as tombstone_capacity:
        admit(
            runtime,
            second_operation_id,
            second_fingerprint,
        )
    assert (
        tombstone_capacity.value.failure is AdmissionRegistryFailure.CAPACITY
    )

    await asyncio.sleep(0.02)
    admitted = admit(
        runtime,
        second_operation_id,
        second_fingerprint,
    )
    assert admitted.accepted_new
    await runtime.close()


def test_public_context_and_legacy_handler_are_both_discoverable() -> None:
    declaration = ManifestDeclaration.discover(_AdmissionProvider)
    operations = {
        item.identifier: item for item in declaration.operation_declarations
    }
    assert operations["example.admission/run@1"].accepts_context
    assert not operations["example.admission/legacy@1"].accepts_context
