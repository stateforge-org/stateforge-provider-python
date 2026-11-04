"""Serve deterministic Operation Lifecycle behavior to an installed Agent."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import grpc

from stateforge_provider import (
    OperationCancelledError,
    OperationCleanup,
    OperationContext,
    OperationEffects,
    OperationFailedError,
    OperationProgressPolicy,
    OperationSideEffects,
    Platform,
    Provider,
    ProviderModel,
    operation,
)
from stateforge_provider._services.operation_lifecycle.service import (
    OperationLifecycleService,
)


class Input(ProviderModel):
    """Select one deterministic lifecycle behavior."""

    mode: str


class Result(ProviderModel):
    """Return a typed integer operation result."""

    value: int


class LifecycleFixture(Provider):
    """Expose successful, failed, and cancellable operation behaviors."""

    identity = "stateforge.test.operation_lifecycle"
    display_name = "StateForge Operation Lifecycle CI Provider"
    version = "0.1.0"
    platforms = (Platform("linux", "x86_64"),)

    def __init__(
        self,
        discovery_directory: Path,
        state_directory: Path,
        event_log: Path,
    ) -> None:
        """Bind operation controls to scenario-owned runtime paths."""
        super().__init__(
            discovery_directory=discovery_directory,
            state_directory=state_directory,
        )
        self._state_directory = state_directory
        self._event_log = event_log

    async def on_startup(self) -> None:
        """Record that the independent Provider process is ready."""
        self._record("startup")

    async def on_shutdown(self) -> None:
        """Record graceful teardown for the scenario evidence."""
        self._record("shutdown")

    @operation(
        "stateforge.test/execute@1",
        cancellable=True,
        progress=OperationProgressPolicy.determinate(),
    )
    async def execute(
        self, request: Input, context: OperationContext
    ) -> Result:
        """Execute one success, failure, cancellation, or race path."""
        operation_id = str(context.operation_id)
        self._record(f"dispatch:{operation_id}:{request.mode}")
        await context.report_progress("Started", percentage=0)

        if request.mode == "failure":
            raise OperationFailedError(
                code="stateforge.test.expected_failure",
                explanation="The fixture operation failed safely.",
                effects=OperationEffects(
                    side_effects=OperationSideEffects.NONE,
                    cleanup=OperationCleanup.NOT_REQUIRED,
                    explanation="No external state was changed.",
                ),
            )

        if request.mode == "runtime-error":
            raise RuntimeError("stateforge-r20-secret-never-in-evidence")

        if request.mode == "progress":
            self._record(f"waiting:{operation_id}")
            release = self._state_directory / f"release-{operation_id}"
            while not release.exists():  # noqa: ASYNC110
                await asyncio.sleep(0.01)

        if request.mode in {"cancel", "race"}:
            self._record(f"waiting:{operation_id}")
            release = self._state_directory / f"release-{operation_id}"
            while not release.exists():
                if context.cancellation_requested:
                    break
                await asyncio.sleep(0.01)
            if context.cancellation_requested:
                self._record(f"cancelled:{operation_id}")
                raise OperationCancelledError(
                    OperationEffects(
                        side_effects=OperationSideEffects.PRESENT,
                        cleanup=OperationCleanup.COMPLETED,
                        explanation="Temporary fixture work was removed.",
                    )
                )

        await context.report_progress("Half", percentage=50)
        if request.mode == "progress":
            self._record(f"half:{operation_id}")
            release_half = (
                self._state_directory / f"release-half-{operation_id}"
            )
            while not release_half.exists():  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        await context.report_progress("Finished", percentage=100)
        self._record(f"finished:{operation_id}")
        if request.mode == "invalid-result":
            return Result.model_construct(value="not-an-integer")
        return Result(value=100)

    def _record(self, event: str) -> None:
        self._event_log.parent.mkdir(parents=True, exist_ok=True)
        with self._event_log.open("a", encoding="utf-8") as stream:
            stream.write(f"{event}\n")


def main() -> None:
    """Run the fixture as a normal standalone Provider process."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--discovery-directory", type=Path, required=True)
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--target-path", type=Path, required=True)
    arguments = parser.parse_args()
    LifecycleFixture.identity = arguments.identity
    LifecycleFixture.display_name = arguments.display_name

    original_watch = OperationLifecycleService.WatchOperation
    retry_marker = arguments.state_directory / "fail-next-watch"
    event_log = arguments.event_log

    async def watch_once_unavailable(
        service: OperationLifecycleService,
        request: object,
        context: grpc.aio.ServicerContext[object, object],
    ) -> None:
        if retry_marker.exists():
            retry_marker.unlink()
            event_log.parent.mkdir(parents=True, exist_ok=True)
            with event_log.open("a", encoding="utf-8") as stream:
                stream.write("watch:injected-unavailable\n")
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Injected one-time Watch transport failure",
            )
        await original_watch(service, request, context)  # type: ignore[arg-type]

    OperationLifecycleService.WatchOperation = watch_once_unavailable
    LifecycleFixture(
        arguments.discovery_directory,
        arguments.state_directory,
        arguments.event_log,
    ).run()


if __name__ == "__main__":
    main()
