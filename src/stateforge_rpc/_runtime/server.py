"""Run the shared Provider-side SFP endpoint.

The endpoint hosts version-neutral bootstrap negotiation and the negotiated
SFP procedure services. This module is a private runtime implementation
detail. Provider authors use the public :class:`stateforge_rpc.Provider` base
class; they must not import or configure anything here directly.
"""

from __future__ import annotations

import logging
import os
import stat
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import grpc

from stateforge_rpc._runtime.configuration import ProviderRuntimeConfiguration
from stateforge_rpc._runtime.descriptor import EndpointDescriptor
from stateforge_rpc._runtime.errors import ProviderServerError
from stateforge_rpc._runtime.filesystem import (
    synchronize_directory,
)
from stateforge_rpc._runtime.grpc import (
    ProcedureRegistration,
    create_server,
)
from stateforge_rpc._runtime.identity import (
    ProviderEndpointIdentity,
    ProviderIdentityError,
    ProviderIdentityStore,
)
from stateforge_rpc._runtime.sessions import SessionRegistry
from stateforge_rpc._services.bootstrap.service import (
    registration as bootstrap_registration,
)

_SOCKET_MODE = 0o660
_LOGGER = logging.getLogger(__name__)

ProcedureFactory = Callable[
    [ProviderEndpointIdentity, SessionRegistry],
    Sequence[ProcedureRegistration],
]


@dataclass(frozen=True, slots=True)
class _SocketIdentity:
    """Identify the exact filesystem socket created for this runtime."""

    device: int
    inode: int
    owner: int

    @classmethod
    def capture(cls, status: os.stat_result) -> _SocketIdentity:
        """Capture the stable fields used before removing a socket."""
        return cls(status.st_dev, status.st_ino, status.st_uid)


class ProviderServer:
    """Host the shared Provider-side SFP endpoint on a Unix domain socket."""

    def __init__(self, configuration: ProviderRuntimeConfiguration) -> None:
        """Create a stopped Provider server."""
        self.configuration = configuration
        self._identity_store = ProviderIdentityStore(
            configuration.state_directory
        )
        self._endpoint_identity: ProviderEndpointIdentity | None = None
        self._runtime_id = uuid4()
        self._descriptor: EndpointDescriptor | None = None
        self._server: grpc.aio.Server | None = None
        self._started = False
        self._sessions: SessionRegistry | None = None
        self._socket_identity: _SocketIdentity | None = None

    @property
    def provider_instance_id(self) -> UUID:
        """Return the stable Provider identity after endpoint allocation."""
        return self._allocated_identity.provider_instance_id

    @property
    def endpoint_generation(self) -> int:
        """Return the allocated endpoint generation."""
        return self._allocated_identity.endpoint_generation

    @property
    def socket_path(self) -> Path:
        """Return the generation-specific Unix socket path."""
        configuration = self.configuration
        return configuration.discovery_directory / (
            f"{self.provider_instance_id}.{self.endpoint_generation}.sock"
        )

    @property
    def descriptor_path(self) -> Path:
        """Return the stable descriptor path for this Provider instance."""
        descriptor = self._descriptor
        if descriptor is None:
            raise ProviderServerError(
                "Provider endpoint descriptor has not been allocated; start "
                "the server first"
            )
        return descriptor.path

    @property
    def _allocated_identity(self) -> ProviderEndpointIdentity:
        """Return the current endpoint identity or reject premature access."""
        if self._endpoint_identity is None:
            raise ProviderServerError(
                "Provider endpoint identity has not been allocated; start the "
                "server first"
            )
        return self._endpoint_identity

    async def start(
        self,
        *,
        on_identity_allocated: Callable[[], Awaitable[None]] | None = None,
        procedure_factory: ProcedureFactory | None = None,
    ) -> None:
        """Start gRPC and atomically advertise the ready endpoint.

        ``on_identity_allocated`` runs after the stable identity and endpoint
        generation are allocated but before gRPC binds, matching the runtime
        lifecycle order the Provider-author framework depends on.
        """
        if self._started:
            raise ProviderServerError("Provider server is already running")

        try:
            self._endpoint_identity = self._identity_store.allocate_endpoint()
        except ProviderIdentityError as error:
            raise ProviderServerError(
                f"Cannot allocate Provider endpoint identity: {error}"
            ) from error

        self._descriptor = EndpointDescriptor(
            configuration=self.configuration,
            identity_store=self._identity_store,
            endpoint_identity=self._allocated_identity,
            runtime_id=self._runtime_id,
        )

        if on_identity_allocated is not None:
            await on_identity_allocated()

        sessions = SessionRegistry(
            self._allocated_identity,
            self.configuration.limits,
        )
        registrations = [
            bootstrap_registration(
                endpoint_identity=self._allocated_identity,
                provider_runtime_id=self._runtime_id,
                sessions=sessions,
            )
        ]
        if procedure_factory is not None:
            registrations.extend(
                procedure_factory(self._allocated_identity, sessions)
            )
        server = create_server(registrations)
        self._sessions = sessions
        self._server = server
        owns_socket = False
        try:
            self._prepare_socket_path()
            bound_port = server.add_insecure_port(
                _unix_channel_target(self.socket_path)
            )
            if bound_port == 0:
                raise ProviderServerError(
                    f"Cannot bind Provider endpoint: {self.socket_path}"
                )
            owns_socket = True
            await server.start()
            self._secure_socket()
            self._publish_descriptor()
        except BaseException as error:
            (
                transport_failure,
                _,
                cleanup_failures,
            ) = await self._teardown(
                server,
                grace_seconds=None,
                remove_endpoint=owns_socket,
            )
            failures = cleanup_failures
            if transport_failure is not None:
                failures = [("gRPC shutdown", transport_failure), *failures]
            _annotate_failure(error, failures)
            raise
        self._started = True

    async def stop(
        self,
        *,
        grace_seconds: float | None = None,
        after_transport_stopped: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Withdraw, stop RPCs, run a callback, then remove the endpoint."""
        server = self._server
        if not self._started or server is None:
            if after_transport_stopped is not None:
                await after_transport_stopped()
            return
        (
            transport_failure,
            callback_failure,
            cleanup_failures,
        ) = await self._teardown(
            server,
            grace_seconds=(
                grace_seconds
                if grace_seconds is not None
                else self.configuration.shutdown_timeout_seconds
            ),
            remove_endpoint=True,
            after_transport_stopped=after_transport_stopped,
        )
        if transport_failure is not None:
            if callback_failure is not None:
                cleanup_failures.insert(
                    0, ("post-transport callback", callback_failure)
                )
            _annotate_failure(transport_failure, cleanup_failures)
            raise transport_failure
        if callback_failure is not None:
            _annotate_failure(callback_failure, cleanup_failures)
            raise callback_failure
        if cleanup_failures:
            _raise_cleanup_failures(cleanup_failures)

    async def _teardown(
        self,
        server: grpc.aio.Server,
        *,
        grace_seconds: float | None,
        remove_endpoint: bool,
        after_transport_stopped: Callable[[], Awaitable[None]] | None = None,
    ) -> tuple[
        BaseException | None,
        BaseException | None,
        list[tuple[str, BaseException]],
    ]:
        """Attempt every shutdown phase and always reset runtime state."""
        cleanup_failures: list[tuple[str, BaseException]] = []
        transport_failure: BaseException | None = None
        callback_failure: BaseException | None = None

        if remove_endpoint:
            try:
                self._remove_descriptor_if_owned()
            except Exception as error:
                cleanup_failures.append(("descriptor withdrawal", error))
        if self._sessions is not None:
            try:
                self._sessions.clear()
            except Exception as error:
                cleanup_failures.append(("session invalidation", error))
        try:
            await server.stop(grace=grace_seconds)
        except BaseException as error:
            transport_failure = error
        else:
            if after_transport_stopped is not None:
                try:
                    await after_transport_stopped()
                except BaseException as error:
                    callback_failure = error
        finally:
            if remove_endpoint:
                try:
                    self._remove_socket()
                except Exception as error:
                    cleanup_failures.append(("socket removal", error))
            self._server = None
            self._sessions = None
            self._socket_identity = None
            self._started = False

        return transport_failure, callback_failure, cleanup_failures

    async def wait_for_termination(self) -> None:
        """Wait until the underlying gRPC server terminates."""
        if self._server is None:
            raise ProviderServerError("Provider server is not running")
        await self._server.wait_for_termination()

    async def __aenter__(self) -> ProviderServer:
        """Start the server when entering an asynchronous context."""
        await self.start()
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> None:
        """Stop the server when leaving an asynchronous context."""
        del exception_type, exception, traceback
        await self.stop()

    def _prepare_socket_path(self) -> None:
        """Reject an occupied generation-specific socket path."""
        try:
            status = self.socket_path.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise ProviderServerError(
                f"Cannot inspect Provider socket {self.socket_path}: {error}"
            ) from error

        entry_type = "socket" if stat.S_ISSOCK(status.st_mode) else "file"
        raise ProviderServerError(
            f"Provider endpoint path is already occupied by a {entry_type}: "
            f"{self.socket_path}"
        )

    def _secure_socket(self) -> None:
        """Apply and verify the protected SFP socket ownership contract."""
        try:
            directory_status = self.configuration.discovery_directory.lstat()
            socket_status = self.socket_path.lstat()
            if not stat.S_ISDIR(directory_status.st_mode):
                raise ProviderServerError(
                    "Provider discovery path is not a directory: "
                    f"{self.configuration.discovery_directory}"
                )
            if not stat.S_ISSOCK(socket_status.st_mode):
                raise ProviderServerError(
                    f"Provider endpoint is not a socket: {self.socket_path}"
                )
            if socket_status.st_uid != os.geteuid():
                raise ProviderServerError(
                    "Provider endpoint is not owned by the Provider process: "
                    f"{self.socket_path}"
                )
            socket_identity = _SocketIdentity.capture(socket_status)
            self._socket_identity = socket_identity

            os.chown(
                self.socket_path,
                -1,
                directory_status.st_gid,
                follow_symlinks=False,
            )
            os.chmod(
                self.socket_path,
                _SOCKET_MODE,
                follow_symlinks=False,
            )
            secured_status = self.socket_path.lstat()
        except OSError as error:
            raise ProviderServerError(
                f"Cannot secure Provider socket {self.socket_path}: {error}"
            ) from error

        if (
            not stat.S_ISSOCK(secured_status.st_mode)
            or _SocketIdentity.capture(secured_status) != socket_identity
            or secured_status.st_uid != os.geteuid()
            or secured_status.st_gid != directory_status.st_gid
            or stat.S_IMODE(secured_status.st_mode) != _SOCKET_MODE
        ):
            raise ProviderServerError(
                "Provider socket ownership or permissions changed while "
                f"securing it: {self.socket_path}"
            )

    def _publish_descriptor(self) -> None:
        """Atomically publish the endpoint only after gRPC is ready."""
        descriptor = self._descriptor
        if descriptor is None:
            raise ProviderServerError(
                "Provider endpoint descriptor has not been allocated"
            )
        descriptor.publish(self.socket_path)

    def _remove_descriptor_if_owned(self) -> None:
        """Withdraw only a descriptor that still names this generation."""
        descriptor = self._descriptor
        if descriptor is not None:
            descriptor.remove_if_owned()

    def _remove_socket(self) -> None:
        """Remove only the exact generation-specific socket we secured."""
        try:
            status = self.socket_path.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise ProviderServerError(
                f"Cannot inspect Provider socket {self.socket_path}: {error}"
            ) from error

        expected = self._socket_identity
        if (
            expected is None
            or not stat.S_ISSOCK(status.st_mode)
            or status.st_uid != os.geteuid()
            or _SocketIdentity.capture(status) != expected
        ):
            raise ProviderServerError(
                "Provider socket changed before cleanup; refusing to remove "
                f"{self.socket_path}"
            )
        try:
            self.socket_path.unlink()
            synchronize_directory(self.configuration.discovery_directory)
        except OSError as error:
            raise ProviderServerError(
                f"Cannot remove Provider socket {self.socket_path}: {error}"
            ) from error


def _annotate_failure(
    primary: BaseException,
    failures: Sequence[tuple[str, BaseException]],
) -> None:
    """Preserve a primary failure while making teardown failures visible."""
    for phase, error in failures:
        primary.add_note(f"Provider teardown failed during {phase}: {error}")
        _LOGGER.error(
            "Provider teardown failed during %s",
            phase,
            exc_info=(type(error), error, error.__traceback__),
        )


def _raise_cleanup_failures(
    failures: Sequence[tuple[str, BaseException]],
) -> None:
    """Raise one public error after all independent cleanup attempts."""
    phases = ", ".join(phase for phase, _ in failures)
    error = ProviderServerError(f"Provider cleanup failed during: {phases}")
    for phase, cause in failures:
        error.add_note(f"{phase}: {cause}")
    raise error from failures[0][1]


def _unix_channel_target(path: Path) -> str:
    """Build the gRPC target for an absolute Unix domain socket."""
    return f"unix:{path}"
