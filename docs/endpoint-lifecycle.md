# Endpoint lifecycle

For each Provider process generation, the runtime follows this order:

1. Load the stable Provider instance ID.
2. Allocate a new endpoint generation.
3. Create the generation-specific Unix domain socket.
4. Start the SFP gRPC server.
5. Secure the socket ownership and permissions.
6. Atomically publish the endpoint descriptor.
7. Serve SFP over the established channel.
8. Withdraw the owned descriptor and remove the socket during shutdown.

The descriptor is published only after gRPC is ready. This prevents the Agent
from discovering an endpoint that cannot yet accept a connection. A newer
generation uses a new socket path, allowing the Agent to validate the
replacement before retiring the prior channel.
