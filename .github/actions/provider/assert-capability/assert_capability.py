"""Verify P2 against exact installed Provider and Protocol artifacts."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from uuid import uuid4

import grpc
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Struct
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)
from stateforge_protocol.sfp.capability_assessment.v1 import (
    capability_assessment_pb2,
    capability_assessment_pb2_grpc,
    validation,
)
from stateforge_protocol.sfp.manifest.v1 import (
    manifest_pb2,
    manifest_pb2_grpc,
)

_OPERATIONS = (
    "stateforge.test/echo@1",
    "stateforge.test/pending@1",
    "stateforge.test/unsupported@1",
    "stateforge.test/indeterminate@1",
)
_EXPECTED_REQUIREMENT_COUNT = 4


async def _verify(arguments: argparse.Namespace) -> dict[str, object]:
    """Handshake, accept the manifest, and call P2 on the real endpoint."""
    existing_events_text = await asyncio.to_thread(
        Path(arguments.event_log).read_text,
        encoding="utf-8",
    )
    existing_event_count = len(existing_events_text.splitlines())
    channel = grpc.aio.insecure_channel(f"unix:{arguments.socket_path}")
    await asyncio.wait_for(channel.channel_ready(), timeout=10)
    try:
        handshake = await bootstrap_pb2_grpc.BootstrapServiceStub(
            channel
        ).Handshake(
            bootstrap_pb2.HandshakeRequest(
                agent_runtime=bootstrap_pb2.AgentRuntime(
                    runtime_id=str(uuid4()),
                    software_version="1.0.0",
                ),
                expected_provider_instance_id=arguments.provider_instance_id,
                expected_endpoint_generation=arguments.endpoint_generation,
                supported_sfp_versions=[
                    bootstrap_pb2.ProtocolVersion(major=1, minor=0)
                ],
            ),
            timeout=10,
        )
        manifest = await manifest_pb2_grpc.ManifestServiceStub(
            channel
        ).GetManifest(
            manifest_pb2.GetManifestRequest(
                expected_provider_instance_id=handshake.provider_instance_id,
                expected_endpoint_generation=handshake.endpoint_generation,
                expected_session_id=handshake.session_id,
                supported_manifest_schema_versions=[1],
            ),
            timeout=10,
        )
        request = capability_assessment_pb2.AssessCapabilitiesRequest(
            assessment_request_id=str(uuid4()),
            expected_provider_instance_id=handshake.provider_instance_id,
            expected_endpoint_generation=handshake.endpoint_generation,
            expected_session_id=handshake.session_id,
            expected_manifest_revision=manifest.manifest_revision,
            execution_context=Struct(),
            operation_identifiers=_OPERATIONS,
        )
        response = await (
            capability_assessment_pb2_grpc.CapabilityAssessmentServiceStub(
                channel
            ).AssessCapabilities(request, timeout=10)
        )
    finally:
        await channel.close()

    validation.validate_assessment_exchange(request, response)
    states = [
        capability_assessment_pb2.SupportState.Name(item.support_state)
        for item in response.findings
    ]
    expected = [
        "SUPPORT_STATE_SUPPORTED",
        "SUPPORT_STATE_SUPPORTED_WITH_REQUIREMENTS",
        "SUPPORT_STATE_UNSUPPORTED",
        "SUPPORT_STATE_INDETERMINATE",
    ]
    if states != expected:
        raise RuntimeError(f"unexpected Capability states: {states}")

    events_text = await asyncio.to_thread(
        Path(arguments.event_log).read_text,
        encoding="utf-8",
    )
    events = events_text.splitlines()[existing_event_count:]
    requirement_events = Counter(
        event for event in events if event.startswith("requirement:")
    )
    if (
        set(requirement_events.values()) != {1}
        or len(requirement_events) != _EXPECTED_REQUIREMENT_COUNT
    ):
        raise RuntimeError(
            f"requirement checks were not globally deduplicated: "
            f"{requirement_events}"
        )
    if any(event.startswith("operation:") for event in events):
        raise RuntimeError("Capability Assessment dispatched an operation")

    return {
        "manifestRevision": manifest.manifest_revision,
        "operationOrder": list(_OPERATIONS),
        "requirementCheckCounts": dict(sorted(requirement_events.items())),
        "response": MessageToDict(
            response,
            always_print_fields_with_no_presence=True,
        ),
        "supportStates": states,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--provider-instance-id", required=True)
    parser.add_argument("--endpoint-generation", type=int, required=True)
    parser.add_argument("--event-log", required=True)
    return parser.parse_args()


def main() -> None:
    """Emit bounded JSON evidence for the exact installed artifacts."""
    evidence = asyncio.run(_verify(_arguments()))
    sys.stdout.write(json.dumps(evidence, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
