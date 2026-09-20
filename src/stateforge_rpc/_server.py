"""Run the Provider side of the SFP bootstrap protocol.

This module is a private runtime implementation detail. Provider authors use
the public :class:`stateforge_rpc.Provider` base class; they must not import
or configure anything here directly.
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import grpc
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)
from stateforge_protocol.sfp.manifest.v1 import manifest_pb2_grpc

from stateforge_rpc._identity import (
    ProviderEndpointIdentity,
    ProviderIdentityError,
    ProviderIdentityStore,
)
from stateforge_rpc._manifest import ManifestDeclaration
from stateforge_rpc._manifest_service import (
    ManifestService,
    SessionRegistry,
    SessionRegistryClosedError,
)
from stateforge_rpc._schema import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES
from stateforge_rpc.version import ProtocolVersion

_DESCRIPTOR_SCHEMA_VERSION = "1"
_DESCRIPTOR_SUFFIX = ".sfp.json"
_DESCRIPTOR_MODE = 0o640
_SOCKET_MODE = 0o660
_MAXIMUM_ENDPOINT_GENERATION = (2**63) - 1
_UUID_VERSION = 4


class ProviderServerError(RuntimeError):
    """Report failure to start or publish a Provider SFP server."""


@dataclass(frozen=True, slots=True)
class ProviderServerConfiguration:
    """Immutable configuration for one Provider process endpoint."""

    state_directory: Path
    discovery_directory: Path
    supported_sfp_versions: tuple[ProtocolVersion, ...]

    def __post_init__(self) -> None:
        """Validate values used to construct the local endpoint."""
        if not self.supported_sfp_versions:
            raise ValueError("At least one SFP version must be supported")
        if len(set(self.supported_sfp_versions)) != len(
            self.supported_sfp_versions
        ):
            raise ValueError(
                "supported_sfp_versions must not contain duplicates"
            )
        if not self.discovery_directory.is_absolute():
            raise ValueError("discovery_directory must be absolute")
        if not self.state_directory.is_absolute():
            raise ValueError("state_directory must be absolute")


class ProviderServer:
    """Expose the Provider bootstrap service over a Unix domain socket."""

    def __init__(self, configuration: ProviderServerConfiguration) -> None:
        """Create a stopped Provider server."""
        self.configuration = configuration
        self._identity_store = ProviderIdentityStore(
            configuration.state_directory
        )
        self._endpoint_identity: ProviderEndpointIdentity | None = None
        self._runtime_id = uuid4()
        self._server: grpc.aio.Server | None = None
        self._started = False
        self._sessions: SessionRegistry | None = None

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
        return self.configuration.discovery_directory / (
            f"{self.provider_instance_id}{_DESCRIPTOR_SUFFIX}"
        )

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
        manifest: ManifestDeclaration | None = None,
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

        if on_identity_allocated is not None:
            await on_identity_allocated()

        snapshot = (
            manifest.snapshot(self._allocated_identity)
            if manifest is not None
            else None
        )
        sessions = SessionRegistry(self._allocated_identity)
        server = grpc.aio.server(
            options=(
                ("grpc.max_receive_message_length", MAX_REQUEST_BYTES),
                ("grpc.max_send_message_length", MAX_RESPONSE_BYTES),
            )
        )
        bootstrap_pb2_grpc.add_BootstrapServiceServicer_to_server(
            _BootstrapService(
                endpoint_identity=self._allocated_identity,
                provider_runtime_id=self._runtime_id,
                supported_sfp_versions=(
                    self.configuration.supported_sfp_versions
                ),
                sessions=sessions,
            ),
            server,
        )
        if snapshot is not None:
            manifest_pb2_grpc.add_ManifestServiceServicer_to_server(
                ManifestService(snapshot, sessions),
                server,
            )
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
        except BaseException:
            sessions.clear()
            await server.stop(grace=None)
            if owns_socket:
                self._remove_descriptor_if_owned()
                self._remove_socket()
            self._server = None
            raise
        self._started = True

    async def stop(self, *, grace_seconds: float = 5.0) -> None:
        """Stop accepting RPCs and withdraw this endpoint generation."""
        server = self._server
        if not self._started or server is None:
            return
        self._remove_descriptor_if_owned()
        if self._sessions is not None:
            self._sessions.clear()
        await server.stop(grace=grace_seconds)
        self._remove_socket()
        self._server = None
        self._started = False

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
        configuration = self.configuration
        document = {
            "schema_version": _DESCRIPTOR_SCHEMA_VERSION,
            "provider_instance_id": str(self.provider_instance_id),
            "endpoint_generation": self.endpoint_generation,
            "transport": {
                "type": "unix",
                "socket_path": str(self.socket_path),
            },
        }
        content = (json.dumps(document, indent=2) + "\n").encode()
        temporary_path = self.descriptor_path.with_name(
            f".{self.descriptor_path.name}.{self._runtime_id}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC

        with self._identity_store.locked():
            published_generation = self._published_generation()
            if (
                published_generation is not None
                and published_generation >= self.endpoint_generation
            ):
                raise ProviderServerError(
                    "Cannot replace an equal or newer Provider endpoint "
                    f"generation: published={published_generation} "
                    f"candidate={self.endpoint_generation}"
                )

            try:
                descriptor = os.open(temporary_path, flags, _DESCRIPTOR_MODE)
                try:
                    directory_status = (
                        configuration.discovery_directory.lstat()
                    )
                    os.fchown(descriptor, -1, directory_status.st_gid)
                    os.fchmod(descriptor, _DESCRIPTOR_MODE)
                    _write_all(descriptor, content)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.replace(temporary_path, self.descriptor_path)
                _synchronize_directory(configuration.discovery_directory)
            except OSError as error:
                temporary_path.unlink(missing_ok=True)
                raise ProviderServerError(
                    f"Cannot publish Provider descriptor "
                    f"{self.descriptor_path}: {error}"
                ) from error

    def _published_generation(self) -> int | None:
        """Return the currently published generation for this identity."""
        try:
            document = json.loads(self.descriptor_path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as error:
            raise ProviderServerError(
                f"Cannot validate existing Provider descriptor "
                f"{self.descriptor_path}: {error}"
            ) from error
        if not isinstance(document, dict):
            raise ProviderServerError(
                f"Existing Provider descriptor is invalid: "
                f"{self.descriptor_path}"
            )
        if document.get("provider_instance_id") != str(
            self.provider_instance_id
        ):
            raise ProviderServerError(
                "Existing Provider descriptor has a different identity: "
                f"{self.descriptor_path}"
            )
        generation = document.get("endpoint_generation")
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or not 1 <= generation <= _MAXIMUM_ENDPOINT_GENERATION
        ):
            raise ProviderServerError(
                "Existing Provider descriptor has an invalid generation: "
                f"{self.descriptor_path}"
            )
        return generation

    def _remove_descriptor_if_owned(self) -> None:
        """Withdraw only a descriptor that still names this generation."""
        try:
            with self._identity_store.locked():
                try:
                    document = json.loads(self.descriptor_path.read_bytes())
                except (OSError, json.JSONDecodeError):
                    return

                if not isinstance(document, dict):
                    return
                if (
                    document.get("provider_instance_id")
                    != str(self.provider_instance_id)
                    or document.get("endpoint_generation")
                    != self.endpoint_generation
                ):
                    return
                try:
                    self.descriptor_path.unlink()
                    _synchronize_directory(
                        self.configuration.discovery_directory
                    )
                except OSError:
                    return
        except ProviderIdentityError:
            return

    def _remove_socket(self) -> None:
        """Remove the generation-specific socket if it still exists."""
        try:
            self.socket_path.unlink(missing_ok=True)
        except OSError:
            return


class _BootstrapService(bootstrap_pb2_grpc.BootstrapServiceServicer):
    """Implement version-neutral SFP session negotiation."""

    def __init__(
        self,
        *,
        endpoint_identity: ProviderEndpointIdentity,
        provider_runtime_id: UUID,
        supported_sfp_versions: tuple[ProtocolVersion, ...],
        sessions: SessionRegistry,
    ) -> None:
        self._endpoint_identity = endpoint_identity
        self._provider_runtime_id = provider_runtime_id
        self._supported_sfp_versions = supported_sfp_versions
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
        endpoint_identity = self._endpoint_identity
        if not request.HasField("agent_runtime"):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "agent_runtime is required",
            )
        if not _is_canonical_uuid4(request.agent_runtime.runtime_id):
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
            self._supported_sfp_versions
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

        return bootstrap_pb2.HandshakeResponse(
            provider_instance_id=str(endpoint_identity.provider_instance_id),
            endpoint_generation=endpoint_identity.endpoint_generation,
            selected_sfp_version=bootstrap_pb2.ProtocolVersion(
                major=selected_version.major,
                minor=selected_version.minor,
            ),
            provider_runtime_id=str(self._provider_runtime_id),
            session_id=session_id,
        )


def _is_canonical_uuid4(value: str) -> bool:
    """Return whether a string is a canonical lowercase UUIDv4."""
    try:
        identifier = UUID(value)
    except ValueError:
        return False
    return identifier.version == _UUID_VERSION and str(identifier) == value


def _unix_channel_target(path: Path) -> str:
    """Build the gRPC target for an absolute Unix domain socket."""
    return f"unix:{path}"


def _synchronize_directory(directory: Path) -> None:
    """Make a descriptor rename or removal durable on the local filesystem."""
    flags = os.O_RDONLY | os.O_CLOEXEC
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, content: bytes) -> None:
    """Write a complete descriptor document despite partial OS writes."""
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written == 0:
            raise OSError("Descriptor write returned zero bytes")
        offset += written
