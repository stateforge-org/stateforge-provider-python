"""Verify real RPM-installed Agent admission against a Provider process."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from uuid import UUID, uuid4

from google.protobuf.json_format import ParseDict
from google.protobuf.struct_pb2 import Struct
from google.protobuf.timestamp_pb2 import Timestamp
from stateforge_agent._journal import SqliteJournal
from stateforge_agent._sfp import (
    OperationAdmissionDisposition,
    OperationAdmissionRequest,
    ProviderAvailabilityState,
    ProviderSessionManager,
    SfpVersion,
)
from stateforge_agent._sfp._runtime.descriptor import (
    ProviderEndpointDescriptor,
    load_provider_descriptor,
)
from stateforge_agent._sfp._services.capability_assessment.client import (
    SfpCapabilityAssessmentUnavailableError,
)
from stateforge_agent._sfp._services.operation_admission.client import (
    OperationAdmissionClient,
    SfpOperationAdmissionRejectedError,
)
from stateforge_agent._sfp._services.operation_admission.coordinator import (
    OperationAdmissionCoordinator,
    OperationAdmissionPreconditionError,
    OperationAdmissionUnresolvedError,
)
from stateforge_protocol.sfp.operation_admission.v1 import (
    operation_admission_pb2 as admission_pb2,
)

_DISCOVERY = Path("/run/stateforge-agent/providers")
_JOURNAL = Path("/var/lib/stateforge-agent/journal/agent.db")
_OPERATION = "stateforge.test/inspect@1"
_ATTEMPT_PREFIX = "operation-admission-attempt:"
_SECRET = "stateforge-r19-secret-never-in-evidence"  # noqa: S105
_EXPECTED_RETRY_ATTEMPTS = 2


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider-instance-id", type=UUID, required=True)
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument("--unit-name", required=True)
    parser.add_argument("--prepare-uncertain", action="store_true")
    return parser.parse_args()


def _descriptor(provider_id: UUID) -> ProviderEndpointDescriptor:
    return load_provider_descriptor(
        _DISCOVERY / f"{provider_id}.sfp.json",
        discovery_directory=_DISCOVERY,
    )


def _events(path: Path) -> tuple[str, ...]:
    try:
        return tuple(path.read_text(encoding="utf-8").splitlines())
    except FileNotFoundError:
        return ()


def _dispatch_ids(path: Path) -> tuple[UUID, ...]:
    return tuple(
        UUID(event.removeprefix("operation:inspect:"))
        for event in _events(path)
        if event.startswith("operation:inspect:")
    )


def _wait_for_dispatches_sync(path: Path, expected: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if len(_dispatch_ids(path)) == expected:
            return
        time.sleep(0.05)
    raise AssertionError(f"Expected exactly {expected} Provider dispatches")


async def _wait_for_dispatches(path: Path, expected: int) -> None:
    await asyncio.to_thread(_wait_for_dispatches_sync, path, expected)


async def _wait_for_availability(
    manager: ProviderSessionManager,
    provider_id: UUID,
    expected: ProviderAvailabilityState,
) -> None:
    async with asyncio.timeout(15):
        while True:
            status = manager.availability_status(provider_id)
            if status is not None and status.state is expected:
                return
            await asyncio.sleep(0.05)


async def _manager(
    journal: SqliteJournal,
    *,
    attempts: int = 2,
) -> tuple[ProviderSessionManager, OperationAdmissionCoordinator]:
    store = journal.operation_admissions(maximum_unresolved_attempts=32)
    await store.initialize()
    coordinator = OperationAdmissionCoordinator(
        store,
        attempts=attempts,
        retry_initial_delay_seconds=0.05,
    )
    manager = ProviderSessionManager(
        agent_runtime_id=uuid4(),
        agent_software_version=version("stateforge-agent"),
        supported_sfp_versions=(SfpVersion(major=1, minor=0),),
        capability_assessment_retry_initial_delay_seconds=0.05,
        operation_admission=coordinator,
    )
    return manager, coordinator


def _request(
    provider_id: UUID,
    label: str,
    *,
    deadline: datetime | None = None,
) -> OperationAdmissionRequest:
    return OperationAdmissionRequest(
        provider_instance_id=provider_id,
        operation_identifier=_OPERATION,
        payload={"value": label},
        execution_deadline=deadline
        or datetime.now(UTC) + timedelta(minutes=5),
        execution_context={"scenario": "provider-r19"},
    )


def _wire_request(
    *,
    provider_id: UUID,
    generation: int,
    session_id: str,
    manifest_revision: str,
    operation_id: UUID,
) -> admission_pb2.StartOperationRequest:
    payload = Struct()
    ParseDict({"value": _SECRET}, payload)
    context = Struct()
    ParseDict({"scenario": "provider-r19"}, context)
    deadline = Timestamp()
    deadline.FromDatetime(datetime.now(UTC) + timedelta(minutes=5))
    return admission_pb2.StartOperationRequest(
        session_binding=admission_pb2.OperationSessionBinding(
            expected_provider_instance_id=str(provider_id),
            expected_endpoint_generation=generation,
            expected_session_id=session_id,
        ),
        invocation=admission_pb2.OperationInvocation(
            operation_id=str(operation_id),
            operation_identifier=_OPERATION,
            payload=payload,
            execution_deadline=deadline,
            contract=admission_pb2.OperationContractContext(
                manifest_revision=manifest_revision,
            ),
            execution_context=context,
        ),
        admission_mode=admission_pb2.ADMISSION_MODE_ADMIT_OR_RESOLVE,
    )


async def _restart(unit_name: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/systemctl", "restart", unit_name
    )
    if await process.wait() != 0:
        raise AssertionError(f"Failed to restart {unit_name}")


async def _signal(unit_name: str, name: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "/usr/bin/systemctl",
        "kill",
        "--kill-whom=main",
        f"--signal={name}",
        unit_name,
    )
    if await process.wait() != 0:
        raise AssertionError(f"Failed to send {name} to {unit_name}")


async def _uncertain_admission(
    manager: ProviderSessionManager,
    coordinator: OperationAdmissionCoordinator,
    provider_id: UUID,
    state: Path,
    label: str,
) -> UUID:
    """Lose one response and retain an uncertain Agent intent."""
    request = _request(provider_id, label)
    assessment = await manager.assess_capabilities(
        provider_id,
        (_OPERATION,),
        execution_context=request.execution_context,
    )
    lease = await manager._operation_admission_lease(provider_id)
    operation_id = await coordinator.prepare(
        lease,
        request,
        assessment,
        assert_current=manager._assert_operation_admission_is_current,
    )
    (state / "drop-next-operation-response").touch()
    try:
        await coordinator.submit(
            lease,
            operation_id,
            assessment,
            assert_current=manager._assert_operation_admission_is_current,
        )
    except OperationAdmissionUnresolvedError as error:
        if error.operation_id != operation_id:
            raise AssertionError(
                "Uncertainty changed operation identity"
            ) from error
    else:
        raise AssertionError("One-attempt response loss was not unresolved")
    attempt = await coordinator.attempt(provider_id, operation_id)
    if (
        attempt is None
        or attempt.attempt_count != 1
        or attempt.result is not None
    ):
        raise AssertionError("Uncertain identity was not durably retained")
    return operation_id


async def _prepare_uncertain_process(
    arguments: argparse.Namespace,
) -> dict[str, str | int]:
    """Leave one unresolved intent in the installed Agent journal."""
    journal = SqliteJournal(_JOURNAL)
    await journal.open()
    manager, coordinator = await _manager(journal, attempts=1)
    try:
        provider_id = arguments.provider_instance_id
        await manager.establish(_descriptor(provider_id))
        await _wait_for_availability(
            manager, provider_id, ProviderAvailabilityState.AVAILABLE
        )
        operation_id = await _uncertain_admission(
            manager,
            coordinator,
            provider_id,
            arguments.state_directory,
            "requester-rebuild",
        )
        return {
            "operation_id": str(operation_id),
            "requester_pid": os.getpid(),
        }
    finally:
        await manager.close()
        await journal.close()


async def _spawn_uncertain_requester(
    arguments: argparse.Namespace,
) -> tuple[UUID, int]:
    """Run the unresolved admission in a distinct installed-RPM process."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        str(Path(__file__)),
        "--provider-instance-id",
        str(arguments.provider_instance_id),
        "--state-directory",
        str(arguments.state_directory),
        "--unit-name",
        arguments.unit_name,
        "--prepare-uncertain",
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
            "Uncertain requester did not exit"
        ) from timeout_error
    if process.returncode != 0:
        raise AssertionError(
            "Uncertain requester failed: "
            + error.decode("utf-8", errors="replace")[-2000:]
        )
    checkpoint = json.loads(output)
    requester_pid = checkpoint["requester_pid"]
    if requester_pid != process.pid or requester_pid == os.getpid():
        raise AssertionError(
            "Uncertain request did not cross a process boundary"
        )
    return UUID(checkpoint["operation_id"]), requester_pid


async def _replacement(
    provider_id: UUID, previous_generation: int
) -> ProviderEndpointDescriptor:
    async with asyncio.timeout(15):
        while True:
            try:
                descriptor = _descriptor(provider_id)
            except (FileNotFoundError, ValueError):
                await asyncio.sleep(0.05)
                continue
            if descriptor.endpoint_generation > previous_generation:
                return descriptor
            await asyncio.sleep(0.05)


async def _run(arguments: argparse.Namespace) -> dict[str, object]:  # noqa: PLR0912, PLR0915
    provider_id: UUID = arguments.provider_instance_id
    state: Path = arguments.state_directory
    event_log = (
        Path("/var/log/stateforge-provider-tests") / state.name / "events.log"
    )
    initial = _descriptor(provider_id)
    target_path = state / "target-state.txt"
    target_digest = hashlib.sha256(target_path.read_bytes()).hexdigest()
    journal = SqliteJournal(_JOURNAL)
    await journal.open()
    manager, coordinator = await _manager(journal)
    try:
        await manager.establish(initial)
        await _wait_for_availability(
            manager, provider_id, ProviderAvailabilityState.AVAILABLE
        )
        initial_dispatches = _dispatch_ids(event_log)
        initial_count = len(initial_dispatches)
        accepted = await manager.admit_operation(
            _request(provider_id, "first")
        )
        if (
            accepted.disposition
            is not OperationAdmissionDisposition.ACCEPTED_NEW
        ):
            raise AssertionError("Agent did not accept new operation")
        await _wait_for_dispatches(event_log, initial_count + 1)
        cached = await manager.resolve_operation(
            provider_id, accepted.operation_id
        )
        if cached != accepted:
            raise AssertionError("Agent did not retain its admission result")

        # The installed Agent client, not a substitute peer, sends these calls.
        lease = await manager._operation_admission_lease(provider_id)
        client = OperationAdmissionClient(timeout_seconds=3)
        wire = _wire_request(
            provider_id=provider_id,
            generation=lease.endpoint_generation,
            session_id=lease.session_id,
            manifest_revision=lease.manifest_revision,
            operation_id=uuid4(),
        )
        replies = await asyncio.gather(
            *(client.start(lease.channel, wire) for _ in range(20))
        )
        if (
            sum(
                r.disposition is OperationAdmissionDisposition.ACCEPTED_NEW
                for r in replies
            )
            != 1
        ):
            raise AssertionError("Concurrent admission had multiple winners")
        await _wait_for_dispatches(event_log, initial_count + 2)
        if len(_dispatch_ids(event_log)) != initial_count + 2:
            raise AssertionError("Concurrent admission dispatched twice")
        replay = await client.start(lease.channel, wire)
        if (
            replay.disposition
            is not OperationAdmissionDisposition.RESOLVED_EXISTING
        ):
            raise AssertionError("Provider did not resolve retained admission")
        if replay.request_fingerprint != replies[0].request_fingerprint:
            raise AssertionError("Resolved record changed fingerprint")
        changed = admission_pb2.StartOperationRequest()
        changed.CopyFrom(wire)
        changed.invocation.payload.fields["value"].string_value = "changed"
        try:
            await client.start(lease.channel, changed)
        except SfpOperationAdmissionRejectedError as error:
            if "IDEMPOTENCY_CONFLICT" not in error.rejection.reason:
                raise AssertionError(
                    "Changed content was not a conflict"
                ) from error
        else:
            raise AssertionError("Changed content was accepted")

        before_rejections = len(_dispatch_ids(event_log))
        malformed = admission_pb2.StartOperationRequest()
        malformed.CopyFrom(wire)
        malformed.invocation.operation_id = str(uuid4())
        malformed.invocation.payload.Clear()
        ParseDict(
            {"unknown": "not-a-declared-input"}, malformed.invocation.payload
        )
        try:
            await client.start(lease.channel, malformed)
        except SfpOperationAdmissionRejectedError as error:
            if "INVALID_OPERATION_REQUEST" not in error.rejection.reason:
                raise AssertionError(
                    "Schema rejection had the wrong reason"
                ) from error
        else:
            raise AssertionError(
                "Provider accepted an invalid operation payload"
            )
        try:
            await manager.admit_operation(
                _request(
                    provider_id,
                    "past",
                    deadline=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
        except SfpOperationAdmissionRejectedError as error:
            if "OPERATION_DEADLINE_EXPIRED" not in error.rejection.reason:
                raise AssertionError(
                    "Deadline rejection had the wrong reason"
                ) from error
        else:
            raise AssertionError("Agent admitted an expired operation")
        await _signal(arguments.unit_name, "SIGUSR1")
        await _wait_for_availability(
            manager, provider_id, ProviderAvailabilityState.NOT_SERVING
        )
        try:
            await manager.admit_operation(_request(provider_id, "not-ready"))
        except SfpCapabilityAssessmentUnavailableError:
            pass
        else:
            raise AssertionError(
                "Agent admitted while Provider was not serving"
            )
        try:
            await manager._operation_admission_lease(provider_id)
        except OperationAdmissionPreconditionError:
            pass
        else:
            raise AssertionError(
                "Agent exposed an admission lease while not serving"
            )
        await _signal(arguments.unit_name, "SIGUSR2")
        await _wait_for_availability(
            manager, provider_id, ProviderAvailabilityState.AVAILABLE
        )
        if len(_dispatch_ids(event_log)) != before_rejections:
            raise AssertionError("Rejected work reached the author operation")

        before_retry = tuple(
            line
            for line in _events(event_log)
            if line.startswith(_ATTEMPT_PREFIX)
        )
        (state / "drop-next-operation-response").touch()
        recovered = await manager.admit_operation(
            _request(provider_id, "retry")
        )
        if (
            recovered.disposition
            is not OperationAdmissionDisposition.RESOLVED_EXISTING
        ):
            raise AssertionError("Lost response did not resolve existing")
        await _wait_for_dispatches(event_log, initial_count + 3)
        retry_attempt = await coordinator.attempt(
            provider_id, recovered.operation_id
        )
        if (
            retry_attempt is None
            or retry_attempt.attempt_count != _EXPECTED_RETRY_ATTEMPTS
        ):
            raise AssertionError("Agent did not retry the same identity")
        after_retry = tuple(
            line
            for line in _events(event_log)
            if line.startswith(_ATTEMPT_PREFIX)
        )
        delta = after_retry[len(before_retry) :]
        if len(delta) != _EXPECTED_RETRY_ATTEMPTS or delta[0] != delta[1]:
            raise AssertionError("Agent retry changed immutable request bytes")
        if "operation-admission-response:dropped" not in _events(event_log):
            raise AssertionError("Fault hook did not discard a response")

        await manager.close()
        await journal.close()
        rebuilt_id, uncertain_requester_pid = await _spawn_uncertain_requester(
            arguments
        )
        await _wait_for_dispatches(event_log, initial_count + 4)
        journal = SqliteJournal(_JOURNAL)
        await journal.open()
        manager, coordinator = await _manager(journal)
        await manager.establish(initial)
        await _wait_for_availability(
            manager, provider_id, ProviderAvailabilityState.AVAILABLE
        )
        rebuilt = await manager.resolve_operation(provider_id, rebuilt_id)
        if (
            rebuilt.disposition
            is not OperationAdmissionDisposition.RESOLVED_EXISTING
        ):
            raise AssertionError(
                "Rebuilt Agent did not resolve Provider record"
            )
        if len(_dispatch_ids(event_log)) != initial_count + 4:
            raise AssertionError("Requester rebuild re-dispatched work")

        await manager.close()
        manager, coordinator = await _manager(journal, attempts=1)
        await manager.establish(initial)
        await _wait_for_availability(
            manager, provider_id, ProviderAvailabilityState.AVAILABLE
        )
        lost_id = await _uncertain_admission(
            manager, coordinator, provider_id, state, "provider-restart"
        )
        await _wait_for_dispatches(event_log, initial_count + 5)

        (state / "short-operation-retention").touch()
        await _restart(arguments.unit_name)
        replacement = await _replacement(
            provider_id, initial.endpoint_generation
        )
        await manager.establish(replacement)
        await _wait_for_availability(
            manager, provider_id, ProviderAvailabilityState.AVAILABLE
        )
        try:
            await manager.resolve_operation(provider_id, lost_id)
        except OperationAdmissionUnresolvedError as error:
            if "OPERATION_RECORD_UNAVAILABLE" not in error.reason:
                raise AssertionError(
                    "Restart had the wrong indeterminate reason"
                ) from error
        else:
            raise AssertionError(
                "Provider restart blindly re-admitted old work"
            )
        if len(_dispatch_ids(event_log)) != initial_count + 5:
            raise AssertionError("Indeterminate resolution re-dispatched work")
        new_lease = await manager._operation_admission_lease(provider_id)
        old_revision = new_lease.manifest_revision
        stale_revision = old_revision[:-1] + (
            "0" if old_revision[-1] != "0" else "1"
        )
        for name, generation, session_id, revision in (
            (
                "generation",
                initial.endpoint_generation,
                new_lease.session_id,
                new_lease.manifest_revision,
            ),
            (
                "session",
                replacement.endpoint_generation,
                wire.session_binding.expected_session_id,
                new_lease.manifest_revision,
            ),
            (
                "manifest",
                replacement.endpoint_generation,
                new_lease.session_id,
                stale_revision,
            ),
        ):
            stale_request = _wire_request(
                provider_id=provider_id,
                generation=generation,
                session_id=session_id,
                manifest_revision=revision,
                operation_id=uuid4(),
            )
            try:
                await client.start(new_lease.channel, stale_request)
            except SfpOperationAdmissionRejectedError as error:
                if (
                    "OPERATION_PRECONDITION_FAILED"
                    not in error.rejection.reason
                ):
                    raise AssertionError(
                        f"Stale {name} had the wrong reason"
                    ) from error
            else:
                raise AssertionError(f"Stale {name} was accepted")
        if len(_dispatch_ids(event_log)) != initial_count + 5:
            raise AssertionError(
                "Stale fence request reached author operation"
            )
        fresh = await manager.admit_operation(
            _request(provider_id, "replacement")
        )
        if fresh.disposition is not OperationAdmissionDisposition.ACCEPTED_NEW:
            raise AssertionError("Replacement generation did not admit work")
        await _wait_for_dispatches(event_log, initial_count + 6)
        fresh_attempt = await coordinator.attempt(
            provider_id, fresh.operation_id
        )
        if fresh_attempt is None:
            raise AssertionError(
                "Fresh identity was not retained by the Agent"
            )
        await asyncio.sleep(1)
        expired = admission_pb2.StartOperationRequest()
        expired.CopyFrom(
            _wire_request(
                provider_id=provider_id,
                generation=replacement.endpoint_generation,
                session_id=new_lease.session_id,
                manifest_revision=new_lease.manifest_revision,
                operation_id=fresh.operation_id,
            )
        )
        expired.invocation.CopyFrom(fresh_attempt.invocation)
        expired.admission_mode = admission_pb2.ADMISSION_MODE_RESOLVE_ONLY
        try:
            await client.start(new_lease.channel, expired)
        except SfpOperationAdmissionRejectedError as error:
            if "OPERATION_RECORD_EXPIRED" not in error.rejection.reason:
                raise AssertionError(
                    "Expired record had the wrong reason"
                ) from error
        else:
            raise AssertionError("Expired Provider record was resolved")
        if len(_dispatch_ids(event_log)) != initial_count + 6:
            raise AssertionError("Expired identity re-dispatched work")
        expected_dispatches = (
            accepted.operation_id,
            UUID(wire.invocation.operation_id),
            recovered.operation_id,
            rebuilt_id,
            lost_id,
            fresh.operation_id,
        )
        observed_dispatches = _dispatch_ids(event_log)[initial_count:]
        if len(set(expected_dispatches)) != len(expected_dispatches):
            raise AssertionError("Scenario reused an operation identity")
        if Counter(observed_dispatches) != Counter(expected_dispatches):
            raise AssertionError(
                "Dispatches did not match admitted identities"
            )
        await _restart("stateforge-agent.service")
        agent_state = await asyncio.create_subprocess_exec(
            "/usr/bin/systemctl",
            "is-active",
            "--quiet",
            "stateforge-agent.service",
        )
        if await agent_state.wait() != 0:
            raise AssertionError("Installed Agent did not restart cleanly")
        if (
            hashlib.sha256(target_path.read_bytes()).hexdigest()
            != target_digest
        ):
            raise AssertionError("Provider operation changed fixture target")
        evidence = {
            "agent_version": version("stateforge-agent"),
            "protocol_version": version("stateforge-protocol"),
            "provider_version": version("stateforge-provider"),
            "provider_instance_id": str(provider_id),
            "initial_endpoint_generation": initial.endpoint_generation,
            "replacement_endpoint_generation": replacement.endpoint_generation,
            "final_socket_path": str(replacement.socket_path),
            "accepted_new_operation_id": str(accepted.operation_id),
            "accepted_new_fingerprint": accepted.request_fingerprint,
            "resolved_existing": replay.disposition.value,
            "concurrent_requests": len(replies),
            "concurrent_accepted_new": 1,
            "lost_response_recovered": recovered.disposition.value,
            "lost_response_attempts": retry_attempt.attempt_count,
            "requester_rebuild_resolved": rebuilt.disposition.value,
            "uncertain_requester_pid": uncertain_requester_pid,
            "resolving_requester_pid": os.getpid(),
            "provider_restart_indeterminate": True,
            "expired_record_rejected": True,
            "schema_rejected": True,
            "deadline_rejected": True,
            "readiness_rejected_and_recovered": True,
            "agent_service_restarted": True,
            "stale_generation_rejected": True,
            "stale_session_rejected": True,
            "stale_manifest_rejected": True,
            "changed_content_rejected": True,
            "dispatches": len(observed_dispatches),
            "dispatch_operation_ids": [
                str(operation_id) for operation_id in observed_dispatches
            ],
            "target_unchanged": True,
        }
        if _SECRET in json.dumps(evidence):
            raise AssertionError("Sensitive operation content leaked")
        return evidence
    finally:
        await manager.close()
        await journal.close()


def main() -> None:
    """Emit only bounded, secret-safe JSON evidence to stdout."""
    arguments = _arguments()
    sys.stdout.write(
        json.dumps(
            asyncio.run(
                _prepare_uncertain_process(arguments)
                if arguments.prepare_uncertain
                else _run(arguments)
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
