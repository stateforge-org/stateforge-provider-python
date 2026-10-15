"""Publish and withdraw one generation-owned endpoint descriptor."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID

from stateforge_protocol.sfp.endpoint_discovery.v1 import (
    contract as discovery_contract,
)

from stateforge_provider._runtime.configuration import (
    ProviderRuntimeConfiguration,
)
from stateforge_provider._runtime.errors import ProviderServerError
from stateforge_provider._runtime.filesystem import (
    SecureFileError,
    read_owned_regular_file,
    synchronize_directory,
    write_all,
)
from stateforge_provider._runtime.identity import (
    ProviderEndpointIdentity,
    ProviderIdentityError,
    ProviderIdentityStore,
)


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
            discovery_contract.descriptor_filename(
                self._endpoint_identity.provider_instance_id
            )
        )

    def publish(self, socket_path: Path) -> None:
        """Atomically publish the endpoint only after gRPC is ready."""
        configuration = self._configuration
        identity = self._endpoint_identity
        content = discovery_contract.EndpointDescriptor(
            provider_instance_id=identity.provider_instance_id,
            endpoint_generation=identity.endpoint_generation,
            socket_path=str(socket_path),
        ).to_json_bytes()
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
                descriptor = os.open(
                    temporary_path,
                    flags,
                    discovery_contract.DESCRIPTOR_MODE,
                )
                try:
                    directory_status = (
                        configuration.discovery_directory.lstat()
                    )
                    os.fchown(descriptor, -1, directory_status.st_gid)
                    os.fchmod(
                        descriptor,
                        discovery_contract.DESCRIPTOR_MODE,
                    )
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
                    document.provider_instance_id
                    != identity.provider_instance_id
                    or document.endpoint_generation
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
        if document.provider_instance_id != identity.provider_instance_id:
            raise ProviderServerError(
                "Existing Provider descriptor has a different identity: "
                f"{self.path}"
            )
        return document.endpoint_generation


def _read_descriptor(
    path: Path,
) -> discovery_contract.EndpointDescriptor | None:
    """Read one bounded, Provider-owned regular descriptor without links."""
    try:
        content = read_owned_regular_file(
            path,
            expected_mode=discovery_contract.DESCRIPTOR_MODE,
            maximum_bytes=discovery_contract.MAX_DESCRIPTOR_BYTES,
            resource="Provider descriptor",
        )
    except SecureFileError as error:
        raise ProviderServerError(str(error)) from error
    if content is None:
        return None

    try:
        return discovery_contract.parse_descriptor(content)
    except discovery_contract.EndpointDescriptorContractError as error:
        raise ProviderServerError(
            f"Cannot parse Provider descriptor {path}: {error}"
        ) from error
