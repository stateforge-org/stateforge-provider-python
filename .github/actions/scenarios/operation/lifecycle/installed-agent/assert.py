"""Exercise installed Agent Operation Lifecycle APIs against a Provider."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from uuid import UUID, uuid4

import grpc
from stateforge_agent._journal import SqliteJournal
from stateforge_agent._sfp import (
    OperationAdmissionRequest,
    ProviderAvailabilityState,
    ProviderSessionManager,
    SfpVersion,
)
from stateforge_agent._sfp._runtime.descriptor import load_provider_descriptor
from stateforge_agent._sfp._services.operation_admission.coordinator import (
    OperationAdmissionCoordinator,
)
from stateforge_agent._sfp._services.operation_lifecycle.client import (
    OperationLifecycleClient,
    SfpOperationLifecycleTransportError,
)
from stateforge_agent._sfp._services.operation_lifecycle.coordinator import (
    OperationLifecycleCoordinator,
)
from stateforge_protocol.sfp.operation_admission.v1 import (
    operation_admission_pb2,
)
from stateforge_protocol.sfp.operation_lifecycle.v1 import (
    operation_lifecycle_pb2,
)

_DISCOVERY = Path("/run/stateforge-agent/providers")
_DEFAULT_JOURNAL = Path(
    "/var/lib/stateforge-agent/journal/operation-lifecycle-r20.db"
)
_TERMINAL = {
    "OPERATION_STATE_SUCCEEDED",
    "OPERATION_STATE_FAILED",
    "OPERATION_STATE_CANCELLED",
}
_MIDDLE_PROGRESS = 50.0
_COMPLETE_PROGRESS = 100.0
_EXPECTED_DISPATCHES = 6
_SCRIPT_PATH = Path(__file__).resolve()
_PROVIDER_ERROR_SENTINEL = "stateforge-r20-secret-never-in-evidence"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reopen-operation", type=UUID)
    parser.add_argument("--previous-session-id")
    parser.add_argument("--previous-generation", type=int)
    parser.add_argument("--agent-runtime-id", type=UUID)
    parser.add_argument("--provider-instance-id", type=UUID, required=True)
    parser.add_argument("--journal-path", type=Path, default=_DEFAULT_JOURNAL)
    parser.add_argument("--state-directory", type=Path)
    parser.add_argument("--event-log", type=Path)
    parser.add_argument("--unit-name")
    return parser.parse_args()


async def _new_agent(
    journal: SqliteJournal,
    agent_runtime_id: UUID | None = None,
) -> tuple[ProviderSessionManager, OperationAdmissionCoordinator]:
    store = journal.operation_admissions(maximum_unresolved_attempts=32)
    await store.initialize()
    admission = OperationAdmissionCoordinator(
        store, retry_initial_delay_seconds=0.05
    )
    lifecycle = OperationLifecycleCoordinator(
        store, retry_initial_delay_seconds=0.05
    )
    manager = ProviderSessionManager(
        agent_runtime_id=agent_runtime_id or uuid4(),
        agent_software_version=version("stateforge-agent"),
        supported_sfp_versions=(SfpVersion(major=1, minor=0),),
        capability_assessment_retry_initial_delay_seconds=0.05,
        operation_admission=admission,
        operation_lifecycle=lifecycle,
    )
    return manager, admission


def _events(path: Path) -> tuple[str, ...]:
    try:
        return tuple(path.read_text(encoding="utf-8").splitlines())
    except FileNotFoundError:
        return ()


async def _wait_until(predicate: Callable[[], bool], message: str) -> None:
    try:
        async with asyncio.timeout(20):
            while not predicate():  # noqa: ASYNC110
                await asyncio.sleep(0.025)
    except TimeoutError as error:
        raise AssertionError(message) from error


def _descriptor_generation(provider_id: UUID) -> int:
    try:
        descriptor = json.loads(
            (_DISCOVERY / f"{provider_id}.sfp.json").read_text(
                encoding="utf-8"
            )
        )
    except (FileNotFoundError, json.JSONDecodeError):
        return 0
    return int(descriptor["endpoint_generation"])


async def _unit_invocation_id(unit_name: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/systemctl",
        "show",
        unit_name,
        "--property",
        "InvocationID",
        "--value",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    output, error = await process.communicate()
    if process.returncode != 0:
        raise AssertionError(
            "Could not inspect Provider systemd invocation: "
            + error.decode("utf-8", errors="replace")[-1000:]
        )
    return output.decode("utf-8").strip()


async def _available(
    manager: ProviderSessionManager, provider_id: UUID
) -> None:
    await _wait_until(
        lambda: (
            (status := manager.availability_status(provider_id)) is not None
            and status.state is ProviderAvailabilityState.AVAILABLE
        ),
        "Agent did not observe Provider availability",
    )


async def _admit(
    manager: ProviderSessionManager,
    provider_id: UUID,
    mode: str,
) -> UUID:
    result = await manager.admit_operation(
        OperationAdmissionRequest(
            provider_instance_id=provider_id,
            operation_identifier="stateforge.test/execute@1",
            payload={"mode": mode},
            execution_deadline=datetime.now(UTC) + timedelta(minutes=2),
            execution_context={"scenario": "provider-r20"},
        )
    )
    return result.operation_id


async def _status(
    manager: ProviderSessionManager, provider_id: UUID, operation_id: UUID
) -> object:
    async with asyncio.timeout(20):
        while True:
            status = await manager.operation_status(provider_id, operation_id)
            if status is not None and status.state in _TERMINAL:
                return status
            await asyncio.sleep(0.025)


async def _watch_to_terminal(
    manager: ProviderSessionManager,
    admission: OperationAdmissionCoordinator,
    *,
    provider_id: UUID,
    operation_id: UUID,
    first_response: asyncio.Event,
    half_progress: asyncio.Event,
) -> list[operation_lifecycle_pb2.WatchOperationResponse]:
    lease = await manager._operation_lifecycle_lease(provider_id)
    attempt = await admission.attempt(provider_id, operation_id)
    if attempt is None:
        raise AssertionError("Agent lost the durable operation identity")
    request = operation_lifecycle_pb2.WatchOperationRequest(
        session_binding=operation_admission_pb2.OperationSessionBinding(
            expected_provider_instance_id=str(provider_id),
            expected_endpoint_generation=lease.endpoint_generation,
            expected_session_id=lease.session_id,
        ),
        operation_id=str(operation_id),
        expected_request_fingerprint=attempt.request_fingerprint,
        after_sequence=1,
    )
    responses = []
    async for response in OperationLifecycleClient().watch(
        lease.channel, request
    ):
        responses.append(response)
        first_response.set()
        if (
            response.snapshot.HasField("progress")
            and response.snapshot.progress.HasField("percentage")
            and response.snapshot.progress.percentage == _MIDDLE_PROGRESS
        ):
            half_progress.set()
    return responses


async def _restarted_requester(
    provider_id: UUID,
    operation_id: UUID,
    *,
    previous_session_id: str,
    previous_generation: int,
    agent_runtime_id: UUID,
    journal_path: Path,
) -> dict[str, object]:
    """Reopen installed Agent persistence and reject its superseded session."""
    journal = SqliteJournal(journal_path)
    await journal.open()
    manager, admission = await _new_agent(journal, agent_runtime_id)
    try:
        descriptor = load_provider_descriptor(
            _DISCOVERY / f"{provider_id}.sfp.json",
            discovery_directory=_DISCOVERY,
        )
        session = await manager.establish(descriptor)
        await _available(manager, provider_id)
        if session.session_id == previous_session_id:
            raise AssertionError(
                "Requester restart reused the old SFP session"
            )
        status = await manager.operation_status(provider_id, operation_id)
        if status is None or status.state != "OPERATION_STATE_SUCCEEDED":
            raise AssertionError(
                "Restarted requester lost terminal journal state"
            )
        attempt = await admission.attempt(provider_id, operation_id)
        if attempt is None:
            raise AssertionError("Restarted requester lost admission identity")
        lease = await manager._operation_lifecycle_lease(provider_id)
        stale = operation_lifecycle_pb2.WatchOperationRequest(
            session_binding=operation_admission_pb2.OperationSessionBinding(
                expected_provider_instance_id=str(provider_id),
                expected_endpoint_generation=previous_generation,
                expected_session_id=previous_session_id,
            ),
            operation_id=str(operation_id),
            expected_request_fingerprint=attempt.request_fingerprint,
        )
        try:
            async for _ in OperationLifecycleClient().watch(
                lease.channel, stale
            ):
                pass
        except SfpOperationLifecycleTransportError as error:
            if error.code is not grpc.StatusCode.FAILED_PRECONDITION:
                raise AssertionError(
                    "Superseded session had the wrong rejection status"
                ) from error
        else:
            raise AssertionError("Superseded Agent session was accepted")
        return {
            "requester_pid": os.getpid(),
            "session_id": session.session_id,
            "endpoint_generation": session.endpoint_generation,
            "retained_terminal_state": status.state,
            "stale_session_rejected": True,
        }
    finally:
        await manager.close()
        await journal.close()


async def _spawn_restarted_requester(
    provider_id: UUID,
    operation_id: UUID,
    *,
    previous_session_id: str,
    previous_generation: int,
    agent_runtime_id: UUID,
    journal_path: Path,
) -> dict[str, object]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        str(_SCRIPT_PATH),
        "--reopen-operation",
        str(operation_id),
        "--provider-instance-id",
        str(provider_id),
        "--journal-path",
        str(journal_path),
        "--previous-session-id",
        previous_session_id,
        "--previous-generation",
        str(previous_generation),
        "--agent-runtime-id",
        str(agent_runtime_id),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, error = await asyncio.wait_for(
            process.communicate(), timeout=30
        )
    except TimeoutError as timeout_error:
        process.kill()
        await process.wait()
        raise AssertionError(
            "Restarted Agent requester timed out"
        ) from timeout_error
    if process.returncode != 0:
        raise AssertionError(
            "Restarted Agent requester failed: "
            + error.decode("utf-8", errors="replace")[-2000:]
        )
    evidence = json.loads(output)
    if evidence["requester_pid"] != process.pid or process.pid == os.getpid():
        raise AssertionError(
            "Requester restart did not cross a process boundary"
        )
    return evidence


async def _run(arguments: argparse.Namespace) -> dict[str, object]:  # noqa: PLR0912, PLR0915
    if arguments.state_directory is None or arguments.event_log is None:
        raise ValueError(
            "state and event paths are required for the full scenario"
        )
    provider_id: UUID = arguments.provider_instance_id
    state: Path = arguments.state_directory
    journal = SqliteJournal(arguments.journal_path)
    await journal.open()
    agent_runtime_id = uuid4()
    manager, admission = await _new_agent(journal, agent_runtime_id)
    descriptor_path = _DISCOVERY / f"{provider_id}.sfp.json"
    descriptor = load_provider_descriptor(
        descriptor_path, discovery_directory=_DISCOVERY
    )
    initial_session = None
    manager_closed = False
    journal_closed = False
    try:
        initial_session = await manager.establish(descriptor)
        await _available(manager, provider_id)

        # Arm a single real Provider Watch transport fault. Agent's installed
        # requester must reconnect its observer without resubmitting admission.
        (state / "fail-next-watch").touch()
        success_id = await _admit(manager, provider_id, "progress")
        await _wait_until(
            lambda: (
                "watch:injected-unavailable" in _events(arguments.event_log)
            ),
            "Installed Agent did not encounter the injected Watch failure",
        )
        release = state / f"release-{success_id}"
        await _wait_until(
            lambda: any(
                event == f"waiting:{success_id}"
                for event in _events(arguments.event_log)
            ),
            "Provider did not hold the progress operation",
        )
        first_response = asyncio.Event()
        half_progress = asyncio.Event()
        live_watch = asyncio.create_task(
            _watch_to_terminal(
                manager,
                admission,
                provider_id=provider_id,
                operation_id=success_id,
                first_response=first_response,
                half_progress=half_progress,
            )
        )
        first_response_wait = asyncio.create_task(first_response.wait())
        completed, _ = await asyncio.wait(
            (first_response_wait, live_watch),
            timeout=5,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if live_watch in completed:
            await live_watch
        if first_response_wait not in completed:
            first_response_wait.cancel()
            await asyncio.gather(first_response_wait, return_exceptions=True)
            live_watch.cancel()
            await asyncio.gather(live_watch, return_exceptions=True)
            raise AssertionError(
                "Agent lifecycle Watch produced no initial observation"
            )
        release.touch()
        await _wait_until(
            lambda: any(
                event == f"half:{success_id}"
                for event in _events(arguments.event_log)
            ),
            "Provider did not hold after publishing intermediate progress",
        )
        await asyncio.wait_for(half_progress.wait(), timeout=5)
        (state / f"release-half-{success_id}").touch()
        progress = await live_watch
        success = await _status(manager, provider_id, success_id)
        if success.result != {"value": 100.0}:
            raise AssertionError(
                "Agent did not retain the typed terminal result"
            )
        if success.progress_percentage != _COMPLETE_PROGRESS:
            raise AssertionError("Agent did not retain terminal progress")
        progress_percentages = [
            item.snapshot.progress.percentage
            for item in progress
            if item.snapshot.HasField("progress")
            and item.snapshot.progress.HasField("percentage")
        ]
        if (
            _MIDDLE_PROGRESS not in progress_percentages
            or _COMPLETE_PROGRESS not in progress_percentages
        ):
            raise AssertionError(
                "Agent lifecycle client missed progress updates"
            )

        # A new Agent observer against the retained operation receives the
        # terminal snapshot; a nonzero cursor reports coalesced gaps.
        lease = await manager._operation_lifecycle_lease(provider_id)
        attempt = await admission.attempt(provider_id, success_id)
        if attempt is None:
            raise AssertionError("Agent lost the durable operation identity")
        watch_request = operation_lifecycle_pb2.WatchOperationRequest(
            session_binding=operation_admission_pb2.OperationSessionBinding(
                expected_provider_instance_id=str(provider_id),
                expected_endpoint_generation=lease.endpoint_generation,
                expected_session_id=lease.session_id,
            ),
            operation_id=str(success_id),
            expected_request_fingerprint=attempt.request_fingerprint,
            after_sequence=0,
        )
        replay = [
            item
            async for item in OperationLifecycleClient().watch(
                lease.channel, watch_request
            )
        ]
        if not replay or replay[-1].snapshot.state != (
            operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED
        ):
            raise AssertionError("Late Agent Watch did not replay completion")
        gap_request = operation_lifecycle_pb2.WatchOperationRequest()
        gap_request.CopyFrom(watch_request)
        gap_request.after_sequence = 1
        gap = [
            item
            async for item in OperationLifecycleClient().watch(
                lease.channel, gap_request
            )
        ]
        if not gap or not gap[-1].updates_skipped:
            raise AssertionError("Agent Watch did not report a cursor gap")

        failure_id = await _admit(manager, provider_id, "failure")
        failure = await _status(manager, provider_id, failure_id)
        if failure.failure_code != "stateforge.test.expected_failure":
            raise AssertionError("Agent did not retain the typed failure")
        if "fixture" not in (failure.failure_explanation or ""):
            raise AssertionError("Agent failure explanation was not retained")

        runtime_error_id = await _admit(manager, provider_id, "runtime-error")
        runtime_error = await _status(manager, provider_id, runtime_error_id)
        if runtime_error.failure_code != "stateforge.operation.provider_error":
            raise AssertionError(
                "Unexpected Provider exception was not normalized"
            )
        if _PROVIDER_ERROR_SENTINEL in (
            runtime_error.failure_explanation or ""
        ):
            raise AssertionError(
                "Provider exception text leaked to Agent status"
            )

        invalid_id = await _admit(manager, provider_id, "invalid-result")
        invalid = await _status(manager, provider_id, invalid_id)
        if invalid.failure_code != "stateforge.operation.invalid_result":
            raise AssertionError(
                "Invalid result was not normalized by Provider"
            )

        cancellation_id = await _admit(manager, provider_id, "cancel")
        await _wait_until(
            lambda: any(
                event == f"waiting:{cancellation_id}"
                for event in _events(arguments.event_log)
            ),
            "Provider did not enter the cancellation fixture",
        )
        requested = await manager.cancel_operation(
            provider_id, cancellation_id
        )
        if requested.state != "OPERATION_STATE_CANCELLATION_REQUESTED":
            raise AssertionError(
                "Agent treated a request as completed cancellation"
            )
        cancelled = await _status(manager, provider_id, cancellation_id)
        if cancelled.state != "OPERATION_STATE_CANCELLED":
            raise AssertionError(
                "Provider did not complete cooperative cancellation"
            )
        if (
            cancelled.side_effects != "SIDE_EFFECT_STATE_PRESENT"
            or cancelled.cleanup != "CLEANUP_STATE_COMPLETED"
        ):
            raise AssertionError("Agent lost confirmed cancellation effects")

        race_id = await _admit(manager, provider_id, "race")
        await _wait_until(
            lambda: any(
                event == f"waiting:{race_id}"
                for event in _events(arguments.event_log)
            ),
            "Provider did not enter the cancellation-race fixture",
        )
        race_release = asyncio.create_task(
            asyncio.to_thread((state / f"release-{race_id}").touch)
        )
        try:
            await manager.cancel_operation(provider_id, race_id)
        except (SfpOperationLifecycleTransportError, RuntimeError):
            # The result may win the race; require a durable terminal state.
            raced_status = await _status(manager, provider_id, race_id)
            if raced_status.state not in _TERMINAL:
                raise
        await race_release
        raced = await _status(manager, provider_id, race_id)
        if raced.state not in {
            "OPERATION_STATE_SUCCEEDED",
            "OPERATION_STATE_CANCELLED",
        }:
            raise AssertionError(
                "Cancellation race had no valid terminal state"
            )

        dispatches = [
            line
            for line in _events(arguments.event_log)
            if line.startswith("dispatch:")
        ]
        if len(dispatches) != _EXPECTED_DISPATCHES:
            raise AssertionError(
                f"Expected six dispatches, found {len(dispatches)}"
            )
        if len({line.split(":", 2)[1] for line in dispatches}) != (
            _EXPECTED_DISPATCHES
        ):
            raise AssertionError(
                "Provider received duplicate operation dispatch"
            )

        await manager.close()
        manager_closed = True
        await journal.close()
        journal_closed = True
        old_invocation = await _unit_invocation_id(arguments.unit_name)
        restart = await asyncio.create_subprocess_exec(
            "/usr/bin/systemctl",
            "restart",
            arguments.unit_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, restart_error = await restart.communicate()
        if restart.returncode != 0:
            raise AssertionError(
                "Provider systemd restart failed: "
                + restart_error.decode("utf-8", errors="replace")[-1000:]
            )
        await _wait_until(
            lambda: (
                _descriptor_generation(provider_id)
                > initial_session.endpoint_generation
            ),
            "Provider restart did not publish a newer endpoint generation",
        )
        new_invocation = await _unit_invocation_id(arguments.unit_name)
        if new_invocation == old_invocation:
            raise AssertionError(
                "Provider restart reused its systemd invocation"
            )
        restarted = await _spawn_restarted_requester(
            provider_id,
            success_id,
            previous_session_id=initial_session.session_id,
            previous_generation=initial_session.endpoint_generation,
            agent_runtime_id=agent_runtime_id,
            journal_path=arguments.journal_path,
        )
        final_dispatches = [
            line
            for line in _events(arguments.event_log)
            if line.startswith("dispatch:")
        ]
        if (
            len(final_dispatches) != _EXPECTED_DISPATCHES
            or len({line.split(":", 2)[1] for line in final_dispatches})
            != _EXPECTED_DISPATCHES
        ):
            raise AssertionError(
                "Provider redispatched operation work across restart"
            )
        result = {
            "agent_version": version("stateforge-agent"),
            "provider_version": version("stateforge-provider"),
            "protocol_version": version("stateforge-protocol"),
            "provider_instance_id": str(provider_id),
            "endpoint_generation": initial_session.endpoint_generation,
            "restarted_endpoint_generation": restarted["endpoint_generation"],
            "session_id": initial_session.session_id,
            "watch_retry_injected": "watch:injected-unavailable"
            in _events(arguments.event_log),
            "watch_retry_recovered": success.state
            == "OPERATION_STATE_SUCCEEDED",
            "progress_sequences": [
                item.snapshot.sequence for item in progress
            ],
            "late_replay": replay[-1].snapshot.state
            == operation_lifecycle_pb2.OPERATION_STATE_SUCCEEDED,
            "cursor_gap_replayed": gap[-1].updates_skipped,
            "success_result": success.result,
            "expected_failure": failure.failure_code,
            "sanitized_failure": runtime_error.failure_code,
            "invalid_result": invalid.failure_code,
            "cancellation_completed": cancelled.state,
            "cancellation_effects": cancelled.side_effects
            == "SIDE_EFFECT_STATE_PRESENT"
            and cancelled.cleanup == "CLEANUP_STATE_COMPLETED",
            "cancellation_race_resolved": raced.state,
            "dispatches": len(final_dispatches),
            "no_redispatch": len(
                {line.split(":", 2)[1] for line in final_dispatches}
            )
            == len(final_dispatches),
            "requester_restarted": restarted["requester_pid"] != os.getpid(),
            "provider_restarted": new_invocation != old_invocation,
            "previous_provider_invocation_id": old_invocation,
            "provider_invocation_id": new_invocation,
            "endpoint_generation_increased": restarted["endpoint_generation"]
            > initial_session.endpoint_generation,
            "restarted_terminal_state": restarted["retained_terminal_state"],
            "stale_session_rejected": restarted["stale_session_rejected"],
            "restarted_session_id": restarted["session_id"],
        }
        return result
    finally:
        if not manager_closed:
            await manager.close()
        if not journal_closed:
            await journal.close()


def main() -> None:
    """Run lifecycle assertions with the installed Agent runtime."""
    arguments = _arguments()
    if arguments.reopen_operation is not None:
        if (
            arguments.previous_session_id is None
            or arguments.previous_generation is None
            or arguments.agent_runtime_id is None
        ):
            raise SystemExit(
                "--previous-session-id, --previous-generation, and "
                "--agent-runtime-id are required"
            )
        result = asyncio.run(
            _restarted_requester(
                arguments.provider_instance_id,
                arguments.reopen_operation,
                previous_session_id=arguments.previous_session_id,
                previous_generation=arguments.previous_generation,
                agent_runtime_id=arguments.agent_runtime_id,
                journal_path=arguments.journal_path,
            )
        )
    else:
        result = asyncio.run(_run(arguments))
    print(json.dumps(result, indent=2, sort_keys=True))  # noqa: T201


if __name__ == "__main__":
    main()
