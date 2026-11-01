"""Run the public Trigger API against the installed StateForge Agent."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from uuid import UUID

from stateforge_protocol.sfp.trigger_publication.v1 import (
    trigger_publication_pb2,
)

from stateforge_provider import (
    Platform,
    Provider,
    ProviderModel,
    Trigger,
    trigger,
)
from stateforge_provider._services.trigger_publication import (
    runtime as trigger_runtime,
)
from stateforge_provider._services.trigger_publication.runtime import (
    TriggerPublicationRuntime,
    TriggerStreamLease,
)


class RuntimeEvent(ProviderModel):
    """Describe deterministic fixture events."""

    sequence: int
    source: str


RUNTIME_REFRESHED = Trigger(
    "stateforge.test/runtime.refreshed@1",
    RuntimeEvent,
)


def _record(path: Path, event: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{event}\n")


class TriggerFixtureProvider(Provider):
    """Publish through both supported public author-facing APIs."""

    identity = "stateforge.test.trigger"
    display_name = "StateForge Trigger CI Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)
    triggers = (RUNTIME_REFRESHED,)

    def __init__(
        self,
        *,
        discovery_directory: Path,
        state_directory: Path,
        event_log: Path,
        startup_sequence: int,
    ) -> None:
        """Bind deterministic trigger inputs to one Provider installation."""
        super().__init__(
            discovery_directory=discovery_directory,
            state_directory=state_directory,
        )
        self._event_log = event_log
        self._startup_sequence = startup_sequence
        self._startup_events: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._tasks: set[asyncio.Task[None]] = set()

    async def on_startup(self) -> None:
        """Publish the decorated event and install the callback signal."""
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGALRM, self._schedule_callback)
        self._startup_events.put_nowait(
            RuntimeEvent(
                sequence=self._startup_sequence,
                source="decorated",
            )
        )
        _record(self._event_log, "startup")

    async def on_shutdown(self) -> None:
        """Remove signal ownership and join callback tasks."""
        with contextlib.suppress(NotImplementedError, ValueError):
            asyncio.get_running_loop().remove_signal_handler(signal.SIGALRM)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        _record(self._event_log, "shutdown")

    @trigger("stateforge.test/runtime.started@1")
    async def runtime_started(self) -> AsyncIterator[RuntimeEvent]:
        """Publish one decorated startup event."""
        yield await self._startup_events.get()

    def _schedule_callback(self) -> None:
        _record(
            self._event_log,
            f"trigger-scheduled:{RUNTIME_REFRESHED.identifier}",
        )
        task = asyncio.create_task(self._publish_callback())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _publish_callback(self) -> None:
        receipt = await self.publish_trigger(
            RUNTIME_REFRESHED,
            RuntimeEvent(sequence=2, source="callback"),
        )
        _record(self._event_log, f"trigger-queued:{receipt.publication_id}")
        outcome = await receipt.outcome()
        suffix = ""
        if outcome.rejection is not None:
            suffix = (
                f":{outcome.rejection.reason.value}"
                f":{str(outcome.rejection.retryable).lower()}"
            )
        _record(
            self._event_log,
            "trigger-outcome:"
            f"{outcome.publication_id}:{outcome.disposition.value}{suffix}",
        )


def _install_ack_observer(arguments: argparse.Namespace) -> None:
    original = TriggerPublicationRuntime.acknowledge
    marker = arguments.state_directory / "accept-trigger-acks"

    async def acknowledge(
        runtime: TriggerPublicationRuntime,
        lease: TriggerStreamLease,
        acknowledgement: trigger_publication_pb2.TriggerAcknowledgement,
        *,
        is_session_current: Callable[[str], bool],
    ) -> None:
        disposition = (
            trigger_publication_pb2.TriggerAcknowledgementDisposition.Name(
                acknowledgement.disposition
            )
            .removeprefix("TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_")
            .lower()
        )
        suffix = ""
        if acknowledgement.HasField("rejection"):
            reason = (
                trigger_publication_pb2.TriggerRejectionReason.Name(
                    acknowledgement.rejection.reason
                )
                .removeprefix("TRIGGER_REJECTION_REASON_")
                .lower()
            )
            suffix = (
                f":{reason}:{str(acknowledgement.rejection.retryable).lower()}"
            )
        if arguments.drop_trigger_acks_until_marker and not marker.exists():
            _record(
                arguments.event_log,
                "trigger-ack-dropped:"
                f"{acknowledgement.publication_id}:{disposition}{suffix}",
            )
            return
        await original(
            runtime,
            lease,
            acknowledgement,
            is_session_current=is_session_current,
        )
        _record(
            arguments.event_log,
            "trigger-ack-observed:"
            f"{acknowledgement.publication_id}:{disposition}{suffix}",
        )

    TriggerPublicationRuntime.acknowledge = acknowledge


def _install_first_publication_id(configured: str) -> None:
    if not configured:
        return
    first = UUID(configured)
    original = trigger_runtime.uuid4
    pending = True

    def uuid4() -> UUID:
        nonlocal pending
        if pending:
            pending = False
            return first
        return original()

    trigger_runtime.uuid4 = uuid4


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--discovery-directory", type=Path, required=True)
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument("--event-log", type=Path, required=True)
    parser.add_argument("--target-path", type=Path, required=True)
    parser.add_argument("--trigger-publication", action="store_true")
    parser.add_argument(
        "--drop-trigger-acks-until-marker", action="store_true"
    )
    parser.add_argument("--first-trigger-publication-id", default="")
    parser.add_argument("--trigger-startup-sequence", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    """Install deterministic faults and run the standalone Provider."""
    arguments = _arguments()
    if not arguments.trigger_publication:
        raise ValueError("Trigger fixture requires --trigger-publication")
    TriggerFixtureProvider.identity = arguments.identity
    TriggerFixtureProvider.display_name = arguments.display_name
    _install_ack_observer(arguments)
    _install_first_publication_id(arguments.first_trigger_publication_id)
    TriggerFixtureProvider(
        discovery_directory=arguments.discovery_directory.resolve(),
        state_directory=arguments.state_directory.resolve(),
        event_log=arguments.event_log.resolve(),
        startup_sequence=arguments.trigger_startup_sequence,
    ).run()


if __name__ == "__main__":
    main()
