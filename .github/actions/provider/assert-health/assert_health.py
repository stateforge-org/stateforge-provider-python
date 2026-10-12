"""Verify standard Provider Health behavior against an installed runtime."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

_BOOTSTRAP_SERVICE = "stateforge.sfp.bootstrap.v1.BootstrapService"
_MANIFEST_SERVICE = "stateforge.sfp.manifest.v1.ManifestService"


async def _read_status(
    watch: grpc.aio.UnaryStreamCall[
        health_pb2.HealthCheckRequest,
        health_pb2.HealthCheckResponse,
    ],
) -> str:
    """Read one bounded Watch response and return its enum name."""
    response = await asyncio.wait_for(watch.read(), timeout=10)
    if response is grpc.aio.EOF:
        raise RuntimeError("Health Watch ended before the expected transition")
    return health_pb2.HealthCheckResponse.ServingStatus.Name(response.status)


def _signal(unit_name: str, signal_name: str) -> None:
    """Deliver one deterministic fixture transition through systemd."""
    if not re.fullmatch(
        r"stateforge-test-[a-z][a-z0-9-]{0,20}\.service",
        unit_name,
    ):
        raise ValueError("unsafe Provider fixture unit name")
    if signal_name not in {"SIGHUP", "SIGUSR1", "SIGUSR2"}:
        raise ValueError("unsupported Provider fixture health signal")
    # Both arguments are allow-listed above and the executable is absolute.
    subprocess.run(  # noqa: S603
        ["/usr/bin/systemctl", "kill", "--signal", signal_name, unit_name],
        check=True,
        timeout=10,
    )


def _stop(unit_name: str) -> None:
    """Stop the fixture while its overall Health Watch remains active."""
    if not re.fullmatch(
        r"stateforge-test-[a-z][a-z0-9-]{0,20}\.service",
        unit_name,
    ):
        raise ValueError("unsafe Provider fixture unit name")
    subprocess.run(  # noqa: S603
        ["/usr/bin/systemctl", "stop", unit_name],
        check=True,
        timeout=20,
    )


async def _assert_shutdown_transition(
    watch: grpc.aio.UnaryStreamCall[
        health_pb2.HealthCheckRequest,
        health_pb2.HealthCheckResponse,
    ],
    unit_name: str,
) -> str:
    """Stop the Provider and require fail-closed Watch delivery."""
    stop = asyncio.create_task(asyncio.to_thread(_stop, unit_name))
    try:
        observed = await _read_status(watch)
    finally:
        await stop
    if observed != "NOT_SERVING":
        raise RuntimeError(
            f"Provider shutdown produced {observed}, expected NOT_SERVING"
        )
    return observed


async def _verify(socket_path: str, unit_name: str) -> dict[str, object]:
    """Exercise Check, Watch, author transitions, and hook failure."""
    channel = grpc.aio.insecure_channel(f"unix:{socket_path}")
    await asyncio.wait_for(channel.channel_ready(), timeout=10)
    stub = health_pb2_grpc.HealthStub(channel)
    checks: dict[str, str] = {}
    transitions: list[str] = []
    watch = stub.Watch(health_pb2.HealthCheckRequest(service=""))
    unknown_watch = None
    try:
        for service in ("", _BOOTSTRAP_SERVICE, _MANIFEST_SERVICE):
            response = await stub.Check(
                health_pb2.HealthCheckRequest(service=service),
                timeout=10,
            )
            name = health_pb2.HealthCheckResponse.ServingStatus.Name(
                response.status
            )
            if name != "SERVING":
                raise RuntimeError(f"{service!r} reported {name}")
            checks[service or "<overall>"] = name

        unknown_service = "stateforge.sfp.unknown.v1.UnknownService"
        try:
            await stub.Check(
                health_pb2.HealthCheckRequest(service=unknown_service),
                timeout=10,
            )
        except grpc.aio.AioRpcError as error:
            if error.code() is not grpc.StatusCode.NOT_FOUND:
                raise
            checks[unknown_service] = error.code().name
        else:
            raise RuntimeError("unknown Health Check did not return NOT_FOUND")

        unknown_watch = stub.Watch(
            health_pb2.HealthCheckRequest(service=unknown_service)
        )
        unknown_initial = await _read_status(unknown_watch)
        if unknown_initial != "SERVICE_UNKNOWN":
            raise RuntimeError(
                f"unknown Health Watch reported {unknown_initial}"
            )

        transitions.append(await _read_status(watch))
        for signal_name, expected in (
            ("SIGUSR1", "NOT_SERVING"),
            ("SIGUSR2", "SERVING"),
            ("SIGHUP", "NOT_SERVING"),
            ("SIGUSR2", "SERVING"),
        ):
            _signal(unit_name, signal_name)
            observed = await _read_status(watch)
            if observed != expected:
                raise RuntimeError(
                    f"{signal_name} produced {observed}, expected {expected}"
                )
            transitions.append(observed)

        transitions.append(await _assert_shutdown_transition(watch, unit_name))
    finally:
        watch.cancel()
        if unknown_watch is not None:
            unknown_watch.cancel()
        await channel.close()

    expected_transitions = [
        "SERVING",
        "NOT_SERVING",
        "SERVING",
        "NOT_SERVING",
        "SERVING",
        "NOT_SERVING",
    ]
    if transitions != expected_transitions:
        raise RuntimeError(f"unexpected Health transitions: {transitions}")
    return {
        "checks": checks,
        "unknownWatchInitial": unknown_initial,
        "watchTransitions": transitions,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--unit-name", required=True)
    return parser.parse_args()


def main() -> None:
    """Run the installed-runtime assertion and emit bounded JSON evidence."""
    arguments = _arguments()
    evidence = asyncio.run(_verify(arguments.socket_path, arguments.unit_name))
    sys.stdout.write(json.dumps(evidence, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
