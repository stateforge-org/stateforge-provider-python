"""Verify installed R4 behavior through an independent Protocol peer."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import grpc
from google.protobuf.duration_pb2 import Duration
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)
from stateforge_protocol.sfp.manifest.v1 import (
    manifest_pb2,
    manifest_pb2_grpc,
)
from stateforge_protocol.sfp.trigger_publication.v1 import (
    trigger_publication_pb2,
    trigger_publication_pb2_grpc,
)
from stateforge_protocol.sfp.trigger_publication.v1.validation import (
    compute_publication_content_fingerprint,
)

from stateforge_provider import (
    Platform,
    Provider,
    ProviderModel,
    Trigger,
    TriggerPublicationDisposition,
    trigger,
)


class DeploymentCompleted(ProviderModel):
    """Describe one callback-driven event."""

    environment: str
    revision: str


class UnitFailed(ProviderModel):
    """Describe one continuous source event."""

    unit: str
    result: str


DEPLOYMENT_COMPLETED = Trigger(
    "stateforge.test/deployment.completed@1",
    DeploymentCompleted,
)


class TriggerProvider(Provider):
    """Exercise both supported author-facing publication styles."""

    identity = "stateforge.test.trigger_publication"
    display_name = "StateForge Trigger Publication CI Provider"
    version = "0.1.0"
    platforms = (Platform("linux", "x86_64"),)
    triggers = (DEPLOYMENT_COMPLETED,)

    def __init__(self, runtime_directory: Path) -> None:
        """Bind the fixture to its scenario-owned directories."""
        super().__init__(
            discovery_directory=runtime_directory / "discovery",
            state_directory=runtime_directory / "state",
        )
        self.failures: asyncio.Queue[UnitFailed] = asyncio.Queue()

    @trigger("stateforge.test/systemd.unit_failed@1")
    async def unit_failures(self) -> AsyncIterator[UnitFailed]:
        """Publish each observed unit transition."""
        while True:
            yield await self.failures.get()


async def _descriptor(
    directory: Path,
    provider_task: asyncio.Task[None],
) -> dict[str, object]:
    """Wait for one atomic endpoint descriptor."""
    async with asyncio.timeout(5):
        while True:
            descriptor = await asyncio.to_thread(
                _read_descriptor,
                directory,
            )
            if descriptor is not None:
                return descriptor
            if provider_task.done():
                await provider_task
            await asyncio.sleep(0.01)


async def _session(
    bootstrap: bootstrap_pb2_grpc.BootstrapServiceStub,
    manifest: manifest_pb2_grpc.ManifestServiceStub,
    descriptor: dict[str, object],
) -> tuple[
    bootstrap_pb2.HandshakeResponse,
    manifest_pb2.GetManifestResponse,
]:
    """Negotiate and accept the exact current manifest."""
    handshake = await bootstrap.Handshake(
        bootstrap_pb2.HandshakeRequest(
            agent_runtime=bootstrap_pb2.AgentRuntime(
                runtime_id=str(uuid4()),
                software_version="0.1.0",
            ),
            expected_provider_instance_id=descriptor["provider_instance_id"],
            expected_endpoint_generation=descriptor["endpoint_generation"],
            supported_sfp_versions=[
                bootstrap_pb2.ProtocolVersion(major=1, minor=0)
            ],
        ),
        timeout=3,
    )
    snapshot = await manifest.GetManifest(
        manifest_pb2.GetManifestRequest(
            expected_provider_instance_id=handshake.provider_instance_id,
            expected_endpoint_generation=handshake.endpoint_generation,
            expected_session_id=handshake.session_id,
            supported_manifest_schema_versions=[1],
        ),
        timeout=3,
    )
    return handshake, snapshot


async def _stream(
    stub: trigger_publication_pb2_grpc.TriggerPublicationServiceStub,
    handshake: bootstrap_pb2.HandshakeResponse,
    snapshot: manifest_pb2.GetManifestResponse,
) -> grpc.aio.StreamStreamCall[
    trigger_publication_pb2.StreamTriggersRequest,
    trigger_publication_pb2.StreamTriggersResponse,
]:
    """Open one fenced stream with a deliberately small window."""
    call = stub.StreamTriggers(timeout=10)
    await call.write(
        trigger_publication_pb2.StreamTriggersRequest(
            open=trigger_publication_pb2.TriggerStreamOpen(
                session_binding=trigger_publication_pb2.TriggerSessionBinding(
                    expected_provider_instance_id=(
                        handshake.provider_instance_id
                    ),
                    expected_endpoint_generation=(
                        handshake.endpoint_generation
                    ),
                    expected_session_id=handshake.session_id,
                    expected_manifest_revision=snapshot.manifest_revision,
                ),
                requested_max_in_flight_publications=1,
            )
        )
    )
    ready = await call.read()
    _require(ready.WhichOneof("message") == "ready", "ready response")
    _require(
        ready.ready.maximum_in_flight_publications == 1,
        "selected receive window",
    )
    return call


async def _ack(
    call: grpc.aio.StreamStreamCall[
        trigger_publication_pb2.StreamTriggersRequest,
        trigger_publication_pb2.StreamTriggersResponse,
    ],
    publication_id: str,
    disposition: int,
) -> None:
    """Send one terminal accepted acknowledgement."""
    await call.write(
        trigger_publication_pb2.StreamTriggersRequest(
            acknowledgement=trigger_publication_pb2.TriggerAcknowledgement(
                publication_id=publication_id,
                disposition=disposition,
            )
        )
    )


async def _prove_source_acknowledgement(
    provider: TriggerProvider,
    call: grpc.aio.StreamStreamCall[
        trigger_publication_pb2.StreamTriggersRequest,
        trigger_publication_pb2.StreamTriggersResponse,
    ],
    source_publication_id: str,
) -> tuple[str, TriggerPublicationDisposition]:
    """Prove the accepted source event no longer occupies pending state."""
    receipt = await provider.publish_trigger(
        DEPLOYMENT_COMPLETED,
        DeploymentCompleted(
            environment="verification",
            revision="queue-drained",
        ),
    )
    sentinel = (await call.read()).publication
    _require(
        sentinel.publication_id == str(receipt.publication_id),
        "source acknowledgement removed the retained publication",
    )
    _require(
        sentinel.publication_id != source_publication_id,
        "acknowledged source publication was not replayed",
    )
    await _ack(
        call,
        sentinel.publication_id,
        trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
    )
    outcome = await receipt.outcome()
    _require(
        outcome.disposition is TriggerPublicationDisposition.ACCEPTED_NEW,
        "sentinel acknowledgement outcome",
    )
    return sentinel.publication_id, outcome.disposition


async def _verify(runtime_directory: Path) -> dict[str, object]:
    """Exercise retry and reconnect replay over the installed endpoint."""
    await asyncio.to_thread(runtime_directory.mkdir, parents=True)
    await asyncio.to_thread(
        (runtime_directory / "discovery").mkdir,
        parents=True,
    )
    provider = TriggerProvider(runtime_directory)
    provider_task = asyncio.create_task(provider.serve())
    channel: grpc.aio.Channel | None = None
    socket_path: Path | None = None
    evidence: dict[str, object] | None = None
    try:
        descriptor = await _descriptor(
            runtime_directory / "discovery",
            provider_task,
        )
        socket_path = Path(str(descriptor["transport"]["socket_path"]))
        channel = grpc.aio.insecure_channel(f"unix:{socket_path}")
        bootstrap = bootstrap_pb2_grpc.BootstrapServiceStub(channel)
        manifest = manifest_pb2_grpc.ManifestServiceStub(channel)
        trigger_stub = (
            trigger_publication_pb2_grpc.TriggerPublicationServiceStub(channel)
        )
        handshake, snapshot = await _session(
            bootstrap,
            manifest,
            descriptor,
        )
        _require(
            set(snapshot.manifest.triggers)
            == {
                DEPLOYMENT_COMPLETED.identifier,
                "stateforge.test/systemd.unit_failed@1",
            },
            "manifest trigger declarations",
        )
        call = await _stream(trigger_stub, handshake, snapshot)

        receipt = await provider.publish_trigger(
            DEPLOYMENT_COMPLETED,
            DeploymentCompleted(environment="production", revision="abc123"),
            observed_at=datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
        )
        first = (await call.read()).publication
        retry_after = Duration()
        retry_after.FromMilliseconds(1)
        await call.write(
            trigger_publication_pb2.StreamTriggersRequest(
                acknowledgement=(
                    trigger_publication_pb2.TriggerAcknowledgement(
                        publication_id=first.publication_id,
                        disposition=(
                            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_REJECTED
                        ),
                        rejection=trigger_publication_pb2.TriggerRejection(
                            reason=(
                                trigger_publication_pb2.TRIGGER_REJECTION_REASON_AGENT_CAPACITY_EXHAUSTED
                            ),
                            retryable=True,
                            retry_after=retry_after,
                            explanation="Temporary capacity exhaustion",
                        ),
                    )
                )
            )
        )
        retried = (await call.read()).publication
        _require(retried == first, "immutable retry publication")
        await _ack(
            call,
            retried.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_DUPLICATE,
        )
        callback_outcome = await receipt.outcome()
        _require(
            callback_outcome.disposition
            is TriggerPublicationDisposition.ACCEPTED_DUPLICATE,
            "callback acknowledgement outcome",
        )

        await provider.failures.put(
            UnitFailed(unit="nginx.service", result="exit-code")
        )
        source_publication = (await call.read()).publication
        call.cancel()
        await asyncio.sleep(0)

        replacement_handshake, replacement_snapshot = await _session(
            bootstrap,
            manifest,
            descriptor,
        )
        replacement_call = await _stream(
            trigger_stub,
            replacement_handshake,
            replacement_snapshot,
        )
        replayed = (await replacement_call.read()).publication
        _require(replayed == source_publication, "reconnect replay")
        await _ack(
            replacement_call,
            replayed.publication_id,
            trigger_publication_pb2.TRIGGER_ACKNOWLEDGEMENT_DISPOSITION_ACCEPTED_NEW,
        )

        (
            sentinel_publication_id,
            sentinel_outcome,
        ) = await _prove_source_acknowledgement(
            provider,
            replacement_call,
            source_publication.publication_id,
        )
        await replacement_call.done_writing()
        evidence = {
            "installed_artifacts": {
                "stateforge-provider": version("stateforge-provider"),
                "stateforge-protocol": version("stateforge-protocol"),
            },
            "provider_instance_id": handshake.provider_instance_id,
            "endpoint_generation": handshake.endpoint_generation,
            "initial_session_id": handshake.session_id,
            "replacement_session_id": replacement_handshake.session_id,
            "manifest_revision": snapshot.manifest_revision,
            "declared_triggers": sorted(snapshot.manifest.triggers),
            "callback_publication_id": first.publication_id,
            "callback_fingerprint": (
                compute_publication_content_fingerprint(first)
            ),
            "callback_outcome": callback_outcome.disposition.value,
            "callback_delivery_attempts": 2,
            "source_publication_id": source_publication.publication_id,
            "source_replayed_after_reconnect": replayed == source_publication,
            "source_acknowledgement_observed": (
                sentinel_publication_id != source_publication.publication_id
            ),
            "sentinel_publication_id": sentinel_publication_id,
            "sentinel_outcome": sentinel_outcome.value,
            "selected_receive_window": 1,
        }
    finally:
        provider.request_shutdown()
        await asyncio.wait_for(provider_task, 5)
        if channel is not None:
            await channel.close()
    _require(evidence is not None, "scenario evidence")
    evidence["final_process_state"] = "stopped"
    evidence["descriptor_removed"] = not any(
        (runtime_directory / "discovery").glob("*.sfp.json")
    )
    evidence["socket_removed"] = (
        socket_path is not None and not socket_path.exists()
    )
    return evidence


def _read_descriptor(directory: Path) -> dict[str, object] | None:
    """Read one complete descriptor without blocking the event loop."""
    paths = list(directory.glob("*.sfp.json"))
    if len(paths) != 1:
        return None
    return json.loads(paths[0].read_text(encoding="utf-8"))


def _require(condition: bool, evidence: str) -> None:
    """Fail the scenario with a stable payload-free assertion message."""
    if not condition:
        raise RuntimeError(f"Trigger Publication evidence failed: {evidence}")


def _arguments() -> argparse.Namespace:
    """Parse the isolated scenario paths."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """Run the scenario and preserve bounded structured evidence."""
    arguments = _arguments()
    evidence = asyncio.run(_verify(arguments.runtime_directory))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
