# StateForge Provider Implementation

This project is the reference starting point for a standalone StateForge
Provider process. A Provider owns all third-party-specific behavior and
communicates with the StateForge Agent exclusively through StateForge Protocol
(SFP).

The Developer RPC Library handles the generic SFP runtime. Provider authors
implement component-specific behavior without placing vendor logic inside the
Agent.

## Process boundary

A Provider is not loaded into the Agent process. It starts its own gRPC server,
publishes its local endpoint, and accepts a connection from the Agent. The
third-party framework or component normally remains unchanged by StateForge.

## Author experience

Subclass [`Provider`][stateforge_rpc.provider.Provider], declare a namespaced
`identity`, and start it. The runtime loads or creates the stable Provider
identity, allocates an endpoint generation, starts the protected local
endpoint, and negotiates SFP with the Agent without any of that appearing in
the author-facing API:

```python
from stateforge_rpc import Provider


class GitProvider(Provider):
    identity = "stateforge.git"

    async def on_startup(self) -> None:
        """Initialize Provider resources."""

    async def on_shutdown(self) -> None:
        """Release Provider resources."""


if __name__ == "__main__":
    GitProvider().run()
```

An application that already owns an event loop calls
`await GitProvider().serve()` instead. See
`.claude/PROVIDER_AUTHORING_VISION.md` for the complete intended author
experience, including operations, capability assessment, and backup/disaster
recovery compliance, which land incrementally as their SFP procedures do.
