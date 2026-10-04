"""Retain negotiated SFP sessions for one Provider generation."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from stateforge_rpc._runtime.configuration import (
    DEFAULT_RUNTIME_LIMITS,
    ProviderRuntimeLimits,
)
from stateforge_rpc._runtime.identity import ProviderEndpointIdentity
from stateforge_rpc.version import ProtocolVersion


class SessionRegistryClosedError(RuntimeError):
    """Reject new handshakes after generation shutdown begins."""


@dataclass(frozen=True, slots=True)
class Session:
    """Bind one opaque session identifier to endpoint and wire version."""

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
        self._sessions: dict[str, Session] = {}
        self._closed = False

    def negotiate(self, version: ProtocolVersion) -> str:
        """Retain a session after successful bootstrap negotiation."""
        if self._closed:
            raise SessionRegistryClosedError("Provider endpoint is stopping")
        identifier = str(uuid4())
        if len(self._sessions) >= self._max_sessions:
            del self._sessions[next(iter(self._sessions))]
        self._sessions[identifier] = Session(self._endpoint, version)
        return identifier

    def get(self, identifier: str) -> Session | None:
        """Resolve an exact opaque ID without normalization or fallback."""
        return self._sessions.get(identifier)

    def clear(self) -> None:
        """Invalidate all sessions when this generation stops."""
        self._closed = True
        self._sessions.clear()
