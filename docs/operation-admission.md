# Operation admission

An operation declaration becomes executable when the Provider starts. The
runtime exposes SFP Operation Admission on the same local endpoint as
Bootstrap, Manifest, Health, Capability Assessment, and Trigger Publication.
Provider authors receive typed Python values; they do not handle protobuf,
gRPC, session fences, fingerprints, or retry decisions.

## Author an operation

```python
from stateforge_provider import (
    OperationContext,
    Platform,
    Provider,
    ProviderModel,
    RequirementCheckResult,
    operation,
    requirement_check,
)


class RestartInput(ProviderModel):
    unit: str


class RestartResult(ProviderModel):
    restarted: bool


class ServiceProvider(Provider):
    identity = "example.systemd"
    display_name = "Example systemd Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)

    @requirement_check(
        "runtime.systemd.control",
        "The Provider can control systemd services",
    )
    async def can_control_systemd(self) -> RequirementCheckResult:
        return RequirementCheckResult.satisfied()

    @operation(
        "example.systemd/restart@1",
        requires=("runtime.systemd.control",),
        implements=("example.service.v1.restart",),
    )
    async def restart(
        self,
        request: RestartInput,
        context: OperationContext,
    ) -> RestartResult:
        return RestartResult(restarted=True)
```

The context parameter may be omitted for handlers that need only the typed
request. When present, it must be annotated as `OperationContext`.

`OperationContext` contains:

| Field | Meaning |
| --- | --- |
| `operation_id` | Immutable UUID assigned to this logical operation |
| `execution_deadline` | Absolute deadline carried by the admitted request |
| `execution_context` | Recursively read-only JSON metadata approved by the Agent |

The context contains no raw session, transport, or authorization object. A
handler cannot mutate it to change the admitted request.

## What happens before dispatch

The runtime validates each new request in this order:

1. canonical Protocol structure and message limits;
2. exact endpoint generation, session, and manifest revision;
3. a declared operation identifier;
4. required implementation-role membership;
5. JSON Schema and typed Pydantic payload validation;
6. an unexpired execution deadline;
7. current process-wide Health; and
8. fresh results from every requirement check attached to the operation.

Only then does it atomically record admission and schedule the author handler.
Rejected requests create no admission record and never invoke author code.

## Idempotency

`operation_id` names one immutable logical request. The runtime calculates the
canonical Protocol fingerprint over its invocation content.

| Later request | Result |
| --- | --- |
| Same ID and same content while the record is retained | Resolve the existing record; do not dispatch again |
| Same ID with changed immutable content | Reject with `ALREADY_EXISTS` and a typed idempotency-conflict detail |
| Unknown ID in resolve-only mode | Reject without creating a record |
| ID whose retained record expired | Return the canonical expired-record outcome while its tombstone remains |

The record is inserted before the handler task is created. Concurrent
identical requests therefore converge on one accepted record and exactly one
author dispatch.

Admission is not operation completion. R5 owns request acceptance and safe
dispatch; progress, terminal results, errors, and cancellation are reported by
the later operation-lifecycle procedure.

## Shutdown and failures

Shutdown stops new admissions, keeps retained records resolvable during the
transition, cancels active author tasks, and waits for them before endpoint
cleanup. An exception or invalid return value from author code stays local and
does not revise the immutable admission record. Payloads, execution context,
and secret-bearing fields are never copied into remote errors or CI evidence.

Capacity and retention are bounded by Provider configuration:

| Setting | Default |
| --- | ---: |
| `max_operation_admission_records` | 1,024 |
| `max_operation_dispatches` | 128 |
| `operation_record_retention_seconds` | 86,400 |
| `operation_tombstone_retention_seconds` | 86,400 |

Callers must treat `RESOURCE_EXHAUSTED` and shutdown-related `UNAVAILABLE` as
retryable only under their own bounded policy. Retrying the same immutable
request is safe because admission resolves by ID and fingerprint.
