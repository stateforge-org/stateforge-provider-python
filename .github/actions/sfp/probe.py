"""Exercise installed Bootstrap and Manifest services over a Unix socket."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import grpc
from google.protobuf.json_format import MessageToDict
from stateforge_protocol.sfp.bootstrap.v1 import (
    bootstrap_pb2,
    bootstrap_pb2_grpc,
)
from stateforge_protocol.sfp.manifest.v1 import (
    manifest_pb2,
    manifest_pb2_grpc,
)


def _descriptor(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Provider descriptor must be an object")
    transport = document.get("transport")
    if not isinstance(transport, dict) or transport.get("type") != "unix":
        raise ValueError("Provider descriptor must select a Unix transport")
    return document


def _handshake_request(
    descriptor: dict[str, Any],
    *,
    provider_instance_id: str | None = None,
) -> bootstrap_pb2.HandshakeRequest:
    return bootstrap_pb2.HandshakeRequest(
        agent_runtime=bootstrap_pb2.AgentRuntime(
            runtime_id=str(uuid4()),
            software_version="0.1.0-ci",
        ),
        expected_provider_instance_id=(
            provider_instance_id or str(descriptor["provider_instance_id"])
        ),
        expected_endpoint_generation=int(descriptor["endpoint_generation"]),
        supported_sfp_versions=[
            bootstrap_pb2.ProtocolVersion(major=1, minor=0)
        ],
    )


async def _handshake(
    stub: bootstrap_pb2_grpc.BootstrapServiceStub,
    descriptor: dict[str, Any],
) -> bootstrap_pb2.HandshakeResponse:
    response = await stub.Handshake(
        _handshake_request(descriptor),
        timeout=5,
    )
    if response.provider_instance_id != descriptor["provider_instance_id"]:
        raise AssertionError(
            "Handshake returned a different Provider identity"
        )
    if response.endpoint_generation != descriptor["endpoint_generation"]:
        raise AssertionError("Handshake returned a different generation")
    if (
        response.selected_sfp_version.major,
        response.selected_sfp_version.minor,
    ) != (1, 0):
        raise AssertionError("Handshake did not negotiate SFP 1.0")
    if not response.session_id or not response.provider_runtime_id:
        raise AssertionError("Handshake omitted runtime or session identity")
    return response


async def _manifest(
    stub: manifest_pb2_grpc.ManifestServiceStub,
    handshake: bootstrap_pb2.HandshakeResponse,
) -> manifest_pb2.GetManifestResponse:
    response = await stub.GetManifest(
        manifest_pb2.GetManifestRequest(
            expected_provider_instance_id=handshake.provider_instance_id,
            expected_endpoint_generation=handshake.endpoint_generation,
            supported_manifest_schema_versions=[1],
            expected_session_id=handshake.session_id,
        ),
        timeout=5,
    )
    if response.provider_instance_id != handshake.provider_instance_id:
        raise AssertionError("Manifest returned a different Provider identity")
    if response.endpoint_generation != handshake.endpoint_generation:
        raise AssertionError("Manifest returned a different generation")
    if response.session_id != handshake.session_id:
        raise AssertionError("Manifest returned a different session")
    if response.manifest_schema_version != 1:
        raise AssertionError("Manifest did not select schema 1")
    if not response.manifest_revision.startswith("sha256:"):
        raise AssertionError("Manifest revision is not a SHA-256 identity")
    return response


async def _run(arguments: argparse.Namespace) -> dict[str, Any]:
    descriptor = _descriptor(arguments.descriptor)
    socket_path = descriptor["transport"]["socket_path"]
    channel = grpc.aio.insecure_channel(f"unix:{socket_path}")
    try:
        await asyncio.wait_for(channel.channel_ready(), timeout=5)
        bootstrap = bootstrap_pb2_grpc.BootstrapServiceStub(channel)
        manifest = manifest_pb2_grpc.ManifestServiceStub(channel)

        if arguments.command == "bootstrap":
            response = await _handshake(bootstrap, descriptor)
            return MessageToDict(
                response,
                always_print_fields_with_no_presence=True,
            )

        if arguments.command == "manifest":
            handshake = await _handshake(bootstrap, descriptor)
            response = await _manifest(manifest, handshake)
            if response.manifest.provider_identity != arguments.identity:
                raise AssertionError(
                    "Manifest Provider identity is unexpected"
                )
            if "stateforge.test/echo@1" not in response.manifest.operations:
                raise AssertionError("Manifest omitted the fixture operation")
            if "stateforge.test/changed@1" not in response.manifest.triggers:
                raise AssertionError("Manifest omitted the fixture trigger")
            return MessageToDict(
                response,
                always_print_fields_with_no_presence=True,
            )

        wrong_identity = str(uuid4())
        try:
            await bootstrap.Handshake(
                _handshake_request(
                    descriptor,
                    provider_instance_id=wrong_identity,
                ),
                timeout=5,
            )
        except grpc.aio.AioRpcError as error:
            if error.code() is not grpc.StatusCode.FAILED_PRECONDITION:
                raise AssertionError(
                    "Invalid Bootstrap peer returned an unexpected status"
                ) from error
            invalid_bootstrap = error.code().name
        else:
            raise AssertionError("Invalid Bootstrap peer was accepted")

        handshake = await _handshake(bootstrap, descriptor)
        try:
            await manifest.GetManifest(
                manifest_pb2.GetManifestRequest(
                    expected_provider_instance_id=(
                        handshake.provider_instance_id
                    ),
                    expected_endpoint_generation=(
                        handshake.endpoint_generation
                    ),
                    supported_manifest_schema_versions=[1],
                    expected_session_id=str(uuid4()),
                ),
                timeout=5,
            )
        except grpc.aio.AioRpcError as error:
            if error.code() is not grpc.StatusCode.FAILED_PRECONDITION:
                raise AssertionError(
                    "Invalid Manifest peer returned an unexpected status"
                ) from error
            invalid_manifest = error.code().name
        else:
            raise AssertionError("Invalid Manifest peer was accepted")

        valid_manifest = await _manifest(manifest, handshake)
        return {
            "invalid_bootstrap_status": invalid_bootstrap,
            "invalid_manifest_status": invalid_manifest,
            "valid_manifest_revision": valid_manifest.manifest_revision,
        }
    finally:
        await channel.close()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("bootstrap", "manifest", "invalid-peer"),
    )
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--identity")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    """Run the selected probe and write deterministic JSON evidence."""
    arguments = _arguments()
    if arguments.command == "manifest" and not arguments.identity:
        raise SystemExit("--identity is required for manifest assertions")
    result = asyncio.run(_run(arguments))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
