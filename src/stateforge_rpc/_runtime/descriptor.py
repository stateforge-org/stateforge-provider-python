"""Publish and withdraw one generation-owned endpoint descriptor."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

from stateforge_rpc._runtime.configuration import ProviderRuntimeConfiguration
from stateforge_rpc._runtime.errors import ProviderServerError
from stateforge_rpc._runtime.filesystem import (
    SecureFileError,
    read_owned_regular_file,
    synchronize_directory,
    write_all,
)
from stateforge_rpc._runtime.identity import (
    ProviderEndpointIdentity,
    ProviderIdentityError,
    ProviderIdentityStore,
    is_allocated_endpoint_generation,
)

_DESCRIPTOR_SCHEMA_VERSION = "1"
_DESCRIPTOR_SUFFIX = ".sfp.json"
_DESCRIPTOR_MODE = 0o640
_MAXIMUM_DESCRIPTOR_BYTES = 4096


class EndpointDescriptor:
    """Own publication of one generation's discovery descriptor."""

    def __init__(
        self,
        *,
        configuration: ProviderRuntimeConfiguration,
        identity_store: ProviderIdentityStore,
        endpoint_identity: ProviderEndpointIdentity,
        runtime_id: UUID,
    ) -> None:
        self._configuration = configuration
        self._identity_store = identity_store
        self._endpoint_identity = endpoint_identity
        self._runtime_id = runtime_id

    @property
    def path(self) -> Path:
        """Return the stable descriptor path for this Provider instance."""
        return self._configuration.discovery_directory / (
            f"{self._endpoint_identity.provider_instance_id}"
            f"{_DESCRIPTOR_SUFFIX}"
        )

    def publish(self, socket_path: Path) -> None:
        """Atomically publish the endpoint only after gRPC is ready."""
        configuration = self._configuration
        identity = self._endpoint_identity
        document = {
            "schema_version": _DESCRIPTOR_SCHEMA_VERSION,
            "provider_instance_id": str(identity.provider_instance_id),
            "endpoint_generation": identity.endpoint_generation,
            "transport": {
                "type": "unix",
                "socket_path": str(socket_path),
            },
        }
        content = (json.dumps(document, indent=2) + "\n").encode()
        temporary_path = self.path.with_name(
            f".{self.path.name}.{self._runtime_id}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC

        with self._identity_store.locked():
            published_generation = self._published_generation()
            if (
                published_generation is not None
                and published_generation >= identity.endpoint_generation
            ):
                raise ProviderServerError(
                    "Cannot replace an equal or newer Provider endpoint "
                    f"generation: published={published_generation} "
                    f"candidate={identity.endpoint_generation}"
                )

            try:
                descriptor = os.open(temporary_path, flags, _DESCRIPTOR_MODE)
                try:
                    directory_status = (
                        configuration.discovery_directory.lstat()
                    )
                    os.fchown(descriptor, -1, directory_status.st_gid)
                    os.fchmod(descriptor, _DESCRIPTOR_MODE)
                    write_all(descriptor, content, resource="Descriptor")
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.replace(temporary_path, self.path)
                synchronize_directory(configuration.discovery_directory)
            except OSError as error:
                temporary_path.unlink(missing_ok=True)
                raise ProviderServerError(
                    f"Cannot publish Provider descriptor {self.path}: {error}"
                ) from error

    def remove_if_owned(self) -> None:
        """Withdraw only a descriptor that still names this generation."""
        identity = self._endpoint_identity
        try:
            with self._identity_store.locked():
                document = _read_descriptor(self.path)
                if document is None:
                    return
                if (
                    document.get("provider_instance_id")
                    != str(identity.provider_instance_id)
                    or document.get("endpoint_generation")
                    != identity.endpoint_generation
                ):
                    return
                self.path.unlink()
                synchronize_directory(self._configuration.discovery_directory)
        except ProviderIdentityError as error:
            raise ProviderServerError(
                f"Cannot lock Provider descriptor cleanup: {error}"
            ) from error
        except OSError as error:
            raise ProviderServerError(
                f"Cannot remove Provider descriptor {self.path}: {error}"
            ) from error

    def _published_generation(self) -> int | None:
        """Return the currently published generation for this identity."""
        document = _read_descriptor(self.path)
        if document is None:
            return None
        identity = self._endpoint_identity
        if document.get("provider_instance_id") != str(
            identity.provider_instance_id
        ):
            raise ProviderServerError(
                "Existing Provider descriptor has a different identity: "
                f"{self.path}"
            )
        generation = document.get("endpoint_generation")
        if not is_allocated_endpoint_generation(generation):
            raise ProviderServerError(
                "Existing Provider descriptor has an invalid generation: "
                f"{self.path}"
            )
        return generation


def _read_descriptor(path: Path) -> dict[str, object] | None:
    """Read one bounded, Provider-owned regular descriptor without links."""
    try:
        content = read_owned_regular_file(
            path,
            expected_mode=_DESCRIPTOR_MODE,
            maximum_bytes=_MAXIMUM_DESCRIPTOR_BYTES,
            resource="Provider descriptor",
        )
    except SecureFileError as error:
        raise ProviderServerError(str(error)) from error
    if content is None:
        return None

    try:
        document = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderServerError(
            f"Cannot parse Provider descriptor {path}: {error}"
        ) from error
    if not isinstance(document, dict):
        raise ProviderServerError(f"Provider descriptor is invalid: {path}")
    return document
