# Health and readiness

Every Provider hosts the standard `grpc.health.v1.Health` service on the same
Unix-domain gRPC endpoint as Bootstrap and Manifest. The runtime owns the
protobuf and streaming adaptation; Provider authors return a typed
[`HealthStatus`][stateforge_provider.health.HealthStatus].

```python
from stateforge_provider import HealthStatus, Platform, Provider


class GitProvider(Provider):
    identity = "stateforge.git"
    display_name = "Git Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)

    async def health(self) -> HealthStatus:
        if self._maintenance:
            return HealthStatus.maintenance()
        if not self._client.ready:
            return HealthStatus.degraded()
        return HealthStatus.healthy()
```

The runtime evaluates `health()` after `on_startup()` and before publishing the
endpoint descriptor. It begins fail-closed as `NOT_SERVING` and reports
`SERVING` only when startup, manifest construction, service registration, and
the author hook are ready.

## Publishing a changed state

The runtime does not poll third-party systems. When Provider-owned evidence
changes, call `await self.refresh_health()` from the Provider's own event or
monitoring path. This re-evaluates `health()` and publishes an ordered standard
Health Watch transition:

```python
async def enter_maintenance(self) -> None:
    self._maintenance = True
    await self.refresh_health()
```

`DEGRADED`, `MAINTENANCE`, and `NOT_SERVING` all map to standard gRPC
`NOT_SERVING`. Their distinction is local author intent; it is not sent as a
diagnostic string. Unexpected hook exceptions and invalid return values are
logged locally and also fail closed as `NOT_SERVING`.

## Wire behavior

- The standard Health service identity, empty Provider-wide key, and serialized
  request/response bounds come from the canonical `stateforge-protocol`
  contract rather than Provider configuration.
- The empty service name (`""`) is the authoritative Provider-wide state.
- The exact hosted Bootstrap and Manifest protobuf service names are also
  registered for diagnostics.
- `Check` returns the current state and rejects unknown names with `NOT_FOUND`.
- `Watch` immediately replays the current state and then sends every ordered
  transition.
- A Watch for an unknown name begins with `SERVICE_UNKNOWN` and stays open in
  accordance with the standard health contract.
- Observer count, per-observer buffering, and delivery time are bounded. A
  slow observer is terminated with `RESOURCE_EXHAUSTED` without blocking the
  Provider.

Calling `request_shutdown()` immediately changes all registered health keys to
`NOT_SERVING` before descriptor withdrawal, session invalidation, transport
shutdown, or author-resource cleanup. Health changes gate new work only; they
do not cancel or rewrite already admitted operations.

Provider-wide `SERVING` does not prove that the Agent accepted the manifest,
that a target supports a particular operation, or that an operation is
authorized. The Agent derives operational eligibility from health together
with current transport, handshake, generation, session, and manifest state.
Health states are not process exit statuses; see
[Process lifecycle and exit behavior](process-lifecycle.md) for the separate
executable contract.
