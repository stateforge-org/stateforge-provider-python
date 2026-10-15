"""Behavioral tests for Provider health publication and gRPC adaptation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import grpc
import pytest
from grpc_health.v1 import health_pb2, health_pb2_grpc
from stateforge_protocol.sfp import health_contract

from stateforge_provider import HealthStatus, Platform, Provider
from stateforge_provider._runtime.configuration import (
    ProviderRuntimeConfiguration,
    ProviderRuntimeLimits,
)
from stateforge_provider._services.health.service import ProviderHealthService


@pytest.fixture
def endpoint_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="sfp-health-", dir="/tmp"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class _HealthProvider(Provider):
    identity = "stateforge.test_health"
    display_name = "Health test Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(self, directory: Path) -> None:
        super().__init__(
            discovery_directory=directory,
            state_directory=directory / "state",
        )
        self.status = HealthStatus.healthy()
        self.fail_health = False
        self.started = asyncio.Event()

    async def on_startup(self) -> None:
        self.started.set()

    async def health(self) -> HealthStatus:
        if self.fail_health:
            raise RuntimeError("local sensitive probe detail")
        return self.status


@contextlib.asynccontextmanager
async def _running(
    provider: _HealthProvider,
) -> AsyncIterator[
    tuple[
        health_pb2_grpc.HealthStub,
        grpc.aio.Channel,
        asyncio.Task[None],
    ]
]:
    task = asyncio.create_task(provider.serve())
    await asyncio.wait_for(provider.started.wait(), timeout=2)
    channel = grpc.aio.insecure_channel(f"unix:{provider._server.socket_path}")
    try:
        await asyncio.wait_for(channel.channel_ready(), timeout=2)
        yield health_pb2_grpc.HealthStub(channel), channel, task
    finally:
        provider.request_shutdown()
        await channel.close()
        await asyncio.wait_for(task, timeout=2)


def _request(
    service: str = health_contract.PROVIDER_HEALTH_SERVICE,
) -> health_pb2.HealthCheckRequest:
    return health_pb2.HealthCheckRequest(service=service)


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
async def test_check_uses_standard_health_on_the_shared_endpoint(
    endpoint_directory: Path,
) -> None:
    provider = _HealthProvider(endpoint_directory)

    async with _running(provider) as (stub, _, _):
        for service in (
            health_contract.PROVIDER_HEALTH_SERVICE,
            health_contract.BOOTSTRAP_SERVICE,
            health_contract.MANIFEST_SERVICE,
        ):
            response = await stub.Check(_request(service), timeout=2)
            assert response.status == health_pb2.HealthCheckResponse.SERVING

        for service in ("stateforge.sfp.unknown.v1.Service", "stateforge.*"):
            with pytest.raises(grpc.aio.AioRpcError) as captured:
                await stub.Check(_request(service), timeout=2)
            assert captured.value.code() is grpc.StatusCode.NOT_FOUND
            assert "sensitive" not in captured.value.details()


@pytest.mark.asyncio
async def test_watch_replays_and_preserves_ordered_author_transitions(
    endpoint_directory: Path,
) -> None:
    provider = _HealthProvider(endpoint_directory)

    async with _running(provider) as (stub, _, _):
        watch = stub.Watch(_request())
        assert (await watch.read()).status == (
            health_pb2.HealthCheckResponse.SERVING
        )

        provider.status = HealthStatus.maintenance()
        assert await provider.refresh_health() is HealthStatus.MAINTENANCE
        assert (await watch.read()).status == (
            health_pb2.HealthCheckResponse.NOT_SERVING
        )

        provider.status = HealthStatus.healthy()
        assert await provider.refresh_health() is HealthStatus.SERVING
        assert (await watch.read()).status == (
            health_pb2.HealthCheckResponse.SERVING
        )
        watch.cancel()


@pytest.mark.asyncio
async def test_unknown_watch_remains_open_until_service_registration(
    endpoint_directory: Path,
) -> None:
    provider = _HealthProvider(endpoint_directory)

    async with _running(provider) as (stub, _, _):
        service_name = "stateforge.sfp.future.v1.FutureService"
        watch = stub.Watch(_request(service_name))
        assert (await watch.read()).status == (
            health_pb2.HealthCheckResponse.SERVICE_UNKNOWN
        )

        assert provider._health_service is not None
        provider._health_service.register_services((service_name,))
        assert (await watch.read()).status == (
            health_pb2.HealthCheckResponse.SERVING
        )
        watch.cancel()


@pytest.mark.asyncio
async def test_hook_failure_is_local_and_fails_closed(
    endpoint_directory: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = _HealthProvider(endpoint_directory)

    async with _running(provider) as (stub, _, _):
        watch = stub.Watch(_request())
        assert (await watch.read()).status == (
            health_pb2.HealthCheckResponse.SERVING
        )
        provider.fail_health = True
        with caplog.at_level(logging.ERROR):
            status = await provider.refresh_health()

        assert status is HealthStatus.NOT_SERVING
        assert (await watch.read()).status == (
            health_pb2.HealthCheckResponse.NOT_SERVING
        )
        assert "local sensitive probe detail" in caplog.text
        response = await stub.Check(_request(), timeout=2)
        assert response.status == health_pb2.HealthCheckResponse.NOT_SERVING
        watch.cancel()


@pytest.mark.asyncio
async def test_shutdown_publishes_not_serving_before_transport_closes(
    endpoint_directory: Path,
) -> None:
    provider = _HealthProvider(endpoint_directory)
    provider._configuration = ProviderRuntimeConfiguration(
        state_directory=endpoint_directory / "state",
        discovery_directory=endpoint_directory,
        shutdown_timeout_seconds=0.25,
    )
    task = asyncio.create_task(provider.serve())
    await asyncio.wait_for(provider.started.wait(), timeout=2)
    channel = grpc.aio.insecure_channel(f"unix:{provider._server.socket_path}")
    await asyncio.wait_for(channel.channel_ready(), timeout=2)
    watch = health_pb2_grpc.HealthStub(channel).Watch(_request())
    assert (
        await watch.read()
    ).status == health_pb2.HealthCheckResponse.SERVING

    provider.request_shutdown()
    assert (await watch.read()).status == (
        health_pb2.HealthCheckResponse.NOT_SERVING
    )
    watch.cancel()
    await channel.close()
    await asyncio.wait_for(task, timeout=2)

    assert not provider._server.descriptor_path.exists()
    assert not provider._server.socket_path.exists()


@pytest.mark.asyncio
async def test_restart_has_a_new_generation_and_fresh_serving_state(
    endpoint_directory: Path,
) -> None:
    first = _HealthProvider(endpoint_directory)
    async with _running(first) as (stub, _, _):
        first_generation = first._server.endpoint_generation
        assert (await stub.Check(_request(), timeout=2)).status == (
            health_pb2.HealthCheckResponse.SERVING
        )

    second = _HealthProvider(endpoint_directory)
    async with _running(second) as (stub, _, _):
        assert second._server.endpoint_generation == first_generation + 1
        assert (await stub.Check(_request(), timeout=2)).status == (
            health_pb2.HealthCheckResponse.SERVING
        )


class _AbortError(Exception):
    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        self.code = code
        self.details = details


class _BlockingContext:
    def __init__(self) -> None:
        self.first_write = asyncio.Event()
        self.release_writes = asyncio.Event()
        self.responses: list[health_pb2.HealthCheckResponse] = []

    async def write(self, response: health_pb2.HealthCheckResponse) -> None:
        self.responses.append(response)
        self.first_write.set()
        await self.release_writes.wait()

    async def abort(self, code: grpc.StatusCode, details: str = "") -> None:
        raise _AbortError(code, details)


@pytest.mark.asyncio
async def test_health_request_exact_limit_and_limit_plus_one(
    endpoint_directory: Path,
) -> None:
    provider = _HealthProvider(endpoint_directory)

    async with _running(provider) as (stub, _, _):
        exact = _with_serialized_size(
            _request(),
            health_contract.MAX_REQUEST_BYTES,
        )
        response = await stub.Check(exact, timeout=2)
        assert response.status == health_pb2.HealthCheckResponse.SERVING

        oversized = _with_serialized_size(
            _request(),
            health_contract.MAX_REQUEST_BYTES + 1,
        )
        with pytest.raises(grpc.aio.AioRpcError) as error:
            await stub.Check(oversized, timeout=2)
        assert error.value.code() is grpc.StatusCode.RESOURCE_EXHAUSTED
        assert error.value.details() == "Health request limit exceeded"


@pytest.mark.parametrize(
    ("response_size", "accepted"),
    [
        (health_contract.MAX_RESPONSE_BYTES, True),
        (health_contract.MAX_RESPONSE_BYTES + 1, False),
    ],
)
@pytest.mark.asyncio
async def test_health_response_exact_limit_and_limit_plus_one(
    response_size: int,
    accepted: bool,
) -> None:
    service = ProviderHealthService(
        max_watchers=1,
        watch_queue_capacity=1,
        watch_delivery_timeout_seconds=1,
    )
    response = _with_serialized_size(
        health_pb2.HealthCheckResponse(
            status=health_pb2.HealthCheckResponse.SERVING
        ),
        response_size,
    )
    context = _BlockingContext()

    if accepted:
        await service._validate_response_size(response, context)
    else:
        with pytest.raises(_AbortError) as error:
            await service._validate_response_size(response, context)
        assert error.value.code is grpc.StatusCode.RESOURCE_EXHAUSTED
        assert error.value.details == "Health response limit exceeded"


@pytest.mark.asyncio
async def test_slow_watch_is_bounded_without_blocking_the_publisher() -> None:
    service = ProviderHealthService(
        max_watchers=1,
        watch_queue_capacity=1,
        watch_delivery_timeout_seconds=1,
    )
    service.register_services((health_contract.BOOTSTRAP_SERVICE,))
    context = _BlockingContext()
    watch = asyncio.create_task(service.Watch(_request(), context))
    await asyncio.wait_for(context.first_write.wait(), timeout=1)

    service.publish(HealthStatus.healthy())
    service.publish(HealthStatus.maintenance())
    service.publish(HealthStatus.healthy())
    context.release_writes.set()

    with pytest.raises(_AbortError) as captured:
        await asyncio.wait_for(watch, timeout=1)
    assert captured.value.code is grpc.StatusCode.RESOURCE_EXHAUSTED
    assert service._observer_count == 0


@pytest.mark.asyncio
async def test_watch_capacity_and_delivery_timeout_are_bounded() -> None:
    service = ProviderHealthService(
        max_watchers=1,
        watch_queue_capacity=1,
        watch_delivery_timeout_seconds=0.01,
    )
    first_context = _BlockingContext()
    first = asyncio.create_task(service.Watch(_request(), first_context))
    await asyncio.wait_for(first_context.first_write.wait(), timeout=1)

    with pytest.raises(_AbortError) as captured:
        await service.Watch(_request(), _BlockingContext())
    assert captured.value.code is grpc.StatusCode.RESOURCE_EXHAUSTED

    with pytest.raises(_AbortError) as timed_out:
        await first
    assert timed_out.value.code is grpc.StatusCode.RESOURCE_EXHAUSTED


def test_health_status_and_runtime_limits_are_typed_and_validated(
    endpoint_directory: Path,
) -> None:
    assert HealthStatus.healthy().is_serving
    assert not HealthStatus.degraded().is_serving
    assert not HealthStatus.maintenance().is_serving
    assert not HealthStatus.not_serving().is_serving

    for field in ("max_health_watchers", "health_watch_queue_capacity"):
        with pytest.raises(ValueError, match="positive integer"):
            ProviderRuntimeLimits(**{field: 0})

    with pytest.raises(
        ValueError,
        match="health_watch_delivery_timeout_seconds must be positive",
    ):
        ProviderRuntimeConfiguration(
            state_directory=endpoint_directory / "state",
            discovery_directory=endpoint_directory,
            health_watch_delivery_timeout_seconds=0,
        )
