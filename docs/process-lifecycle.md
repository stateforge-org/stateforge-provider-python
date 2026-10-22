# Process lifecycle and exit behavior

StateForge Provider Python is a framework, so it does not terminate its host
process or assign application-specific exit codes. The process contract
depends on which public entry point owns execution.

## Standard executable entry point

Use `Provider.run()` when the Provider is the executable:

```python
if __name__ == "__main__":
    GitProvider().run()
```

`run()` owns the event loop and installs graceful `SIGINT` and `SIGTERM`
handlers on the supported Unix runtime. StateForge deliberately relies on the
standard Python process contract instead of defining a Provider exit-code
enum:

| Outcome | Entry-point behavior | Process status |
| --- | --- | --- |
| Normal completion | `run()` returns | `0` |
| Graceful `SIGINT` or `SIGTERM` | The signal requests shutdown; `run()` returns after cleanup | `0` |
| Fatal construction, declaration, startup, publication, runtime, or shutdown failure | The exception propagates out of `run()` | `1` when left uncaught by the standard Python entry point |

The runtime never converts a fatal exception into a successful return. It
attempts the applicable endpoint and author-resource cleanup before preserving
the failure. A cleanup failure is also fatal when no earlier failure already
owns the outcome.

Only the normal `0` and uncaught-exception `1` outcomes are part of this
standard entry-point contract. Statuses produced when the operating system or
a service manager terminates the process directly—for example `SIGKILL`—are
platform and supervisor behavior, not StateForge exit codes.

## Embedded asynchronous applications

Applications that already own an event loop call `Provider.serve()`:

```python
async def main() -> None:
    provider = GitProvider()
    await provider.serve()
```

`serve()` does not install process signal handlers and never selects a numeric
exit status. It returns after a graceful shutdown or raises a fatal lifecycle
exception to the caller. The embedding application owns signal handling,
exception policy, and its eventual process result.

## Health and RPC failures are not exit codes

A health-hook exception fails closed to gRPC Health `NOT_SERVING`. The runtime
logs the local diagnostic, publishes the unavailable health state, and keeps
the Provider process alive. Health state controls eligibility for new work; it
does not encode a process result.

Likewise, gRPC statuses describe individual RPC outcomes. An expected request,
validation, or operation failure must be reported through its procedure
contract rather than terminating the shared Provider process. Process exit
status, gRPC status, Health status, and operating-system signal status are
separate channels.

## Application-specific statuses

A Provider executable may define additional statuses at its own entry-point
boundary when its deployment needs them:

```python
if __name__ == "__main__":
    try:
        GitProvider().run()
    except DeploymentConfigurationError:
        raise SystemExit(10) from None
```

Such values belong to that application and are not portable StateForge
Provider statuses. Do not catch an unrecovered fatal exception and return
success; doing so hides failure from service managers and CI.

See [Endpoint lifecycle](endpoint-lifecycle.md) for cleanup ordering and
[Health and readiness](health-reporting.md) for fail-closed health behavior.
