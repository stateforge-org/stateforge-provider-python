# Endpoint lifecycle

For each Provider process generation, the runtime follows this order:

1. Validate and freeze the static manifest declarations.
2. Load the stable Provider instance ID and allocate a new endpoint generation.
3. Call the Provider author's `on_startup()` hook.
4. Build and validate the complete immutable manifest and revision.
5. Register bootstrap and ManifestService on one gRPC server.
6. Create the generation-specific Unix socket and start gRPC.
7. Secure the socket ownership and permissions.
8. Atomically publish the descriptor, with both services ready.
9. Serve SFP, retaining negotiated sessions for manifest validation.
10. Call the Provider author's `on_shutdown()` hook, with a five-second bound.
11. Withdraw the owned descriptor, invalidate sessions, stop gRPC with bounded
    grace, and remove this generation's socket.

The descriptor is published only after gRPC is ready. This prevents the Agent
from discovering an endpoint that cannot yet accept a connection. A newer
generation uses a new socket path, allowing the Agent to validate the
replacement before retiring the prior channel.

`on_startup()` runs after identity and generation allocation but before the
endpoint exists, so it cannot observe a half-published endpoint.
`on_shutdown()` runs before the descriptor and socket are withdrawn, so
Provider-owned cleanup completes while the endpoint is still reachable.

If startup was entered, `on_shutdown()` is also called after startup, snapshot,
or publication failure, to release partially initialized author resources.
It must tolerate incomplete initialization and an absent descriptor. Invalid
static declarations never enter either hook. A shutdown-hook error or timeout
still stops the runtime. Failure cleanup only removes a descriptor naming
this generation and never replaces/removes a newer generation's descriptor.

Manifest declarations are static for a generation; see
[Manifest declarations](manifest-authoring.md) for session lifetime, limits,
revision stability, and schema safety rules.
