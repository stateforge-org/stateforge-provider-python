# Trigger publication

Provider authors publish typed events in two ways. Use `@trigger` for a
continuous async source. Use `publish_trigger()` when an existing callback or
hook already tells the Provider that an event occurred. Both paths enter the
same bounded runtime, use the same manifest-declared payload schema, and
produce the same P3 publication on the Provider's existing SFP endpoint.

No author-facing API exposes protobuf messages, gRPC streams, sessions,
endpoint generations, receive windows, acknowledgement enums, or retry state.

## Continuous source

The decorator turns an async-generator method into both a manifest declaration
and a managed event source. Its `AsyncIterator[PayloadModel]` return annotation
defines the trigger payload schema.

```python
import asyncio
from collections.abc import AsyncIterator

from stateforge_provider import ProviderModel, trigger


class UnitFailed(ProviderModel):
    unit: str
    result: str


async def watch_failed_transitions(unit: str) -> AsyncIterator[UnitFailed]:
    previous = ""
    while True:
        process = await asyncio.create_subprocess_exec(
            "systemctl",
            "show",
            unit,
            "--property=ActiveState,Result",
            "--value",
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        active_state, result = stdout.decode().splitlines()
        current = f"{active_state}:{result}"
        if active_state == "failed" and current != previous:
            yield UnitFailed(unit=unit, result=result)
        previous = current
        await asyncio.sleep(1)
```

Declare the source directly on the Provider:

```python
@trigger("example.systemd/unit.failed@1")
async def nginx_failures(self) -> AsyncIterator[UnitFailed]:
    async for failure in watch_failed_transitions("nginx.service"):
        yield failure
```

The runtime starts decorated sources only after the endpoint is published. It
applies backpressure when the local queue is full, validates every yielded
model, and cancels the source during Provider shutdown. An unhandled source
failure stops that source and records a payload-free local diagnostic; it does
not forge a remote event.

## Callback-driven publication

Declare callback-only triggers explicitly, then call `publish_trigger()` from
the hook that already owns the event:

```python
from stateforge_provider import ProviderModel, Trigger


class DeploymentCompleted(ProviderModel):
    environment: str
    revision: str


DEPLOYMENT_COMPLETED = Trigger(
    "example.deploy/completed@1",
    DeploymentCompleted,
)


class InfrastructureProvider(Provider):
    triggers = (DEPLOYMENT_COMPLETED,)

    async def deployment_completed(
        self,
        environment: str,
        revision: str,
    ) -> None:
        receipt = await self.publish_trigger(
            DEPLOYMENT_COMPLETED,
            DeploymentCompleted(
                environment=environment,
                revision=revision,
            ),
        )
        outcome = await receipt.outcome()
        # The application may record or react to outcome.disposition.
```

`publish_trigger()` returns after the event is validated and admitted to the
bounded local queue. It does **not** wait for an Agent connection or remote
acknowledgement. Waiting on `receipt.outcome()` is optional; delivery and retry
continue when the caller does not wait.

## Complete Provider

Both styles compose without extra lifecycle code:

```python
from collections.abc import AsyncIterator

from stateforge_provider import Platform, Provider, trigger


class InfrastructureProvider(Provider):
    identity = "example.infrastructure"
    display_name = "Infrastructure Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)
    triggers = (DEPLOYMENT_COMPLETED,)

    @trigger("example.systemd/unit.failed@1")
    async def nginx_failures(self) -> AsyncIterator[UnitFailed]:
        async for failure in watch_failed_transitions("nginx.service"):
            yield failure

    async def deployment_completed(
        self,
        environment: str,
        revision: str,
    ) -> None:
        await self.publish_trigger(
            DEPLOYMENT_COMPLETED,
            DeploymentCompleted(
                environment=environment,
                revision=revision,
            ),
        )


if __name__ == "__main__":
    InfrastructureProvider().run()
```

## Delivery behavior

The Provider runtime owns one immutable UUIDv4 and canonical content for each
logical event. It retains queued and sent-but-unacknowledged events in memory,
enforces the Agent-selected receive window, and accepts acknowledgements in
any order.

| Agent disposition | Provider behavior |
| --- | --- |
| `accepted_new` | Remove the event and resolve the receipt successfully. |
| `accepted_duplicate` | Remove the replayed event and resolve the receipt successfully. |
| Retryable rejection | Preserve the same ID and content, wait for bounded guidance or exponential backoff, and retry. |
| Non-retryable rejection | Remove the event and resolve the receipt with sanitized rejection details. |
| Stream loss | Preserve every unacknowledged event and replay it on an eligible stream. |

The default queue holds 1,024 publications. Callback admission raises
`TriggerQueueFullError` rather than dropping an older event. Decorated sources
pause until capacity becomes available. Provider shutdown stops new admission
and causes unresolved callback receipts to raise
`TriggerPublicationUnavailableError`.

R4 persistence is process-local. A clean stop or crash does not promise event
survival across process restart. Durable Provider-owned publication storage is
an explicit later extension, not an implied property of the current runtime.

## Validation and privacy

Every publication is checked against the exact trigger schema frozen into the
served manifest and then against canonical P3 size, JSON, timestamp, and
identifier limits. Wrong models, undeclared triggers, naive timestamps, and
oversized payloads fail locally with `TriggerPayloadError` before queue
admission.

Trigger declarations and payloads cannot contain credentials or secrets.
Payload models containing `SecretStr`, `SecretBytes`, or another `writeOnly`
field fail startup. Diagnostics never echo payloads, exception text, stack
traces, configured values, or third-party responses.
