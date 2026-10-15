"""Persist Provider identity and allocate endpoint generations."""

from __future__ import annotations

import importlib
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from uuid import UUID, uuid4

from stateforge_protocol.sfp.endpoint_discovery.v1 import (
    contract as discovery_contract,
)

from stateforge_provider._runtime.filesystem import (
    SecureFileError,
    read_owned_regular_file,
    synchronize_directory,
    write_all,
)

_STATE_SCHEMA_VERSION = "1"
_STATE_FILENAME = "identity.json"
_LOCK_FILENAME = ".identity.lock"
_STATE_FILE_MODE = 0o600
_MAXIMUM_STATE_BYTES = 4096
_STATE_FIELDS = {
    "schema_version",
    "provider_instance_id",
    "last_endpoint_generation",
}


class ProviderIdentityError(RuntimeError):
    """Report unusable or exhausted Provider identity state."""


class _AdvisoryFileLocks(Protocol):
    """Describe the POSIX file-locking surface used by the runtime."""

    LOCK_EX: int
    LOCK_UN: int

    def flock(self, descriptor: int, operation: int, /) -> None:
        """Apply or release an advisory lock."""


def _advisory_file_locks() -> _AdvisoryFileLocks:
    """Load POSIX locking only when the Provider runtime starts."""
    try:
        module = importlib.import_module("fcntl")
    except ModuleNotFoundError as error:
        raise ProviderIdentityError(
            "Provider runtime requires POSIX advisory file locking"
        ) from error
    return cast(_AdvisoryFileLocks, module)


def is_canonical_uuid4(value: str) -> bool:
    """Return whether a string is a canonical lowercase UUIDv4."""
    try:
        identifier = UUID(value)
    except ValueError:
        return False
    return (
        identifier.version == discovery_contract.PROVIDER_INSTANCE_UUID_VERSION
        and str(identifier) == value
    )


@dataclass(frozen=True, slots=True)
class ProviderEndpointIdentity:
    """Identify one generation of a stable Provider installation."""

    provider_instance_id: UUID
    endpoint_generation: int


@dataclass(frozen=True, slots=True)
class _ProviderIdentityState:
    """Store the stable identity and last allocated endpoint generation."""

    provider_instance_id: UUID
    last_endpoint_generation: int

    def __post_init__(self) -> None:
        """Reject identity state outside the persisted format."""
        if (
            self.provider_instance_id.version
            != discovery_contract.PROVIDER_INSTANCE_UUID_VERSION
        ):
            raise ValueError("provider_instance_id must be a UUIDv4")
        generation = self.last_endpoint_generation
        if (
            not isinstance(generation, int)
            or isinstance(generation, bool)
            or not 0
            <= generation
            <= discovery_contract.MAX_ENDPOINT_GENERATION
        ):
            raise ValueError(
                "last_endpoint_generation must be a non-negative signed "
                "64-bit integer"
            )


class ProviderIdentityStore:
    """Manage one protected identity file shared by Provider generations."""

    def __init__(self, state_directory: Path) -> None:
        """Create a store rooted in an absolute Provider state directory."""
        if not state_directory.is_absolute():
            raise ValueError("Provider state_directory must be absolute")
        self.state_directory = state_directory
        self.state_path = state_directory / _STATE_FILENAME
        self.lock_path = state_directory / _LOCK_FILENAME

    def allocate_endpoint(self) -> ProviderEndpointIdentity:
        """Load the stable identity and allocate its next generation."""
        self.prepare()
        with self.locked():
            state = self._load_state()
            if state is None:
                state = _ProviderIdentityState(
                    provider_instance_id=uuid4(),
                    last_endpoint_generation=0,
                )
            if (
                state.last_endpoint_generation
                == discovery_contract.MAX_ENDPOINT_GENERATION
            ):
                raise ProviderIdentityError(
                    "Provider endpoint generation space is exhausted"
                )

            endpoint_generation = state.last_endpoint_generation + 1
            self._write_state(
                _ProviderIdentityState(
                    provider_instance_id=state.provider_instance_id,
                    last_endpoint_generation=endpoint_generation,
                )
            )

        return ProviderEndpointIdentity(
            provider_instance_id=state.provider_instance_id,
            endpoint_generation=endpoint_generation,
        )

    def prepare(self) -> None:
        """Create or validate the Provider-owned state directory."""
        try:
            self.state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            status = self.state_directory.lstat()
        except OSError as error:
            raise ProviderIdentityError(
                f"Cannot prepare Provider state directory "
                f"{self.state_directory}: {error}"
            ) from error

        if stat.S_ISLNK(status.st_mode):
            raise ProviderIdentityError(
                "Provider state directory must not be a symbolic link: "
                f"{self.state_directory}"
            )
        if not stat.S_ISDIR(status.st_mode):
            raise ProviderIdentityError(
                f"Provider state path is not a directory: "
                f"{self.state_directory}"
            )
        if status.st_uid != os.geteuid():
            raise ProviderIdentityError(
                "Provider state directory must be owned by the Provider "
                f"process: {self.state_directory}"
            )
        if status.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ProviderIdentityError(
                "Provider state directory must not be writable by group or "
                f"others: {self.state_directory}"
            )

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Hold the installation lock across an identity-sensitive update."""
        file_locks = _advisory_file_locks()
        flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.lock_path, flags, _STATE_FILE_MODE)
        except OSError as error:
            raise ProviderIdentityError(
                f"Cannot open Provider identity lock {self.lock_path}: {error}"
            ) from error

        try:
            status = os.fstat(descriptor)
            if not stat.S_ISREG(status.st_mode):
                raise ProviderIdentityError(
                    f"Provider identity lock is not a regular file: "
                    f"{self.lock_path}"
                )
            if status.st_uid != os.geteuid():
                raise ProviderIdentityError(
                    "Provider identity lock must be owned by the Provider "
                    f"process: {self.lock_path}"
                )
            if stat.S_IMODE(status.st_mode) != _STATE_FILE_MODE:
                raise ProviderIdentityError(
                    f"Provider identity lock mode must be "
                    f"{_STATE_FILE_MODE:#05o}: {self.lock_path}"
                )
            file_locks.flock(descriptor, file_locks.LOCK_EX)
        except OSError as error:
            os.close(descriptor)
            raise ProviderIdentityError(
                "Cannot lock Provider identity state "
                f"{self.lock_path}: {error}"
            ) from error
        except BaseException:
            os.close(descriptor)
            raise

        try:
            yield
        finally:
            file_locks.flock(descriptor, file_locks.LOCK_UN)
            os.close(descriptor)

    # Keep persisted-state validation visible as one security review surface.
    def _load_state(self) -> _ProviderIdentityState | None:
        """Read and validate the complete identity document."""
        try:
            content = read_owned_regular_file(
                self.state_path,
                expected_mode=_STATE_FILE_MODE,
                maximum_bytes=_MAXIMUM_STATE_BYTES,
                resource="Provider identity state",
            )
        except SecureFileError as error:
            raise ProviderIdentityError(str(error)) from error
        if content is None:
            return None

        try:
            document = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProviderIdentityError(
                f"Cannot parse Provider identity state {self.state_path}: "
                f"{error}"
            ) from error
        if not isinstance(document, dict) or set(document) != _STATE_FIELDS:
            raise ProviderIdentityError(
                f"Provider identity state has an invalid schema: "
                f"{self.state_path}"
            )
        if document["schema_version"] != _STATE_SCHEMA_VERSION:
            raise ProviderIdentityError(
                "Unsupported Provider identity schema_version: "
                f"{document['schema_version']}"
            )

        provider_instance_value = document["provider_instance_id"]
        endpoint_generation = document["last_endpoint_generation"]
        if not isinstance(provider_instance_value, str):
            raise ProviderIdentityError(
                "Provider identity provider_instance_id must be a UUIDv4"
            )
        try:
            provider_instance_id = UUID(provider_instance_value)
            state = _ProviderIdentityState(
                provider_instance_id=provider_instance_id,
                last_endpoint_generation=endpoint_generation,
            )
        except (TypeError, ValueError) as error:
            raise ProviderIdentityError(
                f"Provider identity state contains invalid values: "
                f"{self.state_path}"
            ) from error
        if str(provider_instance_id) != provider_instance_value:
            raise ProviderIdentityError(
                "Provider identity provider_instance_id must be canonical"
            )
        return state

    def _write_state(self, state: _ProviderIdentityState) -> None:
        """Atomically replace and synchronize the identity document."""
        document = {
            "schema_version": _STATE_SCHEMA_VERSION,
            "provider_instance_id": str(state.provider_instance_id),
            "last_endpoint_generation": state.last_endpoint_generation,
        }
        content = (json.dumps(document, indent=2) + "\n").encode()
        temporary_path = self.state_directory / (
            f".{_STATE_FILENAME}.{uuid4()}.tmp"
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW

        try:
            descriptor = os.open(temporary_path, flags, _STATE_FILE_MODE)
            try:
                os.fchmod(descriptor, _STATE_FILE_MODE)
                write_all(descriptor, content, resource="Identity-state")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary_path, self.state_path)
            synchronize_directory(self.state_directory)
        except OSError as error:
            temporary_path.unlink(missing_ok=True)
            raise ProviderIdentityError(
                f"Cannot persist Provider identity state {self.state_path}: "
                f"{error}"
            ) from error
