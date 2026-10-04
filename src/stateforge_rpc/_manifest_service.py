"""Serve bounded, session-bound manifest reads on the shared SFP endpoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

import grpc
from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from stateforge_protocol.sfp.manifest.v1 import manifest_pb2, manifest_pb2_grpc

from stateforge_rpc._configuration import (
    DEFAULT_RUNTIME_LIMITS,
    ProviderRuntimeLimits,
)
from stateforge_rpc._identity import ProviderEndpointIdentity
from stateforge_rpc._manifest import ManifestSnapshot
from stateforge_rpc._manifest_schema import (
    MANIFEST_MAX_REQUEST_BYTES,
    ManifestError,
    contract_validator,
)
from stateforge_rpc.version import ProtocolVersion


class SessionRegistryClosedError(RuntimeError):
    """Reject new handshakes after generation shutdown begins."""


@dataclass(frozen=True, slots=True)
class _Session:
    endpoint: ProviderEndpointIdentity
    version: ProtocolVersion


class SessionRegistry:
    """Own a bounded set of negotiated sessions for one generation.

    Oldest sessions are invalidated on capacity pressure. Affected clients
    must handshake again. Reads do not refresh or mutate session state.
    All access runs on the server event loop, with no await during mutation.
    """

    def __init__(
        self,
        endpoint: ProviderEndpointIdentity,
        limits: ProviderRuntimeLimits = DEFAULT_RUNTIME_LIMITS,
    ) -> None:
        self._endpoint = endpoint
        self._max_sessions = limits.max_sessions
        self._sessions: dict[str, _Session] = {}
        self._closed = False

    def negotiate(self, version: ProtocolVersion) -> str:
        """Retain a session after successful bootstrap negotiation."""
        if self._closed:
            raise SessionRegistryClosedError("Provider endpoint is stopping")
        identifier = str(uuid4())
        if len(self._sessions) >= self._max_sessions:
            del self._sessions[next(iter(self._sessions))]
        self._sessions[identifier] = _Session(self._endpoint, version)
        return identifier

    def get(self, identifier: str) -> _Session | None:
        """Resolve an exact opaque ID without normalization or fallback."""
        return self._sessions.get(identifier)

    def clear(self) -> None:
        """Invalidate all sessions when this generation stops."""
        self._closed = True
        self._sessions.clear()


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
        if request.ByteSize() > MANIFEST_MAX_REQUEST_BYTES:
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
            return self._snapshot.response(request.expected_session_id)
        except (DecodeError, ManifestError, ValueError):
            await context.abort(
                grpc.StatusCode.INTERNAL, "Manifest snapshot is unavailable"
            )
