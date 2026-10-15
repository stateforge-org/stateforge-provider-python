"""Serve bounded, session-bound Manifest reads on the shared SFP endpoint."""

from __future__ import annotations

import asyncio

import grpc
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from stateforge_protocol.sfp.manifest.v1 import (
    contract,
    manifest_pb2,
    manifest_pb2_grpc,
)

from stateforge_provider._runtime.grpc import ProcedureRegistration
from stateforge_provider._runtime.sessions import SessionRegistry
from stateforge_provider._services.manifest.declaration import ManifestSnapshot
from stateforge_provider._services.manifest.schema import (
    ManifestError,
    contract_validator,
)
from stateforge_provider.version import ProtocolVersion


class ManifestService(manifest_pb2_grpc.ManifestServiceServicer):
    """Serve one frozen declaration with a separate header for each session."""

    def __init__(
        self, snapshot: ManifestSnapshot, sessions: SessionRegistry
    ) -> None:
        self._snapshot = snapshot
        self._sessions = sessions
        self._validator = contract_validator("getManifestRequest")

    async def GetManifest(  # noqa: N802
        self,
        request: manifest_pb2.GetManifestRequest,
        context: grpc.aio.ServicerContext[
            manifest_pb2.GetManifestRequest, manifest_pb2.GetManifestResponse
        ],
    ) -> manifest_pb2.GetManifestResponse:
        """Check syntax, session, and compatibility before copying."""
        if request.ByteSize() > contract.MAX_REQUEST_BYTES:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Manifest request limit exceeded",
            )
        projected = MessageToDict(
            request, always_print_fields_with_no_presence=True
        )
        if not self._validator.is_valid(projected):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT, "Invalid manifest request"
            )
        session = self._sessions.get(request.expected_session_id)
        if session is None or (
            request.expected_provider_instance_id
            != str(session.endpoint.provider_instance_id)
            or request.expected_endpoint_generation
            != session.endpoint.endpoint_generation
        ):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Manifest session is not active for this endpoint",
            )
        if (
            session.version != ProtocolVersion(1, 0)
            or 1 not in request.supported_manifest_schema_versions
        ):
            await context.abort(
                grpc.StatusCode.UNIMPLEMENTED,
                "No mutually supported manifest schema",
            )
        # Give transport cancellation a checkpoint before allocating a reply.
        await asyncio.sleep(0)
        if context.cancelled():
            raise asyncio.CancelledError
        if self._sessions.get(request.expected_session_id) is not session:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Manifest session is no longer active",
            )
        try:
            response = self._snapshot.response(request.expected_session_id)
        except (DecodeError, ManifestError, ValueError):
            await context.abort(
                grpc.StatusCode.INTERNAL, "Manifest snapshot is unavailable"
            )
        if response.ByteSize() > contract.MAX_RESPONSE_BYTES:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Manifest response limit exceeded",
            )
        return response


def registration(
    snapshot: ManifestSnapshot,
    sessions: SessionRegistry,
) -> ProcedureRegistration:
    """Build the bounded Manifest registration for one generation."""
    service = ManifestService(snapshot, sessions)

    def install(server: grpc.aio.Server) -> None:
        manifest_pb2_grpc.add_ManifestServiceServicer_to_server(
            service,
            server,
        )

    return ProcedureRegistration(
        name=contract.SERVICE_NAME,
        max_request_bytes=contract.MAX_REQUEST_BYTES,
        max_response_bytes=contract.MAX_RESPONSE_BYTES,
        install=install,
    )
