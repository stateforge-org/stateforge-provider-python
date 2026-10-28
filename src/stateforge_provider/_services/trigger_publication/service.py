"""Serve Provider-originated trigger publications over canonical P3."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import grpc
from stateforge_protocol.sfp.trigger_publication.v1 import (
    contract,
    trigger_publication_pb2,
    trigger_publication_pb2_grpc,
    validation,
)

from stateforge_provider._runtime.grpc import ProcedureRegistration
from stateforge_provider._runtime.identity import ProviderEndpointIdentity
from stateforge_provider._runtime.sessions import SessionRegistry
from stateforge_provider._services.health.service import ProviderHealthService
from stateforge_provider._services.manifest.declaration import ManifestSnapshot
from stateforge_provider._services.trigger_publication.runtime import (
    DuplicateTriggerStreamError,
    StaleTriggerStreamError,
    TriggerAcknowledgementError,
    TriggerPublicationRuntime,
    TriggerStreamClosedError,
    TriggerStreamLease,
)
from stateforge_provider.triggers import TriggerPublicationUnavailableError
from stateforge_provider.version import ProtocolVersion


@dataclass(frozen=True, slots=True)
class _StreamFailureError(Exception):
    """Carry one sanitized canonical gRPC termination."""

    code: grpc.StatusCode
    details: str


class TriggerPublicationService(
    trigger_publication_pb2_grpc.TriggerPublicationServiceServicer
):
    """Validate stream framing and delegate event state to the runtime."""

    def __init__(
        self,
        *,
        endpoint: ProviderEndpointIdentity,
        snapshot: ManifestSnapshot,
        sessions: SessionRegistry,
        health: ProviderHealthService,
        runtime: TriggerPublicationRuntime,
    ) -> None:
        self._endpoint = endpoint
        self._manifest_revision = snapshot.manifest_revision
        self._sessions = sessions
        self._health = health
        self._runtime = runtime

    async def StreamTriggers(  # noqa: N802, PLR0912, PLR0915
        self,
        request_iterator: AsyncIterator[
            trigger_publication_pb2.StreamTriggersRequest
        ],
        context: grpc.aio.ServicerContext[
            trigger_publication_pb2.StreamTriggersRequest,
            trigger_publication_pb2.StreamTriggersResponse,
        ],
    ) -> AsyncIterator[trigger_publication_pb2.StreamTriggersResponse]:
        """Bind one session, publish events, and consume correlated acks."""
        lease: TriggerStreamLease | None = None
        reader: asyncio.Task[None] | None = None
        delivery: (
            asyncio.Task[trigger_publication_pb2.TriggerPublication] | None
        ) = None
        try:
            try:
                opening_request = await anext(request_iterator)
            except StopAsyncIteration:
                raise _StreamFailureError(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "Trigger stream must begin with open",
                ) from None
            open_message = self._validate_opening_request(opening_request)
            self._validate_fences(open_message)
            if not self._health.is_serving():
                raise _StreamFailureError(
                    grpc.StatusCode.UNAVAILABLE,
                    "Provider is not ready for Trigger Publication",
                )
            try:
                lease = await self._runtime.open_stream(
                    open_message.session_binding.expected_session_id,
                    open_message.requested_max_in_flight_publications,
                )
            except DuplicateTriggerStreamError:
                raise _StreamFailureError(
                    grpc.StatusCode.ALREADY_EXISTS,
                    "Trigger stream is already active for this session",
                ) from None
            except TriggerPublicationUnavailableError:
                raise _StreamFailureError(
                    grpc.StatusCode.UNAVAILABLE,
                    "Trigger publication runtime is stopping",
                ) from None
            self._validate_fences(open_message)
            if not self._health.is_serving():
                raise _StreamFailureError(
                    grpc.StatusCode.UNAVAILABLE,
                    "Provider is not ready for Trigger Publication",
                )

            ready = self._ready(open_message, lease)
            response = trigger_publication_pb2.StreamTriggersResponse(
                ready=ready
            )
            validation.validate_stream_response(response)
            validation.validate_stream_open_exchange(open_message, ready)
            yield response

            reader = asyncio.create_task(
                self._read_acknowledgements(request_iterator, lease),
                name="stateforge-trigger-acknowledgements",
            )
            while True:
                delivery = asyncio.create_task(
                    self._runtime.next_publication(lease),
                    name="stateforge-trigger-delivery",
                )
                done, _ = await asyncio.wait(
                    (reader, delivery),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if reader in done:
                    reader.result()
                    delivery.cancel()
                    await asyncio.gather(delivery, return_exceptions=True)
                    delivery = None
                    return
                publication = delivery.result()
                delivery = None
                if not self._current_session(lease.session_id):
                    raise _StreamFailureError(
                        grpc.StatusCode.FAILED_PRECONDITION,
                        "Trigger stream session is no longer active",
                    )
                if not self._health.is_serving():
                    raise _StreamFailureError(
                        grpc.StatusCode.UNAVAILABLE,
                        "Provider readiness changed during Trigger "
                        "Publication",
                    )
                response = trigger_publication_pb2.StreamTriggersResponse(
                    publication=publication
                )
                validation.validate_stream_response(response)
                yield response
        except TriggerStreamClosedError:
            return
        except _StreamFailureError as failure:
            await context.abort(failure.code, failure.details)
        except validation.TriggerPublicationValidationError:
            await context.abort(
                grpc.StatusCode.INTERNAL,
                "Trigger Publication response is unavailable",
            )
        finally:
            if delivery is not None:
                delivery.cancel()
                await asyncio.gather(delivery, return_exceptions=True)
            if reader is not None:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)
            if lease is not None:
                await self._runtime.close_stream(lease)

    def _validate_opening_request(
        self,
        request: trigger_publication_pb2.StreamTriggersRequest,
    ) -> trigger_publication_pb2.TriggerStreamOpen:
        """Require one canonical open envelope as the first request."""
        try:
            validation.validate_stream_request(request)
        except validation.TriggerPublicationValidationError:
            raise _StreamFailureError(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Invalid Trigger Publication stream request",
            ) from None
        if request.WhichOneof("message") != "open":
            raise _StreamFailureError(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Trigger stream must begin with open",
            )
        return request.open

    def _validate_fences(
        self,
        open_message: trigger_publication_pb2.TriggerStreamOpen,
    ) -> None:
        """Require the exact current endpoint, session, and manifest."""
        binding = open_message.session_binding
        session = self._sessions.get(binding.expected_session_id)
        if session is None or (
            binding.expected_provider_instance_id
            != str(self._endpoint.provider_instance_id)
            or binding.expected_endpoint_generation
            != self._endpoint.endpoint_generation
            or session.endpoint != self._endpoint
            or session.version != ProtocolVersion(1, 0)
            or binding.expected_manifest_revision != self._manifest_revision
        ):
            raise _StreamFailureError(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Trigger stream binding is stale or inactive",
            )

    def _ready(
        self,
        open_message: trigger_publication_pb2.TriggerStreamOpen,
        lease: TriggerStreamLease,
    ) -> trigger_publication_pb2.TriggerStreamReady:
        """Construct a response correlated to the accepted opening fences."""
        binding = open_message.session_binding
        return trigger_publication_pb2.TriggerStreamReady(
            provider_instance_id=str(self._endpoint.provider_instance_id),
            endpoint_generation=self._endpoint.endpoint_generation,
            session_id=binding.expected_session_id,
            manifest_revision=self._manifest_revision,
            maximum_in_flight_publications=lease.maximum_in_flight,
        )

    async def _read_acknowledgements(
        self,
        request_iterator: AsyncIterator[
            trigger_publication_pb2.StreamTriggersRequest
        ],
        lease: TriggerStreamLease,
    ) -> None:
        """Consume later requests as current-stream acknowledgements."""
        async for request in request_iterator:
            try:
                validation.validate_stream_request(request)
            except validation.TriggerPublicationValidationError:
                raise _StreamFailureError(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "Invalid Trigger Publication stream request",
                ) from None
            if request.WhichOneof("message") != "acknowledgement":
                raise _StreamFailureError(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "Trigger stream accepts open only as its first request",
                )
            try:
                await self._runtime.acknowledge(
                    lease,
                    request.acknowledgement,
                    is_session_current=self._current_session,
                )
            except StaleTriggerStreamError:
                raise _StreamFailureError(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    "Trigger stream session is no longer active",
                ) from None
            except (
                TriggerAcknowledgementError,
                validation.TriggerPublicationValidationError,
            ):
                raise _StreamFailureError(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "Trigger acknowledgement is not active on this stream",
                ) from None

    def _current_session(self, session_id: str) -> bool:
        """Check that a delivery remains bound to this endpoint generation."""
        session = self._sessions.get(session_id)
        return session is not None and (
            session.endpoint == self._endpoint
            and session.version == ProtocolVersion(1, 0)
        )


def registration(
    *,
    endpoint: ProviderEndpointIdentity,
    snapshot: ManifestSnapshot,
    sessions: SessionRegistry,
    health: ProviderHealthService,
    runtime: TriggerPublicationRuntime,
) -> ProcedureRegistration:
    """Build the bounded registration for one endpoint generation."""
    service = TriggerPublicationService(
        endpoint=endpoint,
        snapshot=snapshot,
        sessions=sessions,
        health=health,
        runtime=runtime,
    )

    def install(server: grpc.aio.Server) -> None:
        trigger_publication_pb2_grpc.add_TriggerPublicationServiceServicer_to_server(
            service,
            server,
        )

    return ProcedureRegistration(
        name=contract.SERVICE_NAME,
        max_request_bytes=contract.MAX_REQUEST_BYTES,
        max_response_bytes=contract.MAX_RESPONSE_BYTES,
        install=install,
    )
