"""Author-facing base class for a standalone StateForge Provider process."""

from __future__ import annotations

import asyncio
import contextlib
import signal
from pathlib import Path
from typing import ClassVar, final

from stateforge_rpc._configuration import ProviderRuntimeConfiguration
from stateforge_rpc._manifest import ManifestDeclaration
from stateforge_rpc._server import (
    ProviderServer,
    ProviderServerError,
)
from stateforge_rpc.declarations import (
    Platform,
    ProviderModel,
    RuntimeRequirement,
    Trigger,
)


class Provider:
    """Implement a standalone Provider by subclassing and overriding hooks.

    Set ``identity``, ``display_name``, ``version``, and ``platforms``. Add
    typed models, requirements, triggers, and decorated
    operations as needed. Override lifecycle hooks and start the
    result with :meth:`run` or :meth:`serve`. The runtime owns Provider
    identity persistence, endpoint-generation allocation, Unix sockets,
    descriptors, protobuf adaptation, gRPC services, and SFP negotiation; a
    Provider author never configures those directly.
    """

    identity: ClassVar[str]
    display_name: ClassVar[str]
    version: ClassVar[str]
    platforms: ClassVar[tuple[Platform, ...]]
    configuration_model: ClassVar[type[ProviderModel]] = ProviderModel
    runtime_requirements: ClassVar[tuple[RuntimeRequirement, ...]] = ()
    triggers: ClassVar[tuple[Trigger, ...]] = ()

    def __init__(
        self,
        *,
        discovery_directory: Path | None = None,
        state_directory: Path | None = None,
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
                f"{type(self).__name__}.identity must be a single path segment"
            )
        self._configuration = ProviderRuntimeConfiguration.for_provider(
            identity,
            discovery_directory=discovery_directory,
            state_directory=state_directory,
        )
        self._server = ProviderServer(self._configuration)
        self._shutdown_requested = asyncio.Event()

    async def on_startup(self) -> None:
        """Override to initialize Provider resources before publication."""

    async def on_shutdown(self) -> None:
        """Release resources within the configured shutdown timeout.

        Runs after discovery withdrawal, session invalidation, and transport
        shutdown, before final socket cleanup and runtime-state reset.
        Runs if startup was entered, even if startup or publication failed.
        Must tolerate partially initialized resources and no ready endpoint.
        """

    @final
    def run(self) -> None:
        """Run to completion with an owned event loop and signal handlers."""

        async def run_with_signals() -> None:
            self._install_signal_handlers()
            await self.serve()

        asyncio.run(run_with_signals())

    @final
    async def serve(self) -> None:
        """Validate declarations and serve on the caller's event loop.

        The caller retains signal-handler ownership and may initiate shutdown
        by calling :meth:`request_shutdown`.

        Raises:
            ManifestError: Declarations violate the P1 manifest contract.
            ProviderServerError: Endpoint allocation/publication fails.
        """
        declaration = ManifestDeclaration.discover(
            type(self),
            limits=self._configuration.limits,
        )
        startup_entered = False

        async def startup() -> None:
            nonlocal startup_entered
            startup_entered = True
            await self.on_startup()

        try:
            await self._server.start(
                on_identity_allocated=startup,
                manifest=declaration,
            )
            await self._shutdown_requested.wait()
        finally:
            shutdown_called = False

            async def shutdown_author_resources() -> None:
                nonlocal shutdown_called
                shutdown_called = True
                if startup_entered:
                    async with asyncio.timeout(
                        self._configuration.shutdown_timeout_seconds
                    ):
                        await self.on_shutdown()

            endpoint_failure: BaseException | None = None
            try:
                await self._server.stop(
                    after_transport_stopped=shutdown_author_resources,
                )
            except BaseException as error:
                endpoint_failure = error

            shutdown_failure: BaseException | None = None
            if startup_entered and not shutdown_called:
                try:
                    await shutdown_author_resources()
                except BaseException as error:
                    shutdown_failure = error

            if endpoint_failure is not None:
                if shutdown_failure is not None:
                    endpoint_failure.add_note(
                        "Provider author-resource shutdown also failed: "
                        f"{shutdown_failure}"
                    )
                raise endpoint_failure
            if shutdown_failure is not None:
                raise shutdown_failure

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
