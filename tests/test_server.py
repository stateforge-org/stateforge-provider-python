"""Integration tests for the private shared Provider-side SFP runtime."""

import asyncio
import json
import os
import shutil
import socket
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import grpc
import pytest
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)
from stateforge_protocol.sfp.bootstrap.v1 import contract as bootstrap_contract
from stateforge_protocol.sfp.endpoint_discovery.v1 import (
    contract as discovery_contract,
)
from stateforge_protocol.sfp.manifest.v1 import contract as manifest_contract

from stateforge_provider import ProtocolVersion
from stateforge_provider._runtime.configuration import (
    ProviderRuntimeConfiguration,
    ProviderRuntimeLimits,
)
from stateforge_provider._runtime.descriptor import (
    _read_descriptor,
)
from stateforge_provider._runtime.grpc import endpoint_message_limits
from stateforge_provider._runtime.identity import ProviderEndpointIdentity
from stateforge_provider._runtime.server import (
    ProviderServer,
    ProviderServerError,
)
from stateforge_provider._runtime.sessions import SessionRegistry
from stateforge_provider._services.bootstrap.service import (
    registration as bootstrap_registration,
)
from stateforge_provider._services.manifest.declaration import ManifestSnapshot
from stateforge_provider._services.manifest.service import (
    registration as manifest_registration,
)
from stateforge_provider.version import SUPPORTED_SFP_VERSIONS

_PROVIDER_INSTANCE_ID = UUID("7f7db7d8-68b4-4f71-9769-065b5c4f941c")
_UUID_VERSION = 4
_REPLACEMENT_ENDPOINT_GENERATION = 2


@pytest.fixture
def socket_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="sfp-", dir="/tmp"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _configuration(directory: Path) -> ProviderRuntimeConfiguration:
    return ProviderRuntimeConfiguration(
        state_directory=directory / "state",
        discovery_directory=directory,
    )


def _request(
    provider_instance_id: UUID,
    endpoint_generation: int,
    *,
    agent_runtime_id: str | None = None,
    software_version: str = "0.1.0",
    supported_versions: tuple[ProtocolVersion, ...] = (
        ProtocolVersion(major=1, minor=0),
    ),
) -> bootstrap_pb2.HandshakeRequest:
    return bootstrap_pb2.HandshakeRequest(
        agent_runtime=bootstrap_pb2.AgentRuntime(
            runtime_id=agent_runtime_id or str(uuid4()),
            software_version=software_version,
        ),
        expected_provider_instance_id=str(provider_instance_id),
        expected_endpoint_generation=endpoint_generation,
        supported_sfp_versions=[
            bootstrap_pb2.ProtocolVersion(
                major=version.major,
                minor=version.minor,
            )
            for version in supported_versions
        ],
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


def _session_id_for_response_size(
    server: ProviderServer,
    target_size: int,
) -> str:
    length = target_size
    while True:
        session_id = "x" * length
        response = bootstrap_pb2.HandshakeResponse(
            provider_instance_id=str(server.provider_instance_id),
            endpoint_generation=server.endpoint_generation,
            selected_sfp_version=bootstrap_pb2.ProtocolVersion(
                major=1,
                minor=0,
            ),
            provider_runtime_id=str(server._runtime_id),
            session_id=session_id,
        )
        adjusted = length + target_size - response.ByteSize()
        if adjusted == length:
            return session_id
        length = adjusted


@pytest.mark.asyncio
async def test_publishes_endpoint_and_negotiates_sfp_1_0(
    socket_directory: Path,
) -> None:
    server = ProviderServer(_configuration(socket_directory))

    async with server:
        document = json.loads(server.descriptor_path.read_text())
        assert document["endpoint_generation"] == 1
        descriptor_status = server.descriptor_path.lstat()
        socket_status = server.socket_path.lstat()
        assert stat.S_IMODE(descriptor_status.st_mode) == (
            discovery_contract.DESCRIPTOR_MODE
        )
        assert stat.S_ISSOCK(socket_status.st_mode)
        assert (
            stat.S_IMODE(socket_status.st_mode)
            == discovery_contract.SOCKET_MODE
        )
        assert socket_status.st_uid == descriptor_status.st_uid
        assert socket_status.st_gid == descriptor_status.st_gid

        channel = grpc.aio.insecure_channel(f"unix:{server.socket_path}")
        try:
            await asyncio.wait_for(channel.channel_ready(), timeout=2)
            response = await bootstrap_pb2_grpc.BootstrapServiceStub(
                channel
            ).Handshake(
                _request(
                    server.provider_instance_id,
                    server.endpoint_generation,
                ),
                timeout=2,
            )
        finally:
            await channel.close()

        assert response.provider_instance_id == str(
            server.provider_instance_id
        )
        assert response.endpoint_generation == server.endpoint_generation
        assert response.selected_sfp_version.major == 1
        assert response.selected_sfp_version.minor == 0
        assert UUID(response.provider_runtime_id).version == _UUID_VERSION
        assert UUID(response.session_id).version == _UUID_VERSION

    assert not server.descriptor_path.exists()
    assert not server.socket_path.exists()


@pytest.mark.asyncio
async def test_bootstrap_request_exact_limit_and_limit_plus_one(
    socket_directory: Path,
) -> None:
    server = ProviderServer(_configuration(socket_directory))
    await server.start()
    channel = grpc.aio.insecure_channel(f"unix:{server.socket_path}")
    await asyncio.wait_for(channel.channel_ready(), timeout=2)
    stub = bootstrap_pb2_grpc.BootstrapServiceStub(channel)
    try:
        exact = _with_serialized_size(
            _request(server.provider_instance_id, server.endpoint_generation),
            bootstrap_contract.MAX_REQUEST_BYTES,
        )
        assert (await stub.Handshake(exact, timeout=2)).session_id

        oversized = _with_serialized_size(
            _request(server.provider_instance_id, server.endpoint_generation),
            bootstrap_contract.MAX_REQUEST_BYTES + 1,
        )
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await stub.Handshake(oversized, timeout=2)
        assert error.value.code() is grpc.StatusCode.RESOURCE_EXHAUSTED
    finally:
        await channel.close()
        await server.stop()


@pytest.mark.asyncio
async def test_bootstrap_response_exact_limit_and_limit_plus_one(
    socket_directory: Path,
    monkeypatch,
) -> None:
    server = ProviderServer(_configuration(socket_directory))
    await server.start()
    channel = grpc.aio.insecure_channel(f"unix:{server.socket_path}")
    await asyncio.wait_for(channel.channel_ready(), timeout=2)
    stub = bootstrap_pb2_grpc.BootstrapServiceStub(channel)
    target_size = bootstrap_contract.MAX_RESPONSE_BYTES

    def negotiate(sessions, version):
        del sessions, version
        return _session_id_for_response_size(server, target_size)

    monkeypatch.setattr(SessionRegistry, "negotiate", negotiate)
    try:
        response = await stub.Handshake(
            _request(server.provider_instance_id, server.endpoint_generation),
            timeout=2,
        )
        assert response.ByteSize() == bootstrap_contract.MAX_RESPONSE_BYTES

        target_size = bootstrap_contract.MAX_RESPONSE_BYTES + 1
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await stub.Handshake(
                _request(
                    server.provider_instance_id,
                    server.endpoint_generation,
                ),
                timeout=2,
            )
        assert error.value.code() is grpc.StatusCode.RESOURCE_EXHAUSTED
        assert error.value.details() == "Bootstrap response limit exceeded"
    finally:
        await channel.close()
        await server.stop()


@pytest.mark.asyncio
async def test_endpoint_modes_do_not_depend_on_process_umask(
    socket_directory: Path,
) -> None:
    server = ProviderServer(_configuration(socket_directory))
    previous_umask = os.umask(0o077)
    try:
        await server.start()
    finally:
        os.umask(previous_umask)

    try:
        assert stat.S_IMODE(server.descriptor_path.stat().st_mode) == (
            discovery_contract.DESCRIPTOR_MODE
        )
        assert stat.S_IMODE(server.socket_path.stat().st_mode) == (
            discovery_contract.SOCKET_MODE
        )
    finally:
        await server.stop()


def test_protocol_version_is_ordered_and_printable() -> None:
    version = ProtocolVersion(major=1, minor=2)

    assert str(version) == "1.2"
    assert version > ProtocolVersion(major=1, minor=1)


def test_sdk_advertises_only_implemented_sfp_versions() -> None:
    assert (ProtocolVersion(major=1, minor=0),) == SUPPORTED_SFP_VERSIONS


def test_shared_endpoint_ceiling_uses_only_registered_procedures() -> None:
    identity = ProviderEndpointIdentity(_PROVIDER_INSTANCE_ID, 1)
    sessions = SessionRegistry(identity)
    registrations = (
        bootstrap_registration(
            endpoint_identity=identity,
            provider_runtime_id=uuid4(),
            sessions=sessions,
        ),
        manifest_registration(ManifestSnapshot(b""), sessions),
    )

    assert endpoint_message_limits(registrations) == (
        max(
            bootstrap_contract.MAX_REQUEST_BYTES,
            manifest_contract.MAX_REQUEST_BYTES,
        ),
        max(
            bootstrap_contract.MAX_RESPONSE_BYTES,
            manifest_contract.MAX_RESPONSE_BYTES,
        ),
    )
    assert (
        endpoint_message_limits(registrations)[0]
        > manifest_contract.MAX_REQUEST_BYTES
    )


@pytest.mark.asyncio
async def test_non_manifest_rpc_reaches_handler_past_manifest_limit(
    socket_directory: Path,
) -> None:
    server = ProviderServer(_configuration(socket_directory))
    await server.start()
    channel = grpc.aio.insecure_channel(f"unix:{server.socket_path}")
    await asyncio.wait_for(channel.channel_ready(), timeout=2)

    try:
        with pytest.raises(grpc.aio.AioRpcError) as captured_error:
            await bootstrap_pb2_grpc.BootstrapServiceStub(channel).Handshake(
                _request(
                    server.provider_instance_id,
                    server.endpoint_generation,
                    agent_runtime_id="x"
                    * (manifest_contract.MAX_REQUEST_BYTES + 1),
                ),
                timeout=2,
            )

        assert captured_error.value.code() is grpc.StatusCode.INVALID_ARGUMENT
        assert captured_error.value.details() == (
            "agent_runtime.runtime_id must be a canonical UUIDv4"
        )
    finally:
        await channel.close()
        await server.stop()


def test_rejects_invalid_configuration(socket_directory: Path) -> None:
    with pytest.raises(ValueError, match="state_directory must be absolute"):
        ProviderRuntimeConfiguration(
            state_directory=Path("relative"),
            discovery_directory=socket_directory,
        )

    with pytest.raises(ValueError, match="must be absolute"):
        ProviderRuntimeConfiguration(
            state_directory=socket_directory / "state",
            discovery_directory=Path("relative"),
        )

    for field in ("max_sessions", "max_json_nodes", "max_schema_nodes"):
        with pytest.raises(ValueError, match="positive integer"):
            ProviderRuntimeLimits(**{field: 0})

    with pytest.raises(ValueError, match="shutdown_timeout_seconds"):
        ProviderRuntimeConfiguration(
            state_directory=socket_directory / "state",
            discovery_directory=socket_directory,
            shutdown_timeout_seconds=0,
        )

    with pytest.raises(ValueError, match="positive uint32"):
        ProtocolVersion(major=0, minor=0)
    with pytest.raises(ValueError, match="must be a uint32"):
        ProtocolVersion(major=1, minor=-1)


@pytest.mark.asyncio
async def test_rejects_incompatible_handshakes(
    socket_directory: Path,
) -> None:
    server = ProviderServer(_configuration(socket_directory))
    await server.start()
    channel = grpc.aio.insecure_channel(f"unix:{server.socket_path}")
    await asyncio.wait_for(channel.channel_ready(), timeout=2)
    stub = bootstrap_pb2_grpc.BootstrapServiceStub(channel)

    invalid_requests = (
        _request(
            UUID("00000000-0000-4000-8000-000000000000"),
            server.endpoint_generation,
        ),
        _request(
            server.provider_instance_id,
            server.endpoint_generation + 1,
        ),
        _request(
            server.provider_instance_id,
            server.endpoint_generation,
            agent_runtime_id="not-a-uuid",
        ),
        _request(
            server.provider_instance_id,
            server.endpoint_generation,
            software_version="",
        ),
    )
    for request in invalid_requests:
        with pytest.raises(grpc.aio.AioRpcError):
            await stub.Handshake(request, timeout=2)

    for unsupported_version in (
        ProtocolVersion(major=1, minor=1),
        ProtocolVersion(major=2, minor=0),
    ):
        incompatible_request = _request(
            server.provider_instance_id,
            server.endpoint_generation,
            supported_versions=(unsupported_version,),
        )
        with pytest.raises(grpc.aio.AioRpcError) as captured_error:
            await stub.Handshake(incompatible_request, timeout=2)
        assert captured_error.value.code() is grpc.StatusCode.UNIMPLEMENTED

    compatible_response = await stub.Handshake(
        _request(
            server.provider_instance_id,
            server.endpoint_generation,
            supported_versions=(
                ProtocolVersion(major=1, minor=0),
                ProtocolVersion(major=1, minor=1),
            ),
        ),
        timeout=2,
    )
    assert compatible_response.selected_sfp_version == (
        bootstrap_pb2.ProtocolVersion(major=1, minor=0)
    )

    await channel.close()
    await server.stop()


@pytest.mark.asyncio
async def test_replacement_descriptor_is_not_removed_by_old_server(
    socket_directory: Path,
) -> None:
    first_server = ProviderServer(_configuration(socket_directory))
    second_server = ProviderServer(_configuration(socket_directory))

    await first_server.start()
    first_provider_instance_id = first_server.provider_instance_id
    with pytest.raises(RuntimeError, match="already running"):
        await first_server.start()
    await second_server.start()

    assert second_server.provider_instance_id == first_provider_instance_id
    assert first_server.endpoint_generation == 1
    assert (
        second_server.endpoint_generation == _REPLACEMENT_ENDPOINT_GENERATION
    )
    with pytest.raises(
        RuntimeError,
        match="equal or newer Provider endpoint generation",
    ):
        first_server._publish_descriptor()

    await first_server.stop()

    current = json.loads(second_server.descriptor_path.read_text())
    assert current["endpoint_generation"] == _REPLACEMENT_ENDPOINT_GENERATION

    await first_server.stop()
    await second_server.stop()


@pytest.mark.asyncio
async def test_rejects_symbolic_link_descriptor(
    socket_directory: Path,
) -> None:
    first_server = ProviderServer(_configuration(socket_directory))
    await first_server.start()
    descriptor_path = first_server.descriptor_path
    await first_server.stop()

    target = socket_directory / "untrusted-descriptor.json"
    target.write_text("{}")
    descriptor_path.symlink_to(target)

    second_server = ProviderServer(_configuration(socket_directory))
    with pytest.raises(ProviderServerError, match="Cannot open"):
        await second_server.start()

    assert descriptor_path.is_symlink()
    assert target.exists()


@pytest.mark.asyncio
async def test_rejects_oversized_descriptor(
    socket_directory: Path,
) -> None:
    first_server = ProviderServer(_configuration(socket_directory))
    await first_server.start()
    descriptor_path = first_server.descriptor_path
    await first_server.stop()

    descriptor_path.write_bytes(
        b"x" * (discovery_contract.MAX_DESCRIPTOR_BYTES + 1)
    )
    descriptor_path.chmod(discovery_contract.DESCRIPTOR_MODE)

    second_server = ProviderServer(_configuration(socket_directory))
    with pytest.raises(ProviderServerError, match="exceeds"):
        await second_server.start()

    assert descriptor_path.stat().st_size == (
        discovery_contract.MAX_DESCRIPTOR_BYTES + 1
    )


@pytest.mark.asyncio
async def test_rejects_non_regular_descriptor(
    socket_directory: Path,
) -> None:
    first_server = ProviderServer(_configuration(socket_directory))
    await first_server.start()
    descriptor_path = first_server.descriptor_path
    await first_server.stop()

    descriptor_path.mkdir()

    second_server = ProviderServer(_configuration(socket_directory))
    with pytest.raises(ProviderServerError, match="not a regular file"):
        await second_server.start()

    assert descriptor_path.is_dir()


def test_rejects_descriptor_not_owned_by_provider(
    socket_directory: Path,
    monkeypatch,
) -> None:
    descriptor_path = socket_directory / "provider.sfp.json"
    descriptor_path.write_text("{}")
    descriptor_path.chmod(discovery_contract.DESCRIPTOR_MODE)
    owner = descriptor_path.stat().st_uid
    monkeypatch.setattr(
        "stateforge_provider._runtime.descriptor.os.geteuid", lambda: owner + 1
    )

    with pytest.raises(ProviderServerError, match="must be owned"):
        _read_descriptor(descriptor_path)


@pytest.mark.asyncio
async def test_descriptor_cleanup_failure_is_reported_after_other_cleanup(
    socket_directory: Path,
    monkeypatch,
) -> None:
    server = ProviderServer(_configuration(socket_directory))
    await server.start()
    descriptor_path = server.descriptor_path
    original_unlink = Path.unlink

    def fail_descriptor_unlink(path, *args, **kwargs):
        if path == descriptor_path:
            raise OSError("simulated descriptor unlink failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_descriptor_unlink)

    with pytest.raises(ProviderServerError, match="descriptor withdrawal"):
        await server.stop()

    assert descriptor_path.exists()
    assert not server.socket_path.exists()
    assert server._server is None
    assert server._sessions is None
    assert not server._started

    original_unlink(descriptor_path)


@pytest.mark.asyncio
async def test_transport_failure_still_cleans_and_resets_runtime(
    socket_directory: Path,
) -> None:
    server = ProviderServer(_configuration(socket_directory))
    await server.start()
    transport = server._server
    assert transport is not None

    class FailingTransport:
        async def stop(self, *, grace):
            del grace
            raise RuntimeError("simulated transport shutdown failure")

    server._server = FailingTransport()
    try:
        with pytest.raises(RuntimeError, match="transport shutdown failure"):
            await server.stop()

        assert not server.descriptor_path.exists()
        assert not server.socket_path.exists()
        assert server._server is None
        assert server._sessions is None
        assert server._socket_identity is None
        assert not server._started
    finally:
        await transport.stop(grace=None)


@pytest.mark.asyncio
async def test_transport_failure_retains_every_cleanup_failure(
    socket_directory: Path,
    monkeypatch,
) -> None:
    server = ProviderServer(_configuration(socket_directory))
    await server.start()
    transport = server._server
    assert transport is not None
    descriptor_path = server.descriptor_path
    socket_path = server.socket_path
    phases: list[str] = []

    def fail_descriptor_cleanup():
        phases.append("descriptor")
        raise ProviderServerError("descriptor cleanup failed")

    def fail_socket_cleanup():
        phases.append("socket")
        raise ProviderServerError("socket cleanup failed")

    class FailingTransport:
        async def stop(self, *, grace):
            del grace
            phases.append("transport")
            raise RuntimeError("transport shutdown failed")

    monkeypatch.setattr(
        server, "_remove_descriptor_if_owned", fail_descriptor_cleanup
    )
    monkeypatch.setattr(server, "_remove_socket", fail_socket_cleanup)
    server._server = FailingTransport()
    try:
        with pytest.raises(
            RuntimeError, match="transport shutdown failed"
        ) as error:
            await server.stop()

        assert phases == ["descriptor", "transport", "socket"]
        notes = getattr(error.value, "__notes__", ())
        assert any("descriptor withdrawal" in note for note in notes)
        assert any("socket removal" in note for note in notes)
        assert server._server is None
        assert server._sessions is None
        assert not server._started
    finally:
        await transport.stop(grace=None)
        descriptor_path.unlink(missing_ok=True)
        socket_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_transport_cancellation_still_cleans_and_resets_runtime(
    socket_directory: Path,
) -> None:
    server = ProviderServer(_configuration(socket_directory))
    await server.start()
    transport = server._server
    assert transport is not None

    class CancelledTransport:
        async def stop(self, *, grace):
            del grace
            raise asyncio.CancelledError

    server._server = CancelledTransport()
    try:
        with pytest.raises(asyncio.CancelledError):
            await server.stop()

        assert not server.descriptor_path.exists()
        assert not server.socket_path.exists()
        assert server._server is None
        assert server._sessions is None
        assert server._socket_identity is None
        assert not server._started
    finally:
        await transport.stop(grace=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement_kind", ["file", "symlink", "socket"])
async def test_socket_cleanup_refuses_replacement(
    socket_directory: Path,
    replacement_kind: str,
) -> None:
    server = ProviderServer(_configuration(socket_directory))
    await server.start()
    transport = server._server
    assert transport is not None
    socket_path = server.socket_path
    socket_path.unlink()

    target: Path | None = None
    replacement_socket: socket.socket | None = None
    if replacement_kind == "file":
        socket_path.write_text("replacement")
    elif replacement_kind == "symlink":
        target = socket_directory / "replacement-target"
        target.write_text("replacement")
        socket_path.symlink_to(target)
    else:
        replacement_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        replacement_socket.bind(str(socket_path))

    class SuccessfulTransport:
        async def stop(self, *, grace):
            del grace

    server._server = SuccessfulTransport()
    try:
        with pytest.raises(ProviderServerError, match="socket removal"):
            await server.stop()

        assert socket_path.exists() or socket_path.is_symlink()
        assert server._server is None
        assert server._socket_identity is None
        assert not server._started
    finally:
        if replacement_socket is not None:
            replacement_socket.close()
        socket_path.unlink(missing_ok=True)
        if target is not None:
            target.unlink(missing_ok=True)
        await transport.stop(grace=None)


@pytest.mark.asyncio
async def test_does_not_remove_an_occupied_generation_socket(
    socket_directory: Path,
) -> None:
    first_server = ProviderServer(_configuration(socket_directory))
    await first_server.start()
    provider_instance_id = first_server.provider_instance_id
    await first_server.stop()

    occupied_path = socket_directory / (
        f"{provider_instance_id}.{_REPLACEMENT_ENDPOINT_GENERATION}.sock"
    )
    occupied_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    occupied_socket.bind(str(occupied_path))
    second_server = ProviderServer(_configuration(socket_directory))
    try:
        with pytest.raises(RuntimeError, match="already occupied by a socket"):
            await second_server.start()
        assert occupied_path.exists()
    finally:
        occupied_socket.close()
        occupied_path.unlink(missing_ok=True)
