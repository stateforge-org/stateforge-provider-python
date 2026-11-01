# Operations, admission, and lifecycle

An operation declaration becomes executable when the Provider starts. The
runtime exposes SFP Operation Admission on the same local endpoint as
Bootstrap, Manifest, Health, Capability Assessment, and Trigger Publication.
Provider authors receive typed Python values; they do not handle protobuf,
gRPC, session fences, fingerprints, or retry decisions.

## Author an operation

```python
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
        cancellable=True,
        progress=OperationProgressPolicy.determinate(),
    )
    async def restart(
        self,
        request: RestartInput,
        context: OperationContext,
    ) -> RestartResult:
        await context.report_progress("Stopping service", percentage=0)
        # Perform Provider-owned work and check cancellation between phases.
        if context.cancellation_requested:
            raise OperationCancelledError(
                OperationEffects(
                    side_effects=OperationSideEffects.NONE,
                    cleanup=OperationCleanup.NOT_REQUIRED,
                    explanation="No service change was started.",
                )
            )
        await context.report_progress("Service restarted", percentage=100)
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

It also exposes `report_progress()`, `cancellation_requested`, and
`wait_for_cancellation()`. These methods affect only this admitted operation.
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

Admission is not operation completion. The lifecycle service retains the
complete current snapshot for the same operation identity. A late observer
receives the latest snapshot immediately; an observer that falls behind sees
`updates_skipped` rather than an unbounded event history. A terminal snapshot
is immutable and replayable without dispatching author code again.

## Report progress

Progress is explicit. The runtime sends no synthetic `0%` update and does not
infer completion from `100%`. A handler reports only meaningful changes:

```python
await context.report_progress("Reading configuration")
await context.report_progress("Applying changes", percentage=50)
```

The `progress=` argument on `@operation` is optional:

| Declaration | Contract |
| --- | --- |
| omitted | Messages and percentages are optional; percentages may move in either direction and success below `100` is valid |
| `OperationProgressPolicy.determinate()` | Every update has a percentage, percentages do not decrease, and success requires a final `100` |
| `OperationProgressPolicy.indeterminate()` | Every update has a message and percentages are forbidden |
| custom `OperationProgressPolicy(...)` | Select percentage mode, monotonicity, zero start, final `100`, progress-on-success, and message requirements independently |

All percentages must be finite and between `0` and `100`. An invalid update is
not committed. If it escapes the handler, the operation ends with the
sanitized failure code `stateforge.operation.invalid_progress`.

## Return results or typed failures

A normal return must be an instance of the result model declared by the
handler annotation. The runtime validates it against the manifest schema
pinned at admission and commits that exact typed value as `SUCCEEDED`. Invalid
results become `stateforge.operation.invalid_result`; their unsafe value is
not published.

Use `OperationFailedError` for a stable business failure and include explicit
side-effect and cleanup evidence:

```python
raise OperationFailedError(
    code="example.systemd.restart_failed",
    explanation="The service did not become active.",
    effects=OperationEffects(
        side_effects=OperationSideEffects.PRESENT,
        cleanup=OperationCleanup.INCOMPLETE,
        explanation="The service remains stopped.",
    ),
)
```

Unexpected exceptions are logged locally and become the sanitized
`stateforge.operation.provider_error`. Secret-bearing payload, result, and
exception values are never copied into remote failures.

## Cooperate with cancellation

Set `cancellable=True` only when the handler can stop safely and describe what
remains. Cancellation is a request, not an asynchronous task kill:

```python
await context.wait_for_cancellation()
await remove_temporary_state()
raise OperationCancelledError(
    OperationEffects(
        side_effects=OperationSideEffects.NONE,
        cleanup=OperationCleanup.COMPLETED,
        explanation="Temporary state was removed.",
    )
)
```

The runtime returns one atomic disposition: `REQUESTED`, `ALREADY_REQUESTED`,
`ALREADY_TERMINAL`, or `UNSUPPORTED`. It commits `CANCELLED` only after author
code confirms execution has stopped. If useful work finishes after a request,
`SUCCEEDED` or `FAILED` may still win. Cancelling a Watch detaches that observer
and never cancels the business operation.

## Shutdown and failures

Shutdown stops new admissions, detaches observers, cancels active author tasks,
and waits for them before endpoint cleanup. Runtime shutdown does not fabricate
a business terminal outcome. Retained terminal records remain replayable until
their advertised expiry; active work is not discarded merely because that
time passes.

Capacity and retention are bounded by Provider configuration:

| Setting | Default |
| --- | ---: |
| `max_operation_admission_records` | 1,024 |
| `max_operation_dispatches` | 128 |
| `max_operation_observers_per_operation` | 16 |
| `operation_record_retention_seconds` | 86,400 |
| `operation_tombstone_retention_seconds` | 86,400 |
| `operation_observer_delivery_timeout_seconds` | 5 |

The admission-record limit covers live records and retained expiry tombstones
together. Tombstones are never discarded early to make room because doing so
would turn a known expired identity into an ambiguous absent identity.

One current-state slot is retained per observer. A stalled observer is detached
after the bounded delivery timeout without affecting execution or other
observers. Callers must treat `RESOURCE_EXHAUSTED` and shutdown-related
`UNAVAILABLE` as retryable only under their own bounded policy. Retrying the
same immutable request is safe because admission resolves by ID and
fingerprint.
