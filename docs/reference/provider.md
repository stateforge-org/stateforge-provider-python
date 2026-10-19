# Provider API

::: stateforge_provider.provider.Provider

::: stateforge_provider.health.HealthStatus

::: stateforge_provider.ProviderServerError

## Capability Assessment ownership

`Provider` privately registers the P2 Capability Assessment service on the
same multiplexed endpoint as Bootstrap, Manifest, and Health. Provider authors
do not implement an assessment hook and never construct protocol findings.
They declare read-only requirement checks and operation associations through
the [declaration API](declarations.md).

The runtime validates the active endpoint, negotiated session, served
manifest revision, requested operations, and current process-wide readiness.
It executes each distinct referenced check at most once per request, honors
RPC cancellation and deadlines, then revalidates the session and readiness
before returning a canonically validated response. Assessment is point-in-time
evidence only: it neither executes nor authorizes an operation.
