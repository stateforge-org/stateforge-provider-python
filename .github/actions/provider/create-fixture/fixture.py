"""Public-API Provider used by installed-runtime CI scenarios."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import signal
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from stateforge_provider import (
    HealthStatus,
    Platform,
    Provider,
    ProviderModel,
    RequirementCheckResult,
    RuntimeRequirement,
    Trigger,
    operation,
    requirement_check,
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
        target_path: Path,
    ) -> None:
        """Bind the fixture to isolated scenario-owned paths."""
        super().__init__(
            discovery_directory=discovery_directory,
            state_directory=state_directory,
        )
        self._event_log = event_log
        self._target_path = target_path
        self._health_status = HealthStatus.healthy()
        self._fail_health = False
        self._health_tasks: set[asyncio.Task[None]] = set()

    async def on_startup(self) -> None:
        """Record that author resources were initialized."""
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(
            signal.SIGUSR1,
            self._schedule_health,
            HealthStatus.maintenance(),
            False,
        )
        loop.add_signal_handler(
            signal.SIGUSR2,
            self._schedule_health,
            HealthStatus.healthy(),
            False,
        )
        loop.add_signal_handler(
            signal.SIGHUP,
            self._schedule_health,
            HealthStatus.not_serving(),
            True,
        )
        self._record("startup")

    async def on_shutdown(self) -> None:
        """Record that author resources were released."""
        loop = asyncio.get_running_loop()
        for signal_number in (signal.SIGUSR1, signal.SIGUSR2, signal.SIGHUP):
            with contextlib.suppress(NotImplementedError, ValueError):
                loop.remove_signal_handler(signal_number)
        if self._health_tasks:
            await asyncio.gather(*self._health_tasks, return_exceptions=True)
        self._record("shutdown")

    async def health(self) -> HealthStatus:
        """Report deterministic health controlled by scenario signals."""
        if self._fail_health:
            raise RuntimeError("fixture health hook failed")
        return self._health_status

    @requirement_check(
        "runtime.target.readable",
        "Fixture target is readable",
    )
    async def target_readable(self) -> RequirementCheckResult:
        """Inspect the scenario target without mutating it."""
        self._record("requirement:runtime.target.readable")
        if os.access(self._target_path, os.R_OK):
            return RequirementCheckResult.satisfied()
        return RequirementCheckResult.unsatisfied()

    @requirement_check("runtime.pending", "Pending fixture prerequisite")
    async def pending(self) -> RequirementCheckResult:
        """Expose a deterministic unmet requirement."""
        self._record("requirement:runtime.pending")
        return RequirementCheckResult.unsatisfied()

    @requirement_check(
        "runtime.incompatible",
        "Incompatible fixture runtime",
    )
    async def incompatible(self) -> RequirementCheckResult:
        """Expose deterministic negative evidence."""
        self._record("requirement:runtime.incompatible")
        return RequirementCheckResult.incompatible("Fixture incompatibility")

    @requirement_check("runtime.unknown", "Unobservable fixture prerequisite")
    async def unknown(self) -> RequirementCheckResult:
        """Expose deterministic unknown evidence."""
        self._record("requirement:runtime.unknown")
        return RequirementCheckResult.unknown("Fixture evidence unavailable")

    @operation(
        "stateforge.test/inspect@1",
        requires=("runtime.target.readable",),
    )
    async def inspect(self, request: EchoInput) -> EchoResult:
        """Declare one supported operation without dispatching it."""
        self._record("operation:inspect")
        return EchoResult(value=request.value)

    @operation(
        "stateforge.test/snapshot@1",
        requires=("runtime.target.readable", "runtime.pending"),
    )
    async def snapshot(self, request: EchoInput) -> EchoResult:
        """Declare a supportable operation with an unmet prerequisite."""
        self._record("operation:snapshot")
        return EchoResult(value=request.value)

    @operation(
        "stateforge.test/unsupported@1",
        requires=("runtime.unknown", "runtime.incompatible"),
    )
    async def unsupported_operation(self, request: EchoInput) -> EchoResult:
        """Declare an operation with conclusive negative evidence."""
        self._record("operation:unsupported")
        return EchoResult(value=request.value)

    @operation(
        "stateforge.test/indeterminate@1",
        requires=("runtime.unknown",),
    )
    async def indeterminate_operation(
        self,
        request: EchoInput,
    ) -> EchoResult:
        """Declare an operation whose support cannot be established."""
        self._record("operation:indeterminate")
        return EchoResult(value=request.value)

    def _record(self, event: str) -> None:
        self._event_log.parent.mkdir(parents=True, exist_ok=True)
        with self._event_log.open("a", encoding="utf-8") as stream:
            stream.write(f"{event}\n")

    def _schedule_health(
        self,
        status: HealthStatus,
        fail_health: bool,
    ) -> None:
        """Schedule one event-driven public health refresh."""
        task = asyncio.create_task(
            self._publish_health(status, fail_health),
        )
        self._health_tasks.add(task)
        task.add_done_callback(self._health_tasks.discard)

    async def _publish_health(
        self,
        status: HealthStatus,
        fail_health: bool,
    ) -> None:
        """Update fixture evidence and invoke the public refresh API."""
        self._health_status = status
        self._fail_health = fail_health
        accepted = await self.refresh_health()
        self._record(f"health:{accepted.value}")


_BOUNDARY_REQUIREMENT_IDS = tuple(
    f"runtime.boundary.requirement_{index:02d}" for index in range(64)
)
_BOUNDARY_OPERATION_IDS = tuple(
    f"stateforge.test/boundary_{index:02d}@1" for index in range(64)
)
_BOUNDARY_DESCRIPTION = "\U00010000" * 2_048


class CapabilityBoundaryFixtureProvider(FixtureProvider):
    """Add valid declarations used only by Capability boundary tests."""

    @requirement_check(
        "runtime.cancellable",
        "Cancellable fixture prerequisite",
    )
    async def cancellable(self) -> RequirementCheckResult:
        """Block until the requesting peer cancels this assessment."""
        self._record("requirement:runtime.cancellable.started")
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self._record("requirement:runtime.cancellable.cancelled")
            raise
        self._record("requirement:runtime.cancellable.completed")
        return RequirementCheckResult.satisfied()

    @operation(
        "stateforge.test/cancellable@1",
        requires=("runtime.cancellable",),
    )
    async def cancellable_operation(self, request: EchoInput) -> EchoResult:
        """Declare the operation used to observe RPC cancellation."""
        self._record("operation:cancellable")
        return EchoResult(value=request.value)


def _boundary_requirement(
    identifier: str,
    index: int,
) -> Callable[
    [CapabilityBoundaryFixtureProvider],
    Coroutine[Any, Any, RequirementCheckResult],
]:
    """Build one public requirement declaration for response-size testing."""

    async def check(
        self: CapabilityBoundaryFixtureProvider,
    ) -> RequirementCheckResult:
        self._record(f"requirement:{identifier}")
        return RequirementCheckResult.satisfied()

    check.__name__ = f"boundary_requirement_{index:02d}"
    return requirement_check(identifier, _BOUNDARY_DESCRIPTION)(check)


def _boundary_operation(
    identifier: str,
    index: int,
) -> Callable[
    [CapabilityBoundaryFixtureProvider, EchoInput],
    Coroutine[Any, Any, EchoResult],
]:
    """Build one public operation declaration for response-size testing."""

    async def invoke(
        self: CapabilityBoundaryFixtureProvider,
        request: EchoInput,
    ) -> EchoResult:
        self._record(f"operation:{identifier}")
        return EchoResult(value=request.value)

    invoke.__name__ = f"boundary_operation_{index:02d}"
    return operation(
        identifier,
        requires=_BOUNDARY_REQUIREMENT_IDS,
    )(invoke)


for _index, _identifier in enumerate(_BOUNDARY_REQUIREMENT_IDS):
    setattr(
        CapabilityBoundaryFixtureProvider,
        f"boundary_requirement_{_index:02d}",
        _boundary_requirement(_identifier, _index),
    )
for _index, _identifier in enumerate(_BOUNDARY_OPERATION_IDS):
    setattr(
        CapabilityBoundaryFixtureProvider,
        f"boundary_operation_{_index:02d}",
        _boundary_operation(_identifier, _index),
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--discovery-directory", type=Path, required=True)
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--target-path", type=Path, required=True)
    parser.add_argument("--capability-boundaries", action="store_true")
    return parser.parse_args()


def main() -> None:
    """Run one standalone fixture Provider until it receives a signal."""
    arguments = _arguments()
    provider_type = (
        CapabilityBoundaryFixtureProvider
        if arguments.capability_boundaries
        else FixtureProvider
    )
    provider_type.identity = arguments.identity
    provider_type.display_name = arguments.display_name
    provider_type(
        discovery_directory=arguments.discovery_directory.resolve(),
        state_directory=arguments.state_directory.resolve(),
        event_log=arguments.event_log.resolve(),
        target_path=arguments.target_path.resolve(),
    ).run()


if __name__ == "__main__":
    main()
