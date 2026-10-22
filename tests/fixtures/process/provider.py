"""Run a real Provider process for process-lifecycle tests."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from stateforge_provider import HealthStatus, Platform, Provider


class ProcessProvider(Provider):
    """Exercise one process-lifecycle outcome through the public API."""

    identity = "stateforge.test_process"
    display_name = "Process lifecycle test Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(self, runtime_directory: Path, mode: str) -> None:
        """Configure a disposable Provider process fixture."""
        self._runtime_directory = runtime_directory
        self._discovery_directory = runtime_directory / "discovery"
        self._mode = mode
        self._discovery_directory.mkdir(parents=True, exist_ok=True)
        super().__init__(
            discovery_directory=self._discovery_directory,
            state_directory=runtime_directory / "state",
        )

    async def on_startup(self) -> None:
        """Record startup and select the requested lifecycle outcome."""
        self._record("startup")
        if self._mode == "startup-failure":
            raise RuntimeError("simulated Provider startup failure")
        if self._mode in {
            "normal",
            "health-failure",
            "shutdown-failure",
        }:
            asyncio.get_running_loop().call_soon(self.request_shutdown)

    async def on_shutdown(self) -> None:
        """Record author cleanup and optionally fail it."""
        self._record("shutdown")
        if self._mode == "shutdown-failure":
            raise RuntimeError("simulated Provider shutdown failure")

    async def health(self) -> HealthStatus:
        """Fail closed without terminating for the health-failure mode."""
        if self._mode == "health-failure":
            raise RuntimeError("simulated Provider health failure")
        return HealthStatus.healthy()

    def _record(self, event: str) -> None:
        """Append one durable lifecycle marker for the parent test."""
        with (self._runtime_directory / "events.txt").open("a") as stream:
            stream.write(f"{event}\n")


def _arguments() -> argparse.Namespace:
    """Parse the bounded process-fixture interface."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=(
            "normal",
            "signal",
            "startup-failure",
            "shutdown-failure",
            "health-failure",
        ),
    )
    parser.add_argument("runtime_directory", type=Path)
    return parser.parse_args()


def main() -> None:
    """Run the requested process lifecycle through ``Provider.run()``."""
    arguments = _arguments()
    arguments.runtime_directory.mkdir(parents=True, exist_ok=True)
    ProcessProvider(arguments.runtime_directory, arguments.mode).run()


if __name__ == "__main__":
    main()
