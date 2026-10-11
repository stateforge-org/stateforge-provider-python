"""Public-API Provider used by installed-runtime CI scenarios."""

from __future__ import annotations

import argparse
from pathlib import Path

from pydantic import SecretStr

from stateforge_provider import (
    Platform,
    Provider,
    ProviderModel,
    RuntimeRequirement,
    Trigger,
    operation,
)


class FixtureConfiguration(ProviderModel):
    """Describe configuration shape without publishing configured values."""

    endpoint: str
    token: SecretStr


class EchoInput(ProviderModel):
    """Describe the fixture operation input."""

    value: str


class EchoResult(ProviderModel):
    """Describe the fixture operation result."""

    value: str


class ChangedPayload(ProviderModel):
    """Describe the fixture trigger payload."""

    reference: str


class FixtureProvider(Provider):
    """Exercise the supported authoring and lifecycle surface only."""

    identity = "stateforge.test.provider"
    display_name = "StateForge CI Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)
    configuration_model = FixtureConfiguration
    runtime_requirements = (
        RuntimeRequirement(
            "runtime.python",
            "Python interpreter",
            ">=3.11",
        ),
    )
    triggers = (Trigger("stateforge.test/changed@1", ChangedPayload),)

    def __init__(
        self,
        *,
        discovery_directory: Path,
        state_directory: Path,
        event_log: Path,
    ) -> None:
        """Bind the fixture to isolated scenario-owned paths."""
        super().__init__(
            discovery_directory=discovery_directory,
            state_directory=state_directory,
        )
        self._event_log = event_log

    async def on_startup(self) -> None:
        """Record that author resources were initialized."""
        self._record("startup")

    async def on_shutdown(self) -> None:
        """Record that author resources were released."""
        self._record("shutdown")

    @operation("stateforge.test/echo@1")
    async def echo(self, request: EchoInput) -> EchoResult:
        """Declare one typed operation without invoking it in R11."""
        return EchoResult(value=request.value)

    def _record(self, event: str) -> None:
        self._event_log.parent.mkdir(parents=True, exist_ok=True)
        with self._event_log.open("a", encoding="utf-8") as stream:
            stream.write(f"{event}\n")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--discovery-directory", type=Path, required=True)
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """Run one standalone fixture Provider until it receives a signal."""
    arguments = _arguments()
    FixtureProvider.identity = arguments.identity
    FixtureProvider.display_name = arguments.display_name
    FixtureProvider(
        discovery_directory=arguments.discovery_directory.resolve(),
        state_directory=arguments.state_directory.resolve(),
        event_log=arguments.event_log.resolve(),
    ).run()


if __name__ == "__main__":
    main()
