"""Tests for the author-facing Provider base class and its lifecycle."""

import asyncio
import inspect
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import grpc
import pytest

from stateforge_rpc import Provider, ProviderServerError

_DEFAULT_DISCOVERY_DIRECTORY = Path("/run/stateforge-agent/providers")
_DEFAULT_STATE_ROOT = Path("/var/lib/stateforge-providers")


@pytest.fixture
def endpoint_directory() -> Iterator[Path]:
    directory = Path(tempfile.mkdtemp(prefix="sfp-provider-", dir="/tmp"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class _RecordingProvider(Provider):
    identity = "stateforge.test-recorder"

    def __init__(
        self,
        *,
        discovery_directory: Path | None = None,
        state_directory: Path | None = None,
    ) -> None:
        """Wrap Provider.__init__ to also track lifecycle-hook events."""
        super().__init__(
            discovery_directory=discovery_directory,
            state_directory=state_directory,
        )
        self.events: list[str] = []
        self.started = asyncio.Event()

    async def on_startup(self) -> None:
        assert not self._server.descriptor_path.exists()
        self.events.append("startup")
        self.started.set()

    async def on_shutdown(self) -> None:
        assert self._server.descriptor_path.exists()
        self.events.append("shutdown")


def test_requires_a_declared_identity(endpoint_directory: Path) -> None:
    class _Unnamed(Provider):
        pass

    with pytest.raises(ProviderServerError, match="non-empty 'identity'"):
        _Unnamed(
            discovery_directory=endpoint_directory,
            state_directory=endpoint_directory / "state",
        )


@pytest.mark.parametrize("identity", ["", "has/slash", ".", ".."])
def test_rejects_unsafe_identity(
    endpoint_directory: Path, identity: str
) -> None:
    class _Unsafe(Provider):
        pass

    _Unsafe.identity = identity
    with pytest.raises(ProviderServerError):
        _Unsafe(
            discovery_directory=endpoint_directory,
            state_directory=endpoint_directory / "state",
        )


def test_uses_reference_defaults_when_not_overridden() -> None:
    class _Defaulted(Provider):
        identity = "stateforge.defaulted"

    provider = _Defaulted()

    assert (
        provider._configuration.discovery_directory
        == _DEFAULT_DISCOVERY_DIRECTORY
    )
    assert (
        provider._configuration.state_directory
        == _DEFAULT_STATE_ROOT / "stateforge.defaulted"
    )


def test_wire_version_support_is_not_provider_configurable() -> None:
    assert (
        "supported_sfp_versions"
        not in inspect.signature(Provider.__init__).parameters
    )


@pytest.mark.asyncio
async def test_runs_hooks_around_endpoint_publication(
    endpoint_directory: Path,
) -> None:
    provider = _RecordingProvider(
        discovery_directory=endpoint_directory,
        state_directory=endpoint_directory / "state",
    )
    serve_task = asyncio.ensure_future(provider.serve())
    await asyncio.wait_for(provider.started.wait(), timeout=2)
    assert provider.events == ["startup"]

    channel = grpc.aio.insecure_channel(f"unix:{provider._server.socket_path}")
    try:
        await asyncio.wait_for(channel.channel_ready(), timeout=2)
    finally:
        await channel.close()
    assert provider._server.descriptor_path.exists()

    provider.request_shutdown()
    await asyncio.wait_for(serve_task, timeout=2)

    assert provider.events == ["startup", "shutdown"]
    assert not provider._server.descriptor_path.exists()
    assert not provider._server.socket_path.exists()
