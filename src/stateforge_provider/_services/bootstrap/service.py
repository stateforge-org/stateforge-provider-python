"""Negotiate one session on the shared Provider endpoint."""

from __future__ import annotations

from uuid import UUID

import grpc
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
    contract,
)

from stateforge_provider._runtime.grpc import ProcedureRegistration
from stateforge_provider._runtime.identity import (
    ProviderEndpointIdentity,
    is_canonical_uuid4,
)
from stateforge_provider._runtime.sessions import (
    SessionRegistry,
    SessionRegistryClosedError,
)
from stateforge_provider.version import SUPPORTED_SFP_VERSIONS, ProtocolVersion


class BootstrapService(bootstrap_pb2_grpc.BootstrapServiceServicer):
    """Implement version-neutral SFP session negotiation."""

    def __init__(
        self,
        *,
        endpoint_identity: ProviderEndpointIdentity,
        provider_runtime_id: UUID,
        sessions: SessionRegistry,
    ) -> None:
        self._endpoint_identity = endpoint_identity
        self._provider_runtime_id = provider_runtime_id
        self._sessions = sessions

    async def Handshake(  # noqa: N802
        self,
        request: bootstrap_pb2.HandshakeRequest,
        context: grpc.aio.ServicerContext[
            bootstrap_pb2.HandshakeRequest,
            bootstrap_pb2.HandshakeResponse,
        ],
    ) -> bootstrap_pb2.HandshakeResponse:
        """Validate discovery identity and select the highest wire version."""
        if request.ByteSize() > contract.MAX_REQUEST_BYTES:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Bootstrap request limit exceeded",
            )
        endpoint_identity = self._endpoint_identity
        if not request.HasField("agent_runtime"):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "agent_runtime is required",
            )
        if not is_canonical_uuid4(request.agent_runtime.runtime_id):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "agent_runtime.runtime_id must be a canonical UUIDv4",
            )
        if not request.agent_runtime.software_version:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "agent_runtime.software_version is required",
            )
        if request.expected_provider_instance_id != str(
            endpoint_identity.provider_instance_id
        ):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Expected Provider identity does not match this endpoint",
            )
        if (
            request.expected_endpoint_generation
            != endpoint_identity.endpoint_generation
        ):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Expected endpoint generation does not match this endpoint",
            )

        try:
            offered_versions = {
                ProtocolVersion(major=version.major, minor=version.minor)
                for version in request.supported_sfp_versions
            }
        except ValueError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "supported_sfp_versions contains an invalid wire version",
            )
        selected_versions = offered_versions.intersection(
            SUPPORTED_SFP_VERSIONS
        )
        if not selected_versions:
            await context.abort(
                grpc.StatusCode.UNIMPLEMENTED,
                "No mutually supported SFP wire version",
            )
        selected_version = max(selected_versions)
        try:
            session_id = self._sessions.negotiate(selected_version)
        except SessionRegistryClosedError:
            await context.abort(
                grpc.StatusCode.UNAVAILABLE, "Provider endpoint is stopping"
            )

        response = bootstrap_pb2.HandshakeResponse(
            provider_instance_id=str(endpoint_identity.provider_instance_id),
            endpoint_generation=endpoint_identity.endpoint_generation,
            selected_sfp_version=bootstrap_pb2.ProtocolVersion(
                major=selected_version.major,
                minor=selected_version.minor,
            ),
            provider_runtime_id=str(self._provider_runtime_id),
            session_id=session_id,
        )
        if response.ByteSize() > contract.MAX_RESPONSE_BYTES:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Bootstrap response limit exceeded",
            )
        return response


def registration(
    *,
    endpoint_identity: ProviderEndpointIdentity,
    provider_runtime_id: UUID,
    sessions: SessionRegistry,
) -> ProcedureRegistration:
    """Build the bounded Bootstrap registration for one generation."""
    service = BootstrapService(
        endpoint_identity=endpoint_identity,
        provider_runtime_id=provider_runtime_id,
        sessions=sessions,
    )

    def install(server: grpc.aio.Server) -> None:
        bootstrap_pb2_grpc.add_BootstrapServiceServicer_to_server(
            service,
            server,
        )

    return ProcedureRegistration(
        name=contract.SERVICE_NAME,
        max_request_bytes=contract.MAX_REQUEST_BYTES,
        max_response_bytes=contract.MAX_RESPONSE_BYTES,
        install=install,
    )
