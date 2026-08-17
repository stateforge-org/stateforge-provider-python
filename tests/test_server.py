"""Integration tests for the Provider-side SFP bootstrap server."""

import asyncio
import json
import os
import shutil
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

from stateforge_rpc import (
    ProtocolVersion,
    ProviderServer,
    ProviderServerConfiguration,
)

_PROVIDER_INSTANCE_ID = UUID("7f7db7d8-68b4-4f71-9769-065b5c4f941c")
_UUID_VERSION = 4
_REPLACEMENT_ENDPOINT_GENERATION = 2
_DESCRIPTOR_MODE = 0o640
_SOCKET_MODE = 0o660


@pytest.fixture
def socket_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="sfp-", dir="/tmp"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _configuration(directory: Path) -> ProviderServerConfiguration:
    return ProviderServerConfiguration(
        provider_instance_id=_PROVIDER_INSTANCE_ID,
        endpoint_generation=1,
        discovery_directory=directory,
        supported_sfp_versions=(
            ProtocolVersion(major=1, minor=0),
            ProtocolVersion(major=1, minor=1),
        ),
    )


def _request(
    *,
    provider_instance_id: UUID = _PROVIDER_INSTANCE_ID,
    endpoint_generation: int = 1,
    agent_runtime_id: str | None = None,
    software_version: str = "0.1.0",
    supported_versions: tuple[ProtocolVersion, ...] = (
        ProtocolVersion(major=1, minor=0),
        ProtocolVersion(major=1, minor=1),
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


@pytest.mark.asyncio
async def test_publishes_endpoint_and_negotiates_highest_version(
    socket_directory: Path,
) -> None:
    server = ProviderServer(_configuration(socket_directory))

    async with server:
        document = json.loads(server.descriptor_path.read_text())
        assert document["endpoint_generation"] == 1
        descriptor_status = server.descriptor_path.lstat()
        socket_status = server.socket_path.lstat()
        assert stat.S_IMODE(descriptor_status.st_mode) == _DESCRIPTOR_MODE
        assert stat.S_ISSOCK(socket_status.st_mode)
        assert stat.S_IMODE(socket_status.st_mode) == _SOCKET_MODE
        assert socket_status.st_uid == descriptor_status.st_uid
        assert socket_status.st_gid == descriptor_status.st_gid

        channel = grpc.aio.insecure_channel(f"unix:{server.socket_path}")
        try:
            await asyncio.wait_for(channel.channel_ready(), timeout=2)
            response = await bootstrap_pb2_grpc.BootstrapServiceStub(
                channel
            ).Handshake(_request(), timeout=2)
        finally:
            await channel.close()

        assert response.provider_instance_id == str(_PROVIDER_INSTANCE_ID)
        assert response.selected_sfp_version.major == 1
        assert response.selected_sfp_version.minor == 1
        assert UUID(response.provider_runtime_id).version == _UUID_VERSION
        assert UUID(response.session_id).version == _UUID_VERSION

    assert not server.descriptor_path.exists()
    assert not server.socket_path.exists()


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
            _DESCRIPTOR_MODE
        )
        assert stat.S_IMODE(server.socket_path.stat().st_mode) == _SOCKET_MODE
    finally:
        await server.stop()


def test_protocol_version_is_ordered_and_printable() -> None:
    version = ProtocolVersion(major=1, minor=2)

    assert str(version) == "1.2"
    assert version > ProtocolVersion(major=1, minor=1)


def test_rejects_invalid_configuration(socket_directory: Path) -> None:
    with pytest.raises(ValueError, match="positive signed 64-bit"):
        ProviderServerConfiguration(
            provider_instance_id=_PROVIDER_INSTANCE_ID,
            endpoint_generation=0,
            discovery_directory=socket_directory,
            supported_sfp_versions=(ProtocolVersion(major=1, minor=0),),
        )

    with pytest.raises(ValueError, match="duplicates"):
        ProviderServerConfiguration(
            provider_instance_id=_PROVIDER_INSTANCE_ID,
            endpoint_generation=1,
            discovery_directory=socket_directory,
            supported_sfp_versions=(
                ProtocolVersion(major=1, minor=0),
                ProtocolVersion(major=1, minor=0),
            ),
        )

    with pytest.raises(ValueError, match="must be absolute"):
        ProviderServerConfiguration(
            provider_instance_id=_PROVIDER_INSTANCE_ID,
            endpoint_generation=1,
            discovery_directory=Path("relative"),
            supported_sfp_versions=(ProtocolVersion(major=1, minor=0),),
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
            provider_instance_id=UUID("00000000-0000-4000-8000-000000000000")
        ),
        _request(endpoint_generation=2),
        _request(agent_runtime_id="not-a-uuid"),
        _request(software_version=""),
    )
    for request in invalid_requests:
        with pytest.raises(grpc.aio.AioRpcError):
            await stub.Handshake(request, timeout=2)

    incompatible_request = _request(
        supported_versions=(ProtocolVersion(major=2, minor=0),)
    )
    with pytest.raises(grpc.aio.AioRpcError) as captured_error:
        await stub.Handshake(incompatible_request, timeout=2)
    assert captured_error.value.code() is grpc.StatusCode.UNIMPLEMENTED

    await channel.close()
    await server.stop()


@pytest.mark.asyncio
async def test_replacement_descriptor_is_not_removed_by_old_server(
    socket_directory: Path,
) -> None:
    first_server = ProviderServer(_configuration(socket_directory))
    second_server = ProviderServer(
        ProviderServerConfiguration(
            provider_instance_id=_PROVIDER_INSTANCE_ID,
            endpoint_generation=_REPLACEMENT_ENDPOINT_GENERATION,
            discovery_directory=socket_directory,
            supported_sfp_versions=(ProtocolVersion(major=1, minor=0),),
        )
    )

    await first_server.start()
    with pytest.raises(RuntimeError, match="already running"):
        await first_server.start()
    await second_server.start()
    await first_server.stop()

    current = json.loads(second_server.descriptor_path.read_text())
    assert current["endpoint_generation"] == _REPLACEMENT_ENDPOINT_GENERATION

    await first_server.stop()
    await second_server.stop()
