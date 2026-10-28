"""Real P3 stream and author-facing trigger publication tests."""

import asyncio
import json
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import grpc
import pytest
from google.protobuf.duration_pb2 import Duration
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)
from stateforge_protocol.sfp.manifest.v1 import (
    manifest_pb2,
    manifest_pb2_grpc,
)
from stateforge_protocol.sfp.trigger_publication.v1 import (
    trigger_publication_pb2,
    trigger_publication_pb2_grpc,
)
from stateforge_protocol.sfp.trigger_publication.v1.validation import (
    compute_publication_content_fingerprint,
)

from stateforge_provider import (
    Platform,
    Provider,
    ProviderModel,
    Trigger,
    TriggerPayloadError,
    TriggerPublicationDisposition,
    TriggerPublicationUnavailableError,
    TriggerQueueFullError,
    TriggerRejectionReason,
    trigger,
)


class _DeploymentCompleted(ProviderModel):
    environment: str
    revision: str


class _UnitFailed(ProviderModel):
    unit: str
    result: str


_DEPLOYMENT_COMPLETED = Trigger(
    "example.deploy/completed@1",
    _DeploymentCompleted,
)


class _TriggerProvider(Provider):
    identity = "example.trigger"
    display_name = "Trigger test Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)
    triggers = (_DEPLOYMENT_COMPLETED,)

    def __init__(self, directory: Path) -> None:
        super().__init__(
            discovery_directory=directory,
            state_directory=directory / "state",
        )
        self.failures: asyncio.Queue[_UnitFailed] = asyncio.Queue()

    @trigger("example.systemd/unit.failed@1")
    async def unit_failures(self) -> AsyncIterator[_UnitFailed]:
        while True:
            yield await self.failures.get()


class _FailingSourceProvider(Provider):
    identity = "example.trigger.failure"
    display_name = "Failing trigger source Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.source_failed = asyncio.Event()

    @trigger("example.systemd/source.failed@1")
    async def failures(self) -> AsyncIterator[_UnitFailed]:
        if False:  # pragma: no cover - establishes the generator payload type
            yield _UnitFailed(unit="unused", result="unused")
        self.source_failed.set()
        raise RuntimeError("source-secret-must-not-appear")


@pytest.fixture
def directory() -> Iterator[Path]:
    path = Path(tempfile.mkdtemp(prefix="sfp-r4-", dir="/tmp"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@asynccontextmanager
async def _running(
    provider: Provider,
) -> AsyncIterator[
    tuple[
        bootstrap_pb2_grpc.BootstrapServiceStub,
        manifest_pb2_grpc.ManifestServiceStub,
        trigger_publication_pb2_grpc.TriggerPublicationServiceStub,
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
            f"unix:{descriptor['transport']['socket_path']}"
        )
        yield (
            bootstrap_pb2_grpc.BootstrapServiceStub(channel),
            manifest_pb2_grpc.ManifestServiceStub(channel),
            trigger_publication_pb2_grpc.TriggerPublicationServiceStub(
                channel
            ),
            descriptor,
        )
    finally:
        provider.request_shutdown()
        await asyncio.wait_for(task, 3)
        if channel is not None:
            await channel.close()


async def _session(
    bootstrap: bootstrap_pb2_grpc.BootstrapServiceStub,
    manifest: manifest_pb2_grpc.ManifestServiceStub,
    descriptor: dict[str, object],
) -> tuple[
    bootstrap_pb2.HandshakeResponse,
    manifest_pb2.GetManifestResponse,
]:
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


async def _stream(
    stub: trigger_publication_pb2_grpc.TriggerPublicationServiceStub,
    handshake: bootstrap_pb2.HandshakeResponse,
    snapshot: manifest_pb2.GetManifestResponse,
    *,
    window: int = 8,
    deadline_seconds: float = 3,
) -> grpc.aio.StreamStreamCall[
    trigger_publication_pb2.StreamTriggersRequest,
    trigger_publication_pb2.StreamTriggersResponse,
]:
    call = stub.StreamTriggers(timeout=deadline_seconds)
    await call.write(_open_request(handshake, snapshot, window=window))
    ready = await call.read()
    assert ready.WhichOneof("message") == "ready"
    assert ready.ready.maximum_in_flight_publications == window
    return call


def _open_request(
    handshake: bootstrap_pb2.HandshakeResponse,
    snapshot: manifest_pb2.GetManifestResponse,
    *,
    window: int = 8,
    manifest_revision: str | None = None,
) -> trigger_publication_pb2.StreamTriggersRequest:
    """Construct one canonical or deliberately stale opening request."""
    return trigger_publication_pb2.StreamTriggersRequest(
        open=trigger_publication_pb2.TriggerStreamOpen(
            session_binding=trigger_publication_pb2.TriggerSessionBinding(
                expected_provider_instance_id=handshake.provider_instance_id,
                expected_endpoint_generation=handshake.endpoint_generation,
                expected_session_id=handshake.session_id,
                expected_manifest_revision=(
                    manifest_revision or snapshot.manifest_revision
                ),
            ),
            requested_max_in_flight_publications=window,
        )
    )


async def _acknowledge(
    call: grpc.aio.StreamStreamCall[
        trigger_publication_pb2.StreamTriggersRequest,
        trigger_publication_pb2.StreamTriggersResponse,
    ],
    publication_id: str,
    disposition: int,
) -> None:
    await call.write(
        trigger_publication_pb2.StreamTriggersRequest(
            acknowledgement=trigger_publication_pb2.TriggerAcknowledgement(
                publication_id=publication_id,
                disposition=disposition,
            )
        )
    )


@pytest.mark.asyncio
async def test_callback_publication_returns_receipt_and_terminal_outcome(
    directory: Path,
) -> None:
    provider = _TriggerProvider(directory)
    async with _running(provider) as (bootstrap, manifest, trigger_stub, data):
        handshake, snapshot = await _session(bootstrap, manifest, data)
        assert set(snapshot.manifest.triggers) == {
            "example.deploy/completed@1",
            "example.systemd/unit.failed@1",
        }
        call = await _stream(trigger_stub, handshake, snapshot)
        observed_at = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
        receipt = await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(
                environment="production",
                revision="abc123",
            ),
            observed_at=observed_at,
        )

        response = await call.read()
        publication = response.publication
        assert publication.publication_id == str(receipt.publication_id)
        assert (
            publication.trigger_identifier == _DEPLOYMENT_COMPLETED.identifier
        )
        assert publication.observed_at.ToDatetime(tzinfo=UTC) == observed_at
        assert publication.payload["environment"] == "production"
        await _acknowledge(
            call,
            publication.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )
        outcome = await asyncio.wait_for(receipt.outcome(), 1)
        assert (
            outcome.disposition is TriggerPublicationDisposition.ACCEPTED_NEW
        )
        assert outcome.publication_id == receipt.publication_id
        await call.done_writing()


@pytest.mark.asyncio
async def test_decorated_source_publishes_without_manual_runtime_code(
    directory: Path,
) -> None:
    provider = _TriggerProvider(directory)
    async with _running(provider) as (bootstrap, manifest, trigger_stub, data):
        handshake, snapshot = await _session(bootstrap, manifest, data)
        call = await _stream(trigger_stub, handshake, snapshot)

        await provider.failures.put(
            _UnitFailed(unit="nginx.service", result="exit-code")
        )
        publication = (await call.read()).publication
        assert (
            publication.trigger_identifier == "example.systemd/unit.failed@1"
        )
        assert publication.payload["unit"] == "nginx.service"
        await _acknowledge(
            call,
            publication.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )

        sentinel_receipt = await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(
                environment="verification",
                revision="queue-drained",
            ),
        )
        sentinel = (await call.read()).publication
        assert sentinel.publication_id == str(sentinel_receipt.publication_id)
        assert sentinel.publication_id != publication.publication_id
        await _acknowledge(
            call,
            sentinel.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )
        assert (
            await asyncio.wait_for(sentinel_receipt.outcome(), 1)
        ).disposition is TriggerPublicationDisposition.ACCEPTED_NEW
        await call.done_writing()


@pytest.mark.asyncio
async def test_retryable_rejection_replays_exact_immutable_publication(
    directory: Path,
) -> None:
    provider = _TriggerProvider(directory)
    configuration = replace(
        provider._configuration,
        trigger_retry_base_seconds=0.001,
        trigger_retry_max_seconds=0.01,
    )
    provider._configuration = configuration
    provider._server.configuration = configuration
    async with _running(provider) as (bootstrap, manifest, trigger_stub, data):
        handshake, snapshot = await _session(bootstrap, manifest, data)
        call = await _stream(trigger_stub, handshake, snapshot)
        receipt = await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(environment="test", revision="def456"),
        )
        first = (await call.read()).publication
        retry_after = Duration()
        retry_after.FromMilliseconds(1)
        await call.write(
            trigger_publication_pb2.StreamTriggersRequest(
                acknowledgement=(
                    trigger_publication_pb2.TriggerAcknowledgement(
                        publication_id=first.publication_id,
                        disposition=(
                            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_REJECTED
                        ),
                        rejection=trigger_publication_pb2.TriggerRejection(
                            reason=(
                                trigger_publication_pb2.TRIGGER_REJECTION_REASON_AGENT_CAPACITY_EXHAUSTED
                            ),
                            retryable=True,
                            retry_after=retry_after,
                            explanation="Capacity is temporarily exhausted",
                        ),
                    )
                )
            )
        )
        second = (await call.read()).publication
        assert second == first
        assert compute_publication_content_fingerprint(second) == (
            compute_publication_content_fingerprint(first)
        )
        await _acknowledge(
            call,
            second.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_DUPLICATE,
        )
        outcome = await asyncio.wait_for(receipt.outcome(), 1)
        assert (
            outcome.disposition
            is TriggerPublicationDisposition.ACCEPTED_DUPLICATE
        )
        await call.done_writing()


@pytest.mark.asyncio
async def test_unacknowledged_publication_replays_after_fresh_session(
    directory: Path,
) -> None:
    provider = _TriggerProvider(directory)
    configuration = replace(
        provider._configuration,
        trigger_retry_base_seconds=1,
        trigger_retry_max_seconds=1,
    )
    provider._configuration = configuration
    provider._server.configuration = configuration
    async with _running(provider) as (bootstrap, manifest, trigger_stub, data):
        first_session, first_snapshot = await _session(
            bootstrap, manifest, data
        )
        first_call = await _stream(
            trigger_stub,
            first_session,
            first_snapshot,
        )
        receipt = await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(environment="staging", revision="ghi789"),
        )
        first = (await first_call.read()).publication
        first_call.cancel()
        await asyncio.sleep(0)

        second_session, second_snapshot = await _session(
            bootstrap, manifest, data
        )
        second_call = await _stream(
            trigger_stub,
            second_session,
            second_snapshot,
        )
        pending_replay = asyncio.create_task(second_call.read())
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(pending_replay), 0.05)
        second = (await asyncio.wait_for(pending_replay, 2)).publication
        assert second == first
        await _acknowledge(
            second_call,
            second.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )
        assert (
            await asyncio.wait_for(receipt.outcome(), 1)
        ).disposition is TriggerPublicationDisposition.ACCEPTED_NEW
        await second_call.done_writing()


@pytest.mark.asyncio
async def test_deadline_releases_unacknowledged_publication_for_replay(
    directory: Path,
) -> None:
    provider = _TriggerProvider(directory)
    async with _running(provider) as (bootstrap, manifest, trigger_stub, data):
        first_session, first_snapshot = await _session(
            bootstrap, manifest, data
        )
        expiring = await _stream(
            trigger_stub,
            first_session,
            first_snapshot,
            window=1,
            deadline_seconds=0.05,
        )
        receipt = await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(environment="test", revision="deadline"),
        )
        first = (await expiring.read()).publication
        await asyncio.sleep(0.06)
        with pytest.raises(grpc.aio.AioRpcError) as deadline_error:
            await expiring.read()
        assert deadline_error.value.code() is grpc.StatusCode.DEADLINE_EXCEEDED

        replacement_session, replacement_snapshot = await _session(
            bootstrap, manifest, data
        )
        replacement = await _stream(
            trigger_stub,
            replacement_session,
            replacement_snapshot,
        )
        replayed = (await replacement.read()).publication
        assert replayed == first
        await _acknowledge(
            replacement,
            replayed.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )
        assert (
            await asyncio.wait_for(receipt.outcome(), 1)
        ).disposition is TriggerPublicationDisposition.ACCEPTED_NEW
        await replacement.done_writing()


@pytest.mark.asyncio
async def test_stream_rejects_stale_binding_and_duplicate_session(
    directory: Path,
) -> None:
    provider = _TriggerProvider(directory)
    async with _running(provider) as (bootstrap, manifest, trigger_stub, data):
        handshake, snapshot = await _session(bootstrap, manifest, data)

        stale = trigger_stub.StreamTriggers(timeout=3)
        await stale.write(
            _open_request(
                handshake,
                snapshot,
                manifest_revision="sha256:" + ("0" * 64),
            )
        )
        with pytest.raises(grpc.aio.AioRpcError) as stale_error:
            await stale.read()
        assert stale_error.value.code() is grpc.StatusCode.FAILED_PRECONDITION

        active = await _stream(trigger_stub, handshake, snapshot)
        duplicate = trigger_stub.StreamTriggers(timeout=3)
        await duplicate.write(_open_request(handshake, snapshot))
        with pytest.raises(grpc.aio.AioRpcError) as duplicate_error:
            await duplicate.read()
        assert duplicate_error.value.code() is grpc.StatusCode.ALREADY_EXISTS
        await active.done_writing()


@pytest.mark.asyncio
async def test_evicted_session_cannot_acknowledge_pending_publication(
    directory: Path,
) -> None:
    provider = _TriggerProvider(directory)
    limits = replace(provider._configuration.limits, max_sessions=1)
    configuration = replace(
        provider._configuration,
        limits=limits,
        trigger_retry_base_seconds=0.001,
        trigger_retry_max_seconds=0.001,
    )
    provider._configuration = configuration
    provider._server.configuration = configuration
    async with _running(provider) as (bootstrap, manifest, trigger_stub, data):
        first_session, first_snapshot = await _session(
            bootstrap,
            manifest,
            data,
        )
        stale_call = await _stream(
            trigger_stub,
            first_session,
            first_snapshot,
        )
        receipt = await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(environment="test", revision="stale-ack"),
        )
        publication = (await stale_call.read()).publication

        current_session, current_snapshot = await _session(
            bootstrap,
            manifest,
            data,
        )
        await _acknowledge(
            stale_call,
            publication.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )
        with pytest.raises(grpc.aio.AioRpcError) as stale_error:
            await stale_call.read()
        assert stale_error.value.code() is grpc.StatusCode.FAILED_PRECONDITION

        pending_outcome = asyncio.create_task(receipt.outcome())
        await asyncio.sleep(0)
        assert not pending_outcome.done()
        current_call = await _stream(
            trigger_stub,
            current_session,
            current_snapshot,
        )
        replayed = (await current_call.read()).publication
        assert replayed == publication
        await _acknowledge(
            current_call,
            replayed.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )
        assert (
            await asyncio.wait_for(pending_outcome, 1)
        ).disposition is TriggerPublicationDisposition.ACCEPTED_NEW
        await current_call.done_writing()


@pytest.mark.asyncio
async def test_stream_rejects_invalid_framing_and_unknown_acknowledgement(
    directory: Path,
) -> None:
    provider = _TriggerProvider(directory)
    async with _running(provider) as (bootstrap, manifest, trigger_stub, data):
        handshake, snapshot = await _session(bootstrap, manifest, data)

        acknowledgement_first = trigger_stub.StreamTriggers(timeout=3)
        await _acknowledge(
            acknowledgement_first,
            str(uuid4()),
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )
        with pytest.raises(grpc.aio.AioRpcError) as framing_error:
            await acknowledgement_first.read()
        assert framing_error.value.code() is grpc.StatusCode.INVALID_ARGUMENT

        call = await _stream(trigger_stub, handshake, snapshot)
        await _acknowledge(
            call,
            str(uuid4()),
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )
        with pytest.raises(grpc.aio.AioRpcError) as acknowledgement_error:
            await call.read()
        assert (
            acknowledgement_error.value.code()
            is grpc.StatusCode.INVALID_ARGUMENT
        )


@pytest.mark.asyncio
async def test_receive_window_blocks_second_publication_until_acknowledgement(
    directory: Path,
) -> None:
    provider = _TriggerProvider(directory)
    async with _running(provider) as (bootstrap, manifest, trigger_stub, data):
        handshake, snapshot = await _session(bootstrap, manifest, data)
        call = await _stream(trigger_stub, handshake, snapshot, window=1)
        first_receipt = await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(environment="test", revision="one"),
        )
        second_receipt = await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(environment="test", revision="two"),
        )

        first = (await call.read()).publication
        pending_second = asyncio.create_task(call.read())
        await asyncio.sleep(0.02)
        assert not pending_second.done()

        await _acknowledge(
            call,
            first.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )
        second = (await asyncio.wait_for(pending_second, 1)).publication
        assert second.publication_id != first.publication_id
        await _acknowledge(
            call,
            second.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )
        assert (
            await asyncio.wait_for(first_receipt.outcome(), 1)
        ).disposition is TriggerPublicationDisposition.ACCEPTED_NEW
        assert (
            await asyncio.wait_for(second_receipt.outcome(), 1)
        ).disposition is TriggerPublicationDisposition.ACCEPTED_NEW
        await call.done_writing()


@pytest.mark.parametrize(
    ("wire_reason", "public_reason"),
    [
        (
            trigger_publication_pb2.TRIGGER_REJECTION_REASON_PAYLOAD_SCHEMA_VIOLATION,
            TriggerRejectionReason.PAYLOAD_SCHEMA_VIOLATION,
        ),
        (
            trigger_publication_pb2.TRIGGER_REJECTION_REASON_IDEMPOTENCY_CONFLICT,
            TriggerRejectionReason.IDEMPOTENCY_CONFLICT,
        ),
    ],
)
@pytest.mark.asyncio
async def test_nonretryable_rejection_resolves_sanitized_receipt(
    directory: Path,
    wire_reason: int,
    public_reason: TriggerRejectionReason,
) -> None:
    provider = _TriggerProvider(directory)
    async with _running(provider) as (bootstrap, manifest, trigger_stub, data):
        handshake, snapshot = await _session(bootstrap, manifest, data)
        call = await _stream(trigger_stub, handshake, snapshot)
        receipt = await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(environment="test", revision="invalid"),
        )
        publication = (await call.read()).publication
        await call.write(
            trigger_publication_pb2.StreamTriggersRequest(
                acknowledgement=trigger_publication_pb2.TriggerAcknowledgement(
                    publication_id=publication.publication_id,
                    disposition=(
                        trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_REJECTED
                    ),
                    rejection=trigger_publication_pb2.TriggerRejection(
                        reason=wire_reason,
                        retryable=False,
                        explanation="Publication rejected by policy",
                    ),
                )
            )
        )
        outcome = await asyncio.wait_for(receipt.outcome(), 1)
        assert outcome.disposition is TriggerPublicationDisposition.REJECTED
        assert outcome.rejection is not None
        assert outcome.rejection.reason is public_reason
        assert not outcome.rejection.retryable
        await call.done_writing()


@pytest.mark.asyncio
async def test_shutdown_fails_receipt_without_persisting_or_logging_payload(
    directory: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _TriggerProvider(directory)
    sensitive_value = "payload-value-must-not-appear"
    async with _running(provider):
        receipt = await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(
                environment="test",
                revision=sensitive_value,
            ),
        )

    with pytest.raises(TriggerPublicationUnavailableError):
        await receipt.outcome()
    assert sensitive_value not in caplog.text
    assert not any(
        "trigger" in path.name for path in (directory / "state").rglob("*")
    )


@pytest.mark.asyncio
async def test_source_failure_log_omits_exception_and_payload(
    directory: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _FailingSourceProvider(
        discovery_directory=directory,
        state_directory=directory / "state",
    )
    async with _running(provider):
        await asyncio.wait_for(provider.source_failed.wait(), timeout=1)
        await asyncio.sleep(0)

    assert "source-secret-must-not-appear" not in caplog.text


@pytest.mark.asyncio
async def test_public_api_rejects_wrong_payload_and_queue_overflow(
    directory: Path,
) -> None:
    provider = _TriggerProvider(directory)
    limits = replace(
        provider._configuration.limits,
        max_pending_trigger_publications=1,
    )
    configuration = replace(provider._configuration, limits=limits)
    provider._configuration = configuration
    provider._server.configuration = configuration
    async with _running(provider):
        with pytest.raises(TriggerPayloadError):
            await provider.publish_trigger(
                _DEPLOYMENT_COMPLETED,
                _UnitFailed(unit="nginx.service", result="exit-code"),
            )
        await provider.publish_trigger(
            _DEPLOYMENT_COMPLETED,
            _DeploymentCompleted(environment="test", revision="one"),
        )
        with pytest.raises(TriggerQueueFullError):
            await provider.publish_trigger(
                _DEPLOYMENT_COMPLETED,
                _DeploymentCompleted(environment="test", revision="two"),
            )
