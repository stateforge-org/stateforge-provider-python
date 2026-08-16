"""Run the Provider side of the SFP bootstrap protocol."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import grpc
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)

from stateforge_rpc.version import ProtocolVersion

_DESCRIPTOR_SCHEMA_VERSION = "1"
_DESCRIPTOR_SUFFIX = ".sfp.json"
_MAXIMUM_ENDPOINT_GENERATION = (2**63) - 1
_UUID_VERSION = 4


class ProviderServerError(RuntimeError):
    """Report failure to start or publish a Provider SFP server."""


@dataclass(frozen=True, slots=True)
class ProviderServerConfiguration:
    """Immutable configuration for one Provider process endpoint."""

    provider_instance_id: UUID
    endpoint_generation: int
    discovery_directory: Path
    supported_sfp_versions: tuple[ProtocolVersion, ...]

    def __post_init__(self) -> None:
        """Validate values used to construct the local endpoint."""
        if self.provider_instance_id.version != _UUID_VERSION:
            raise ValueError("provider_instance_id must be a UUIDv4")
        if not 1 <= self.endpoint_generation <= _MAXIMUM_ENDPOINT_GENERATION:
            raise ValueError(
                "endpoint_generation must be a positive signed 64-bit integer"
            )
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


class ProviderServer:
    """Expose the Provider bootstrap service over a Unix domain socket."""

    def __init__(self, configuration: ProviderServerConfiguration) -> None:
        """Create a stopped Provider server."""
        self.configuration = configuration
        self._runtime_id = uuid4()
        self._server = grpc.aio.server()
        self._started = False
        bootstrap_pb2_grpc.add_BootstrapServiceServicer_to_server(
            _BootstrapService(
                configuration=configuration,
                provider_runtime_id=self._runtime_id,
            ),
            self._server,
        )

    @property
    def socket_path(self) -> Path:
        """Return the generation-specific Unix socket path."""
        configuration = self.configuration
        return configuration.discovery_directory / (
            f"{configuration.provider_instance_id}."
            f"{configuration.endpoint_generation}.sock"
        )

    @property
    def descriptor_path(self) -> Path:
        """Return the stable descriptor path for this Provider instance."""
        return self.configuration.discovery_directory / (
            f"{self.configuration.provider_instance_id}{_DESCRIPTOR_SUFFIX}"
        )

    async def start(self) -> None:
        """Start gRPC and atomically advertise the ready endpoint."""
        if self._started:
            raise ProviderServerError("Provider server is already running")

        self._prepare_socket_path()
        bound_port = self._server.add_insecure_port(
            _unix_channel_target(self.socket_path)
        )
        if bound_port == 0:
            raise ProviderServerError(
                f"Cannot bind Provider endpoint: {self.socket_path}"
            )

        try:
            await self._server.start()
            self._publish_descriptor()
        except BaseException:
            await self._server.stop(grace=None)
            self._remove_socket()
            raise
        self._started = True

    async def stop(self, *, grace_seconds: float = 5.0) -> None:
        """Stop accepting RPCs and withdraw this endpoint generation."""
        if not self._started:
            return
        self._remove_descriptor_if_owned()
        await self._server.stop(grace=grace_seconds)
        self._remove_socket()
        self._started = False

    async def wait_for_termination(self) -> None:
        """Wait until the underlying gRPC server terminates."""
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
        """Remove only a stale socket at this generation-specific path."""
        try:
            status = self.socket_path.lstat()
        except FileNotFoundError:
            return
        except OSError as error:
            raise ProviderServerError(
                f"Cannot inspect Provider socket {self.socket_path}: {error}"
            ) from error

        if not stat.S_ISSOCK(status.st_mode):
            raise ProviderServerError(
                "Provider endpoint path exists and is not a socket: "
                f"{self.socket_path}"
            )
        try:
            self.socket_path.unlink()
        except OSError as error:
            raise ProviderServerError(
                f"Cannot remove stale Provider socket {self.socket_path}: "
                f"{error}"
            ) from error

    def _publish_descriptor(self) -> None:
        """Atomically publish the endpoint only after gRPC is ready."""
        configuration = self.configuration
        document = {
            "schema_version": _DESCRIPTOR_SCHEMA_VERSION,
            "provider_instance_id": str(configuration.provider_instance_id),
            "endpoint_generation": configuration.endpoint_generation,
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

        try:
            descriptor = os.open(temporary_path, flags, 0o640)
            try:
                os.write(descriptor, content)
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

    def _remove_descriptor_if_owned(self) -> None:
        """Withdraw only a descriptor that still names this generation."""
        try:
            document = json.loads(self.descriptor_path.read_bytes())
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(document, dict):
            return
        if (
            document.get("provider_instance_id")
            != str(self.configuration.provider_instance_id)
            or document.get("endpoint_generation")
            != self.configuration.endpoint_generation
        ):
            return
        try:
            self.descriptor_path.unlink()
            _synchronize_directory(self.configuration.discovery_directory)
        except OSError:
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
        configuration: ProviderServerConfiguration,
        provider_runtime_id: UUID,
    ) -> None:
        self._configuration = configuration
        self._provider_runtime_id = provider_runtime_id

    async def Handshake(  # noqa: N802
        self,
        request: bootstrap_pb2.HandshakeRequest,
        context: grpc.aio.ServicerContext[
            bootstrap_pb2.HandshakeRequest,
            bootstrap_pb2.HandshakeResponse,
        ],
    ) -> bootstrap_pb2.HandshakeResponse:
        """Validate discovery identity and select the highest wire version."""
        configuration = self._configuration
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
            configuration.provider_instance_id
        ):
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "Expected Provider identity does not match this endpoint",
            )
        if (
            request.expected_endpoint_generation
            != configuration.endpoint_generation
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
            configuration.supported_sfp_versions
        )
        if not selected_versions:
            await context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                "No mutually supported SFP wire version",
            )
        selected_version = max(selected_versions)

        return bootstrap_pb2.HandshakeResponse(
            provider_instance_id=str(configuration.provider_instance_id),
            endpoint_generation=configuration.endpoint_generation,
            selected_sfp_version=bootstrap_pb2.ProtocolVersion(
                major=selected_version.major,
                minor=selected_version.minor,
            ),
            provider_runtime_id=str(self._provider_runtime_id),
            session_id=str(uuid4()),
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
