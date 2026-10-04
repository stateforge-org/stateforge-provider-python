"""Real multiplexed Unix-socket manifest exchange and lifecycle tests."""

import asyncio
import json
import shutil
import tempfile
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import grpc
import pytest
from google.protobuf.message import DecodeError
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)
from stateforge_protocol.sfp.manifest.v1 import manifest_pb2, manifest_pb2_grpc

from stateforge_rpc import (
    ManifestError,
    Platform,
    Provider,
    ProviderModel,
    operation,
)
from stateforge_rpc._services.manifest.declaration import (
    ManifestDeclaration,
    ManifestSnapshot,
)
from stateforge_rpc._services.manifest.limits import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
)
from stateforge_rpc._services.manifest.service import ManifestService


class _Request(ProviderModel):
    name: str


class _Result(ProviderModel):
    found: bool


class _Provider(Provider):
    identity = "example.manifest"
    display_name = "Manifest test"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(self, directory):
        super().__init__(
            discovery_directory=directory,
            state_directory=directory / "state",
        )
        self.events = []

    async def on_startup(self):
        self.events.append("startup")

    async def on_shutdown(self):
        self.events.append("shutdown")

    @operation("example.manifest/find@1")
    async def find(self, request: _Request) -> _Result:
        self.events.append("operation")
        return _Result(found=bool(request.name))


@pytest.fixture
def directory():
    path = Path(tempfile.mkdtemp(prefix="sfp-r1-", dir="/tmp"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@asynccontextmanager
async def _running(provider):
    task = asyncio.create_task(provider.serve())
    channel = None
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
            manifest_pb2_grpc.ManifestServiceStub(channel),
            bootstrap_pb2_grpc.BootstrapServiceStub(channel),
            descriptor,
        )
    finally:
        provider.request_shutdown()
        await asyncio.wait_for(task, 3)
        if channel is not None:
            await channel.close()


def _configure(provider, **changes):
    configuration = replace(provider._configuration, **changes)
    provider._configuration = configuration
    provider._server.configuration = configuration


async def _handshake(stub, descriptor):
    return await stub.Handshake(
        bootstrap_pb2.HandshakeRequest(
            agent_runtime=bootstrap_pb2.AgentRuntime(
                runtime_id=str(uuid4()), software_version="1.0.0"
            ),
            expected_provider_instance_id=descriptor["provider_instance_id"],
            expected_endpoint_generation=descriptor["endpoint_generation"],
            supported_sfp_versions=[
                bootstrap_pb2.ProtocolVersion(major=1, minor=0)
            ],
        ),
        timeout=2,
    )


def _request(handshake, **overrides):
    return manifest_pb2.GetManifestRequest(
        **{
            "expected_provider_instance_id": handshake.provider_instance_id,
            "expected_endpoint_generation": handshake.endpoint_generation,
            "expected_session_id": handshake.session_id,
            "supported_manifest_schema_versions": [3, 1, 2],
            **overrides,
        }
    )


def _varint(value: int) -> bytes:
    maximum_single_byte_value = 0x7F
    encoded = bytearray()
    while value > maximum_single_byte_value:
        encoded.append((value & maximum_single_byte_value) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _with_serialized_size(message, target_size: int):
    """Pad a protobuf with one preserved unknown field to an exact size."""
    content = message.SerializeToString()
    tag = _varint((2_047 << 3) | 2)
    payload_size = target_size - len(content) - len(tag) - 1
    while True:
        encoded_size = _varint(payload_size)
        adjusted = target_size - len(content) - len(tag) - len(encoded_size)
        if adjusted == payload_size:
            break
        payload_size = adjusted
    assert payload_size >= 0
    result = type(message).FromString(
        content + tag + encoded_size + (b"x" * payload_size)
    )
    assert result.ByteSize() == target_size
    return result


@pytest.mark.asyncio
async def test_manifest_request_exact_limit_and_limit_plus_one(directory):
    async with _running(_Provider(directory)) as (
        manifest,
        bootstrap,
        descriptor,
    ):
        handshake = await _handshake(bootstrap, descriptor)
        exact = _with_serialized_size(
            _request(handshake),
            MAX_REQUEST_BYTES,
        )
        assert (await manifest.GetManifest(exact, timeout=2)).session_id == (
            handshake.session_id
        )

        oversized = _with_serialized_size(
            _request(handshake),
            MAX_REQUEST_BYTES + 1,
        )
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await manifest.GetManifest(oversized, timeout=2)
        assert error.value.code() is grpc.StatusCode.RESOURCE_EXHAUSTED
        assert error.value.details() == "Manifest request limit exceeded"


@pytest.mark.asyncio
async def test_manifest_response_exact_limit_and_limit_plus_one(
    directory,
    monkeypatch,
):
    target_size = MAX_RESPONSE_BYTES
    original = ManifestSnapshot.response

    def sized_response(snapshot, session_id):
        return _with_serialized_size(
            original(snapshot, session_id),
            target_size,
        )

    monkeypatch.setattr(ManifestSnapshot, "response", sized_response)
    async with _running(_Provider(directory)) as (
        manifest,
        bootstrap,
        descriptor,
    ):
        handshake = await _handshake(bootstrap, descriptor)
        response = await manifest.GetManifest(_request(handshake), timeout=2)
        assert response.ByteSize() == MAX_RESPONSE_BYTES

        target_size = MAX_RESPONSE_BYTES + 1
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await manifest.GetManifest(_request(handshake), timeout=2)
        assert error.value.code() is grpc.StatusCode.RESOURCE_EXHAUSTED
        assert error.value.details() == "Manifest response limit exceeded"


@pytest.mark.asyncio
async def test_manifest_is_ready_on_publication_and_binds_each_session(
    directory,
):
    provider = _Provider(directory)
    async with _running(provider) as (manifest, bootstrap, descriptor):
        first = await _handshake(bootstrap, descriptor)
        second = await _handshake(bootstrap, descriptor)
        assert first.session_id != second.session_id
        responses = await asyncio.gather(
            *[
                manifest.GetManifest(_request(session), timeout=2)
                for session in [first, second] * 20
            ]
        )
        assert len({response.manifest_revision for response in responses}) == 1
        assert {response.session_id for response in responses} == {
            first.session_id,
            second.session_id,
        }
        for index, response in enumerate(responses):
            session = (first, second)[index % 2]
            assert (
                response.provider_instance_id == session.provider_instance_id
            )
            assert response.endpoint_generation == session.endpoint_generation
            assert response.session_id == session.session_id
            assert response.manifest_schema_version == 1
            assert response.manifest.provider_identity == provider.identity
            assert len(response.manifest.operations) == 1
        # Author metadata changes cannot alter the published snapshot.
        provider.display_name = "instance mutation"
        original_name = _Provider.display_name
        _Provider.display_name = "class mutation"
        try:
            response = await manifest.GetManifest(_request(first), timeout=2)
            assert response.manifest.display_name == original_name
            assert response.manifest_revision == responses[0].manifest_revision
        finally:
            _Provider.display_name = original_name
        assert provider.events == ["startup"]
    assert provider.events == ["startup", "shutdown"]
    assert not provider._server.socket_path.exists()
    assert not provider._server.descriptor_path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"expected_session_id": ""}, grpc.StatusCode.INVALID_ARGUMENT),
        ({"expected_session_id": "x" * 256}, grpc.StatusCode.INVALID_ARGUMENT),
        (
            {"expected_session_id": "unknown"},
            grpc.StatusCode.FAILED_PRECONDITION,
        ),
        (
            {"expected_provider_instance_id": ""},
            grpc.StatusCode.INVALID_ARGUMENT,
        ),
        (
            {"expected_provider_instance_id": "wrong"},
            grpc.StatusCode.INVALID_ARGUMENT,
        ),
        (
            {"expected_provider_instance_id": str(uuid4())},
            grpc.StatusCode.FAILED_PRECONDITION,
        ),
        (
            {"expected_endpoint_generation": 0},
            grpc.StatusCode.INVALID_ARGUMENT,
        ),
        (
            {"expected_endpoint_generation": 100},
            grpc.StatusCode.FAILED_PRECONDITION,
        ),
        (
            {"supported_manifest_schema_versions": []},
            grpc.StatusCode.INVALID_ARGUMENT,
        ),
        (
            {"supported_manifest_schema_versions": [0]},
            grpc.StatusCode.INVALID_ARGUMENT,
        ),
        (
            {"supported_manifest_schema_versions": [1, 1]},
            grpc.StatusCode.INVALID_ARGUMENT,
        ),
        (
            {"supported_manifest_schema_versions": list(range(1, 34))},
            grpc.StatusCode.INVALID_ARGUMENT,
        ),
        (
            {"supported_manifest_schema_versions": [2, 3]},
            grpc.StatusCode.UNIMPLEMENTED,
        ),
        (
            {
                "expected_session_id": "unknown",
                "supported_manifest_schema_versions": [2],
            },
            grpc.StatusCode.FAILED_PRECONDITION,
        ),
        (
            {
                "expected_session_id": "unknown",
                "supported_manifest_schema_versions": [0],
            },
            grpc.StatusCode.INVALID_ARGUMENT,
        ),
        (
            {"expected_session_id": "x" * MAX_REQUEST_BYTES},
            grpc.StatusCode.RESOURCE_EXHAUSTED,
        ),
    ],
)
async def test_manifest_status_precedence_and_transport_limits(
    directory, overrides, code
):
    async with _running(_Provider(directory)) as (
        manifest,
        bootstrap,
        descriptor,
    ):
        handshake = await _handshake(bootstrap, descriptor)
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await manifest.GetManifest(
                _request(handshake, **overrides), timeout=2
            )
        assert error.value.code() == code
        if code is grpc.StatusCode.RESOURCE_EXHAUSTED:
            assert error.value.details() == "Manifest request limit exceeded"


@pytest.mark.asyncio
async def test_an_endpoint_without_handshake_is_not_a_session(directory):
    async with _running(_Provider(directory)) as (manifest, _, descriptor):
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await manifest.GetManifest(
                manifest_pb2.GetManifestRequest(
                    expected_provider_instance_id=descriptor[
                        "provider_instance_id"
                    ],
                    expected_endpoint_generation=descriptor[
                        "endpoint_generation"
                    ],
                    expected_session_id="not-negotiated",
                    supported_manifest_schema_versions=[1],
                ),
                timeout=2,
            )
        assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION


@pytest.mark.asyncio
async def test_bounded_sessions_invalidate_oldest_and_rehandshake_recovers(
    directory,
):
    provider = _Provider(directory)
    limits = replace(provider._configuration.limits, max_sessions=2)
    _configure(provider, limits=limits)
    async with _running(provider) as (
        manifest,
        bootstrap,
        descriptor,
    ):
        first = await _handshake(bootstrap, descriptor)
        second = await _handshake(bootstrap, descriptor)
        latest = await _handshake(bootstrap, descriptor)
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await manifest.GetManifest(_request(first), timeout=2)
        assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION
        for session in (second, latest):
            assert (
                await manifest.GetManifest(_request(session), timeout=2)
            ).session_id == session.session_id


@pytest.mark.asyncio
async def test_restart_retains_revision_and_rejects_old_generation_session(
    directory,
):
    async with _running(_Provider(directory)) as (
        manifest,
        bootstrap,
        descriptor,
    ):
        old_session = await _handshake(bootstrap, descriptor)
        original = await manifest.GetManifest(_request(old_session), timeout=2)
    async with _running(_Provider(directory)) as (
        manifest,
        bootstrap,
        descriptor,
    ):
        new_session = await _handshake(bootstrap, descriptor)
        response = await manifest.GetManifest(_request(new_session), timeout=2)
        assert response.manifest_revision == original.manifest_revision
        assert response.endpoint_generation > original.endpoint_generation
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await manifest.GetManifest(
                _request(
                    new_session, expected_session_id=old_session.session_id
                ),
                timeout=2,
            )
        assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_deadline_and_cancellation_stop_work_without_author_calls(
    directory, monkeypatch, cancel
):
    entered, stopped = asyncio.Event(), asyncio.Event()
    release = asyncio.Event()
    original = ManifestService.GetManifest

    async def delayed(service, request, context):
        entered.set()
        try:
            await release.wait()
            return await original(service, request, context)
        finally:
            stopped.set()

    monkeypatch.setattr(ManifestService, "GetManifest", delayed)
    provider = _Provider(directory)
    async with _running(provider) as (manifest, bootstrap, descriptor):
        handshake = await _handshake(bootstrap, descriptor)
        call = manifest.GetManifest(
            _request(handshake), timeout=2 if cancel else 0.05
        )
        await asyncio.wait_for(entered.wait(), 2)
        if cancel:
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
        else:
            with pytest.raises(grpc.aio.AioRpcError) as error:
                await call
            assert error.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
        await asyncio.wait_for(stopped.wait(), 2)
        assert provider.events == ["startup"]
        release.set()
        assert (
            await manifest.GetManifest(_request(handshake), timeout=2)
        ).session_id == handshake.session_id


@pytest.mark.asyncio
async def test_corrupt_snapshot_returns_sanitized_internal(
    directory, monkeypatch
):
    def broken(snapshot, session_id):
        raise DecodeError("sensitive-canary")

    async with _running(_Provider(directory)) as (
        manifest,
        bootstrap,
        descriptor,
    ):
        handshake = await _handshake(bootstrap, descriptor)
        monkeypatch.setattr(ManifestSnapshot, "response", broken)
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await manifest.GetManifest(_request(handshake), timeout=2)
        assert error.value.code() == grpc.StatusCode.INTERNAL
        assert "sensitive-canary" not in error.value.details()


@pytest.mark.asyncio
async def test_invalid_declarations_fail_before_author_startup(directory):
    class Invalid(_Provider):
        version = "invalid"

    provider = Invalid(directory)
    with pytest.raises(ManifestError):
        await provider.serve()
    assert provider.events == []
    assert not list(directory.glob("*.sfp.json"))
    assert not list(directory.glob("*.sock"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["startup", "snapshot", "publication", "shutdown"]
)
async def test_failure_unwinds_author_resources_and_owned_endpoint(
    directory, monkeypatch, failure
):
    provider = _Provider(directory)

    def fail(*args, **kwargs):
        raise RuntimeError("test failure")

    async def fail_startup():
        provider.events.append("startup")
        fail()

    async def fail_shutdown():
        provider.events.append("shutdown")
        fail()

    if failure == "startup":
        monkeypatch.setattr(provider, "on_startup", fail_startup)
    elif failure == "snapshot":
        monkeypatch.setattr(ManifestDeclaration, "snapshot", fail)
    elif failure == "publication":
        original = provider._server._publish_descriptor

        def publish_then_fail():
            original()
            fail()

        monkeypatch.setattr(
            provider._server, "_publish_descriptor", publish_then_fail
        )
    else:
        monkeypatch.setattr(provider, "on_shutdown", fail_shutdown)
        provider.request_shutdown()
    with pytest.raises(RuntimeError, match="test failure"):
        await provider.serve()
    assert provider.events == ["startup", "shutdown"]
    assert not list(directory.glob("*.sfp.json"))
    assert not list(directory.glob("*.sock"))


@pytest.mark.asyncio
async def test_failed_publication_does_not_remove_newer_generation(
    directory, monkeypatch
):
    provider = _Provider(directory)

    def publish_newer_then_fail():
        provider._server.descriptor_path.write_text(
            json.dumps(
                {
                    "provider_instance_id": str(
                        provider._server.provider_instance_id
                    ),
                    "endpoint_generation": provider._server.endpoint_generation
                    + 1,
                }
            )
        )
        raise RuntimeError("newer generation won publication")

    monkeypatch.setattr(
        provider._server, "_publish_descriptor", publish_newer_then_fail
    )
    with pytest.raises(RuntimeError, match="newer generation"):
        await provider.serve()
    assert (
        json.loads(provider._server.descriptor_path.read_text())[
            "endpoint_generation"
        ]
        == provider._server.endpoint_generation + 1
    )
    assert not provider._server.socket_path.exists()
    assert provider.events == ["startup", "shutdown"]


@pytest.mark.asyncio
async def test_shutdown_timeout_still_withdraws_the_endpoint(
    directory, monkeypatch
):
    provider = _Provider(directory)
    _configure(provider, shutdown_timeout_seconds=0.01)

    async def hang():
        await asyncio.Event().wait()

    monkeypatch.setattr(provider, "on_shutdown", hang)
    with pytest.raises(TimeoutError):
        async with _running(provider):
            pass
    assert not provider._server.socket_path.exists()
    assert not provider._server.descriptor_path.exists()


@pytest.mark.asyncio
async def test_shutdown_cannot_repopulate_sessions(directory):
    provider = _Provider(directory)
    async with _running(provider) as (manifest, bootstrap, descriptor):
        handshake = await _handshake(bootstrap, descriptor)
        # Model an in-flight RPC arriving after generation invalidation.
        provider._server._sessions.clear()
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await _handshake(bootstrap, descriptor)
        assert error.value.code() == grpc.StatusCode.UNAVAILABLE
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await manifest.GetManifest(_request(handshake), timeout=2)
        assert error.value.code() == grpc.StatusCode.FAILED_PRECONDITION
