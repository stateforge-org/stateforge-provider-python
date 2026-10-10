"""Provide auditable filesystem primitives for Provider runtime state."""

from __future__ import annotations

import os
import stat
from pathlib import Path


class SecureFileError(RuntimeError):
    """Report rejection or failure of a protected runtime file."""


def read_owned_regular_file(
    path: Path,
    *,
    expected_mode: int,
    maximum_bytes: int,
    resource: str,
) -> bytes | None:
    """Read a bounded, process-owned regular file without following links."""
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise SecureFileError(
            f"Cannot open {resource} {path}: {error}"
        ) from error

    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise SecureFileError(f"{resource} is not a regular file: {path}")
        if status.st_uid != os.geteuid():
            raise SecureFileError(
                f"{resource} must be owned by the Provider process: {path}"
            )
        if stat.S_IMODE(status.st_mode) != expected_mode:
            raise SecureFileError(
                f"{resource} mode must be {expected_mode:#05o}: {path}"
            )
        if status.st_size > maximum_bytes:
            raise SecureFileError(
                f"{resource} exceeds {maximum_bytes} bytes: {path}"
            )
        content = os.read(descriptor, maximum_bytes + 1)
        if len(content) > maximum_bytes:
            raise SecureFileError(
                f"{resource} exceeds {maximum_bytes} bytes: {path}"
            )
    except OSError as error:
        raise SecureFileError(
            f"Cannot read {resource} {path}: {error}"
        ) from error
    finally:
        os.close(descriptor)
    return content


def synchronize_directory(directory: Path) -> None:
    """Make a completed directory-entry change durable."""
    descriptor = os.open(directory, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_all(descriptor: int, content: bytes, *, resource: str) -> None:
    """Write complete content despite partial operating-system writes."""
    offset = 0
    while offset < len(content):
        written = os.write(descriptor, content[offset:])
        if written == 0:
            raise OSError(f"{resource} write returned zero bytes")
        offset += written
