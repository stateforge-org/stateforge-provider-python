# Endpoint lifecycle

For each Provider process generation, the runtime follows this order:

1. Load the stable Provider instance ID.
2. Allocate a new endpoint generation.
3. Call the Provider author's `on_startup()` hook.
4. Create the generation-specific Unix domain socket.
5. Start the SFP gRPC server.
6. Secure the socket ownership and permissions.
7. Atomically publish the endpoint descriptor.
8. Serve SFP over the established channel.
9. Call the Provider author's `on_shutdown()` hook.
10. Withdraw the owned descriptor and remove the socket during shutdown.

The descriptor is published only after gRPC is ready. This prevents the Agent
from discovering an endpoint that cannot yet accept a connection. A newer
generation uses a new socket path, allowing the Agent to validate the
replacement before retiring the prior channel.

`on_startup()` runs after identity and generation allocation but before the
endpoint exists, so it cannot observe a half-published endpoint.
`on_shutdown()` runs before the descriptor and socket are withdrawn, so
Provider-owned cleanup completes while the endpoint is still reachable.
