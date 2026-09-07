"""Author-facing base class for a standalone StateForge Provider process."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from pathlib import Path
from typing import ClassVar, final

from stateforge_rpc._server import (
    ProviderServer,
    ProviderServerConfiguration,
    ProviderServerError,
)
from stateforge_rpc.version import SUPPORTED_SFP_VERSIONS, ProtocolVersion

_DEFAULT_DISCOVERY_DIRECTORY = Path("/run/stateforge-agent/providers")
_DEFAULT_STATE_ROOT = Path("/var/lib/stateforge-providers")


class Provider:
    """Implement a standalone Provider by subclassing and overriding hooks.

    Set the ``identity`` class attribute to a namespaced Provider type
    identifier, override the lifecycle hooks a Provider needs, and start the
    result with :meth:`run` or :meth:`serve`. The runtime owns Provider
    identity persistence, endpoint-generation allocation, Unix sockets,
    descriptors, protobuf adaptation, gRPC services, and SFP negotiation; a
    Provider author never configures those directly.
    """

    identity: ClassVar[str]

    def __init__(
        self,
        *,
        discovery_directory: Path | None = None,
        state_directory: Path | None = None,
        supported_sfp_versions: tuple[ProtocolVersion, ...] | None = None,
    ) -> None:
        """Bind this Provider to its default or overridden endpoint paths.

        The keyword-only overrides exist for local development, testing, and
        non-standard deployments. The reference defaults are the production
        Agent discovery directory (``/run/stateforge-agent/providers``) and a
        per-identity persistent state directory
        (``/var/lib/stateforge-providers/<identity>``); a Provider author does
        not need to pass any of them.
        """
        identity = getattr(type(self), "identity", None)
        if not isinstance(identity, str) or not identity:
            raise ProviderServerError(
                f"{type(self).__name__} must declare a non-empty 'identity'"
            )
        if "/" in identity or "\\" in identity or identity in {".", ".."}:
            raise ProviderServerError(
                f"{type(self).__name__}.identity must be a single path "
                f"segment, not {identity!r}"
            )
        self._configuration = ProviderServerConfiguration(
            state_directory=(
                state_directory
                if state_directory is not None
                else _DEFAULT_STATE_ROOT / identity
            ),
            discovery_directory=(
                discovery_directory
                if discovery_directory is not None
                else _DEFAULT_DISCOVERY_DIRECTORY
            ),
            supported_sfp_versions=(
                supported_sfp_versions
                if supported_sfp_versions is not None
                else SUPPORTED_SFP_VERSIONS
            ),
        )
        self._server = ProviderServer(self._configuration)
        self._shutdown_requested = asyncio.Event()

    async def on_startup(self) -> None:
        """Override to initialize Provider resources before publication."""

    async def on_shutdown(self) -> None:
        """Override to release Provider resources during shutdown."""

    @final
    def run(self) -> None:
        """Run this Provider to completion, owning a new event loop."""
        asyncio.run(self.serve())

    @final
    async def serve(self) -> None:
        """Run this Provider to completion on the caller's event loop."""
        await self._server.start(on_identity_allocated=self.on_startup)
        self._install_signal_handlers()
        try:
            await self._shutdown_requested.wait()
        finally:
            await self.on_shutdown()
            await self._server.stop()

    @final
    def request_shutdown(self) -> None:
        """Signal a running Provider to begin graceful shutdown."""
        self._shutdown_requested.set()

    def _install_signal_handlers(self) -> None:
        """Request graceful shutdown on SIGINT/SIGTERM where supported."""
        loop = asyncio.get_running_loop()
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, ValueError):
                loop.add_signal_handler(signal_number, self.request_shutdown)
