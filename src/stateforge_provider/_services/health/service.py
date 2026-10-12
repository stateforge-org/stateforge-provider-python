"""Serve bounded standard gRPC Health Check and Watch requests."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TypeAlias

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

from stateforge_provider._runtime.grpc import ProcedureRegistration
from stateforge_provider._services.health.limits import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
)
from stateforge_provider.health import HealthStatus

_HEALTH_SERVICE_NAME = "grpc.health.v1.Health"
_OVERALL_SERVICE_NAME = ""
_Status: TypeAlias = health_pb2.HealthCheckResponse.ServingStatus


@dataclass(eq=False, slots=True)
class _Observer:
    """Own one bounded Watch queue and its overflow signal."""

    queue: asyncio.Queue[_Status]
    overflowed: asyncio.Event


class ProviderHealthService(health_pb2_grpc.HealthServicer):
    """Publish Provider-wide health with bounded ordered Watch delivery."""

    def __init__(
        self,
        *,
        max_watchers: int,
        watch_queue_capacity: int,
        watch_delivery_timeout_seconds: float,
    ) -> None:
        self._max_watchers = max_watchers
        self._watch_queue_capacity = watch_queue_capacity
        self._watch_delivery_timeout_seconds = watch_delivery_timeout_seconds
        self._statuses: dict[str, _Status] = {
            _OVERALL_SERVICE_NAME: health_pb2.HealthCheckResponse.NOT_SERVING
        }
        self._observers: defaultdict[str, set[_Observer]] = defaultdict(set)
        self._observer_count = 0
        self._stopping = False

    def register_services(self, service_names: Iterable[str]) -> None:
        """Register hosted SFP services as initially not serving."""
        overall_status = self._statuses[_OVERALL_SERVICE_NAME]
        for service_name in service_names:
            if service_name and service_name != _HEALTH_SERVICE_NAME:
                self._set_wire_status(service_name, overall_status)

    async def Check(  # noqa: N802
        self,
        request: health_pb2.HealthCheckRequest,
        context: grpc.aio.ServicerContext[
            health_pb2.HealthCheckRequest,
            health_pb2.HealthCheckResponse,
        ],
    ) -> health_pb2.HealthCheckResponse:
        """Return the current status for a registered service."""
        await self._validate_request_size(request, context)
        status = self._statuses.get(request.service)
        if status is None:
            await context.abort(
                grpc.StatusCode.NOT_FOUND,
                "Health service is not registered",
            )
        return health_pb2.HealthCheckResponse(status=status)

    async def Watch(  # noqa: N802
        self,
        request: health_pb2.HealthCheckRequest,
        context: grpc.aio.ServicerContext[
            health_pb2.HealthCheckRequest,
            health_pb2.HealthCheckResponse,
        ],
    ) -> None:
        """Stream the current status and every ordered status change."""
        await self._validate_request_size(request, context)
        if self._observer_count >= self._max_watchers:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Health Watch observer capacity exhausted",
            )

        observer = _Observer(
            asyncio.Queue(maxsize=self._watch_queue_capacity),
            asyncio.Event(),
        )
        service = request.service
        self._observers[service].add(observer)
        self._observer_count += 1
        observer.queue.put_nowait(
            self._statuses.get(
                service,
                health_pb2.HealthCheckResponse.SERVICE_UNKNOWN,
            )
        )
        try:
            while True:
                status = await self._next_status(observer, context)
                response = health_pb2.HealthCheckResponse(status=status)
                async with asyncio.timeout(
                    self._watch_delivery_timeout_seconds
                ):
                    await context.write(response)
        except TimeoutError:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Health Watch delivery deadline exceeded",
            )
        finally:
            observers = self._observers.get(service)
            if observers is not None:
                observers.discard(observer)
                if not observers:
                    self._observers.pop(service, None)
            self._observer_count -= 1

    def publish(self, status: HealthStatus) -> None:
        """Publish one author-facing state to all hosted service keys."""
        if self._stopping:
            return
        wire_status = (
            health_pb2.HealthCheckResponse.SERVING
            if status.is_serving
            else health_pb2.HealthCheckResponse.NOT_SERVING
        )
        for service in tuple(self._statuses):
            self._set_wire_status(service, wire_status)

    def begin_shutdown(self) -> None:
        """Fail closed and permanently reject later readiness updates."""
        if self._stopping:
            return
        self._stopping = True
        for service in tuple(self._statuses):
            self._set_wire_status(
                service,
                health_pb2.HealthCheckResponse.NOT_SERVING,
            )

    def close(self) -> None:
        """Wake any runtime-owned observers after transport shutdown."""
        self._stopping = True
        for observers in tuple(self._observers.values()):
            for observer in tuple(observers):
                observer.overflowed.set()

    def registration(
        self,
        hosted_service_names: Iterable[str],
    ) -> ProcedureRegistration:
        """Build the standard Health registration for this runtime."""
        self.register_services(hosted_service_names)

        def install(server: grpc.aio.Server) -> None:
            health_pb2_grpc.add_HealthServicer_to_server(self, server)

        return ProcedureRegistration(
            name=_HEALTH_SERVICE_NAME,
            max_request_bytes=MAX_REQUEST_BYTES,
            max_response_bytes=MAX_RESPONSE_BYTES,
            install=install,
        )

    async def _validate_request_size(
        self,
        request: health_pb2.HealthCheckRequest,
        context: grpc.aio.ServicerContext[
            health_pb2.HealthCheckRequest,
            health_pb2.HealthCheckResponse,
        ],
    ) -> None:
        """Reject a service key outside the local Health request bound."""
        if request.ByteSize() > MAX_REQUEST_BYTES:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Health request limit exceeded",
            )

    async def _next_status(
        self,
        observer: _Observer,
        context: grpc.aio.ServicerContext[
            health_pb2.HealthCheckRequest,
            health_pb2.HealthCheckResponse,
        ],
    ) -> _Status:
        """Wait for a queued status while detecting observer overflow."""
        queued = asyncio.create_task(observer.queue.get())
        overflowed = asyncio.create_task(observer.overflowed.wait())
        tasks = (queued, overflowed)
        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if overflowed in done and overflowed.result():
            queued.cancel()
            await asyncio.gather(queued, return_exceptions=True)
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Health Watch observer exceeded delivery capacity",
            )
        return queued.result()

    def _set_wire_status(self, service: str, status: _Status) -> None:
        """Record and fan out one changed status without blocking."""
        if self._statuses.get(service) == status:
            return
        self._statuses[service] = status
        for observer in tuple(self._observers.get(service, ())):
            try:
                observer.queue.put_nowait(status)
            except asyncio.QueueFull:
                observer.overflowed.set()
