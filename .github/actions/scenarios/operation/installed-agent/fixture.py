"""Operation-capable Provider fixture with a narrow response-loss hook."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import signal
from dataclasses import replace
from pathlib import Path

import grpc
from stateforge_protocol.sfp.operation_admission.v1 import (
    operation_admission_pb2 as admission_pb2,
)

from stateforge_provider import (
    HealthStatus,
    OperationContext,
    Platform,
    Provider,
    ProviderModel,
    operation,
)
from stateforge_provider._services.operation_admission.service import (
    OperationAdmissionService,
)


class Input(ProviderModel):
    """One read-only fixture input."""

    value: str


class Result(ProviderModel):
    """One read-only fixture result."""

    value: str


class AdmissionFixture(Provider):
    """Expose the real Provider author API and Health service to the Agent."""

    identity = "stateforge.test.operation_admission"
    display_name = "StateForge Admission CI Provider"
    version = "0.1.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(
        self,
        *,
        discovery_directory: Path,
        state_directory: Path,
        event_log: Path,
    ) -> None:
        """Bind only scenario-owned paths to the fixture."""
        super().__init__(
            discovery_directory=discovery_directory,
            state_directory=state_directory,
        )
        if (state_directory / "short-operation-retention").exists():
            self._configuration = replace(
                self._configuration,
                operation_record_retention_seconds=0.5,
                operation_tombstone_retention_seconds=30.0,
            )
        self._event_log = event_log
        self._health = HealthStatus.healthy()
        self._health_tasks: set[asyncio.Task[None]] = set()

    async def on_startup(self) -> None:
        """Register deterministic Health controls."""
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGUSR1, self._schedule_health, False)
        loop.add_signal_handler(signal.SIGUSR2, self._schedule_health, True)
        self._record("startup")

    async def on_shutdown(self) -> None:
        """Release Health controls and complete pending updates."""
        loop = asyncio.get_running_loop()
        for number in (signal.SIGUSR1, signal.SIGUSR2):
            with contextlib.suppress(NotImplementedError, ValueError):
                loop.remove_signal_handler(number)
        if self._health_tasks:
            await asyncio.gather(*self._health_tasks, return_exceptions=True)
        self._record("shutdown")

    async def health(self) -> HealthStatus:
        """Report the fixture's current process-wide Health."""
        return self._health

    @operation("stateforge.test/inspect@1")
    async def inspect(
        self, request: Input, context: OperationContext
    ) -> Result:
        """Perform one read-only operation and record its dispatch."""
        self._record(f"operation:inspect:{context.operation_id}")
        return Result(value=request.value)

    def _record(self, event: str) -> None:
        self._event_log.parent.mkdir(parents=True, exist_ok=True)
        with self._event_log.open("a", encoding="utf-8") as stream:
            stream.write(f"{event}\n")

    def _schedule_health(self, ready: bool) -> None:
        task = asyncio.create_task(self._set_health(ready))
        self._health_tasks.add(task)
        task.add_done_callback(self._health_tasks.discard)

    async def _set_health(self, ready: bool) -> None:
        self._health = (
            HealthStatus.healthy() if ready else HealthStatus.maintenance()
        )
        await self.refresh_health()
        self._record("health:ready" if ready else "health:not-serving")


def _observe_admission(event_log: Path, state_directory: Path) -> None:
    """Discard one post-admission response only when the marker is armed."""
    original = OperationAdmissionService.StartOperation
    marker = state_directory / "drop-next-operation-response"

    async def start_operation(
        service: OperationAdmissionService,
        request: admission_pb2.StartOperationRequest,
        context: grpc.aio.ServicerContext[
            admission_pb2.StartOperationRequest,
            admission_pb2.StartOperationResponse,
        ],
    ) -> admission_pb2.StartOperationResponse:
        digest = hashlib.sha256(
            request.SerializeToString(deterministic=True)
        ).hexdigest()
        event_log.parent.mkdir(parents=True, exist_ok=True)
        with event_log.open("a", encoding="utf-8") as stream:
            stream.write(f"operation-admission-attempt:{digest}\n")
        response = await original(service, request, context)
        if marker.exists():
            marker.unlink()
            with event_log.open("a", encoding="utf-8") as stream:
                stream.write("operation-admission-response:dropped\n")
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Injected response loss after admission",
            )
        return response

    OperationAdmissionService.StartOperation = start_operation


def main() -> None:
    """Run the real Provider service until systemd stops it."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--discovery-directory", type=Path, required=True)
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--target-path", type=Path, required=True)
    arguments = parser.parse_args()
    AdmissionFixture.identity = arguments.identity
    AdmissionFixture.display_name = arguments.display_name
    _observe_admission(arguments.event_log, arguments.state_directory)
    AdmissionFixture(
        discovery_directory=arguments.discovery_directory,
        state_directory=arguments.state_directory,
        event_log=arguments.event_log,
    ).run()


if __name__ == "__main__":
    main()
