# Endpoint lifecycle

For each Provider process generation, the runtime follows this order:

1. Validate and freeze the static manifest declarations.
2. Load the stable Provider instance ID and allocate a new endpoint generation.
3. Call the Provider author's `on_startup()` hook.
4. Build and validate the complete immutable manifest and revision.
5. Evaluate the typed Provider health hook. Failure remains local and leaves
   the process-wide state fail-closed as `NOT_SERVING`.
6. Compose Bootstrap, Manifest, and the standard gRPC Health registration on
   one gRPC server. Health registers the exact hosted SFP service names. The
   endpoint derives its transport ceilings from those registrations while
   each RPC retains its exact procedure limit.
7. Create the generation-specific Unix socket and start gRPC.
8. Secure the socket ownership and permissions.
9. Atomically publish the descriptor, with every service ready.
10. Serve SFP, retaining negotiated sessions for manifest validation.
11. Set Provider-wide and named health to `NOT_SERVING`, then withdraw the
    owned descriptor, invalidate sessions, and stop gRPC with
    bounded grace so no new work can reach Provider-owned resources.
12. Call the Provider author's `on_shutdown()` hook within the configured
    shutdown timeout.
13. Verify and remove any remaining generation-specific socket path, then reset
    the runtime state.

The descriptor is published only after gRPC is ready. This prevents the Agent
from discovering an endpoint that cannot yet accept a connection. A newer
generation uses a new socket path, allowing the Agent to validate the
replacement before retiring the prior channel.

`on_startup()` runs after identity and generation allocation but before the
endpoint exists, so it cannot observe a half-published endpoint.
`on_shutdown()` runs only after the descriptor is withdrawn, sessions are
invalidated, and gRPC has stopped accepting or draining work. Transport
shutdown may itself remove the Unix socket; after the hook, the runtime safely
verifies and removes any remaining path before resetting its state. The
endpoint cannot serve requests while Provider-owned resources are released.

If startup was entered, `on_shutdown()` is also called after startup, snapshot,
or publication failure, to release partially initialized author resources.
It must tolerate incomplete initialization and an absent descriptor. Invalid
static declarations never enter either hook. A shutdown-hook error or timeout
does not prevent final socket cleanup. Failure cleanup only removes a
descriptor naming this generation and never replaces/removes a newer
generation's descriptor.

Manifest declarations are static for a generation; see
[Manifest declarations](manifest-authoring.md) for session lifetime, limits,
revision stability, and schema safety rules.
Health is event-driven rather than polled; see
[Health and readiness](health-reporting.md) for the public hook and Watch
semantics.
See [Runtime package ownership](runtime-architecture.md) for the boundary
between the shared endpoint and procedure-specific services.
