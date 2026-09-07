# StateForge Provider authoring vision

This document is the authoritative product direction for the public Developer
RPC Library. It describes the experience that Provider authors must receive,
even while individual SFP procedures are implemented incrementally.

## Product goal

A Provider author writes ordinary asynchronous Python that integrates with a
third-party component. StateForge owns the protocol and runtime machinery that
exposes that behavior to the Agent.

The public framework combines two familiar models:

- PyTorch Lightning-style subclassing and lifecycle hooks; and
- FastAPI-style decorators for typed, namespaced operations.

Provider authors must not need to understand protobuf generation, gRPC
servicers, Unix socket ownership, endpoint descriptors, handshake messages,
or endpoint-generation replacement.

## Process boundary

The Developer RPC Library and the author's Provider implementation run in one
standalone Provider process. The StateForge Agent is a different process. The
Provider communicates with the Agent through SFP over one multiplexed local
gRPC channel.

The Provider normally integrates with the third-party component through its
supported API, SDK, command-line interface, or filesystem contract. StateForge
does not modify the third-party component merely to establish SFP.

```text
Provider implementation + Developer RPC Library
                    |
       standalone Provider process
                    |
        SFP over multiplexed local gRPC
                    |
             StateForge Agent
```

## Intended public interface

The intended public surface consists of:

- a `Provider` base class;
- `Provider.run()` for a normal executable entry point;
- `Provider.serve()` for an existing asynchronous event loop;
- overridable startup, shutdown, health, and capability hooks;
- an `@operation()` decorator for namespaced operation identifiers;
- typed and runtime-validated request and result models;
- an `OperationContext` for identity, deadlines, cancellation, workspaces,
  and progress reporting;
- a trigger-publication API; and
- documented Provider exceptions that the runtime maps to SFP outcomes.

Low-level server configuration and generated protobuf objects are not part of
the Provider-author API.

## Intended author experience

```python
from stateforge_rpc import (
    CapabilityAssessment,
    HealthStatus,
    OperationContext,
    Provider,
    ProviderModel,
    operation,
)


class ResolveReferenceInput(ProviderModel):
    repository: str
    reference: str


class ResolveReferenceOutput(ProviderModel):
    commit: str


class GitProvider(Provider):
    identity = "stateforge.git"
    display_name = "Git Provider"
    version = "1.0.0"

    async def on_startup(self) -> None:
        """Initialize Provider resources."""
        self.git = GitClient()

    async def on_shutdown(self) -> None:
        """Release Provider resources."""
        await self.git.close()

    async def health(self) -> HealthStatus:
        """Report whether the Provider can accept work."""
        return HealthStatus.healthy()

    async def assess_capability(
        self,
        operation_identifier: str,
        target: dict[str, object],
    ) -> CapabilityAssessment:
        """Assess an operation against the current target."""
        return CapabilityAssessment.supported()

    @operation("git.resolve_reference")
    async def resolve_reference(
        self,
        request: ResolveReferenceInput,
        context: OperationContext,
    ) -> ResolveReferenceOutput:
        commit = await self.git.resolve(
            repository=request.repository,
            reference=request.reference,
        )
        await context.report_progress(
            message="Git reference resolved.",
            percentage=100,
        )
        return ResolveReferenceOutput(commit=commit)


if __name__ == "__main__":
    GitProvider().run()
```

Applications that already own an event loop use:

```python
async def main() -> None:
    await GitProvider().serve()
```

`run()` owns the event loop. `serve()` runs in the caller's event loop and
blocks until the Provider shuts down.

The names above define the intended public shape. Renaming or materially
changing that shape requires an explicit product decision; it must not happen
accidentally while implementing an internal SFP procedure.

## Operations

An operation is identified by an extensible, namespaced string such as
`git.resolve_reference`. StateForge must not define a closed operation enum.

The operation identifier describes behavior; an invocation is still a tracked
execution with an immutable operation ID, deadline, cancellation state,
progress, and terminal result. Decorated methods are asynchronous, accept a
validated request and `OperationContext`, and return a validated result.

The runtime discovers decorated methods, rejects duplicate or invalid
identifiers, derives their declared schemas, and dispatches SFP requests. The
default operation registry is in memory. Provider-controlled persistence is
optional when a Provider needs stronger restart guarantees.

## Backup and disaster-recovery compliance

Backup and disaster recovery are predefined compliance profiles over generic
operations, not special transport commands. Compliance is always explicit.

```python
@operation(
    "git.create_backup_reference",
    implements="stateforge.backup.v1.prepare",
)
async def create_backup_reference(...):
    ...
```

```python
@operation(
    "git.reconstruct_repository",
    implements="stateforge.disaster_recovery.v1.reconstruct",
)
async def reconstruct_repository(...):
    ...
```

The runtime validates the claimed profile and publishes it in the Provider
manifest. It must never infer compliance from a method name.

BackupEngine remains an Agent-side tool. A compliant Provider prepares staged
data or returns a supported Provider reference. During disaster recovery, the
Agent restores stored data into an Agent-managed staging workspace and asks
the Provider to reconstruct and verify the third-party component. The Provider
does not receive a generic restore command.

## Manifest ownership

Provider authors declare metadata, operations, trigger types, model schemas,
runtime requirements, and compliance roles through the public Python API. They
do not construct the wire manifest manually.

Before publishing an endpoint, the runtime builds and validates the effective
manifest. Startup fails when declarations are incomplete, conflicting, or
invalid. The runtime calculates the manifest revision deterministically and
serves the manifest through SFP.

## Identity ownership

The Provider author declares the Provider type identity, for example
`stateforge.git`. The runtime manages installation and session identities.

| Identity | Owner | Lifetime |
| --- | --- | --- |
| `provider.identity` | Provider author | Provider implementation type |
| `provider_instance_id` | Developer RPC Library | Stable installation identity |
| `provider_runtime_id` | Developer RPC Library | One process lifetime |
| `endpoint_generation` | Developer RPC Library | Monotonic endpoint generation |
| `session_id` | SFP handshake | One negotiated session |

The runtime creates and securely persists `provider_instance_id`, locks the
instance state, allocates endpoint generations, and prevents two processes
from claiming the same instance and generation. A Provider author never passes
these values to `Provider.run()` or `Provider.serve()`.

Persisting runtime identity does not make Provider operation state persistent.
The baseline operation registry remains in memory.

## Runtime lifecycle

Before calling `on_startup()`, the runtime loads or creates the stable
identity, acquires the instance lock, allocates an endpoint generation, and
validates static declarations. It then calls `on_startup()`, builds the
effective manifest, starts the protected Unix-domain gRPC endpoint, and
atomically publishes the descriptor only after the endpoint is ready.

After publication, the runtime negotiates SFP and routes multiplexed requests
to lifecycle hooks and decorated operations. It validates every request and
result at the public boundary.

During shutdown, the runtime stops admission, performs bounded graceful
completion and cancellation, calls `on_shutdown()`, withdraws the descriptor,
stops gRPC, removes only resources owned by the current generation, and
releases the instance lock.

## Progress, cancellation, triggers, and errors

`OperationContext` exposes the operation identity, deadline, Agent-managed
workspace, cancellation state, and progress reporter without exposing gRPC.
Cancellation is cooperative and follows the SFP operation contract.

Providers publish only declared trigger identifiers through the base class.
The runtime constructs the SFP envelope, validates idempotency data, handles
acknowledgement and retry, and keeps protobuf details private.

Provider authors raise documented domain exceptions. The runtime maps them to
normalized SFP outcomes. Unexpected exceptions produce sanitized remote
failures while complete diagnostics remain in local logs. Secrets and
tracebacks must not be placed in manifests or returned to the Agent.

## Internal responsibilities

The Developer RPC Library exclusively owns:

- protobuf and gRPC adaptation;
- endpoint discovery artifacts and filesystem permissions;
- stable identity and endpoint-generation management;
- handshake and version negotiation;
- manifest construction and exchange;
- health-service exposure;
- operation dispatch, admission, progress, cancellation, and result mapping;
- trigger publication and acknowledgement; and
- safe startup, replacement, disconnection, and shutdown behavior.

`ProviderServerConfiguration`, raw gRPC servicers, generated protobuf types,
descriptor writers, and identity stores are private runtime implementation
details. They must not become the documented authoring interface.

## Repository ownership

| Repository | Responsibility |
| --- | --- |
| `stateforge-protocol` | Versioned protobuf sources and generated contracts only. |
| `stateforge-provider-implemntation` | Developer RPC Library, Provider framework, runtime server, and reference skeleton. |
| `stateforge-agent` | Agent-side SFP coordination, workspaces, and BackupEngine tooling. |

The Provider repository must not gain Agent coordination, BackupEngine logic,
Control Plane communication, or concrete vendor behavior.

## Implementation rule

Every SFP procedure must be implemented behind this public model. Temporary
low-level APIs may exist while the foundation is under construction, but they
must remain private and must not dictate the final author experience.

The governing rule is:

> A Provider author implements what the Provider does. StateForge implements
> how that behavior is exposed, discovered, negotiated, validated, executed,
> observed, and recovered through SFP.
