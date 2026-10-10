# StateForge Provider

StateForge Provider is the Python framework and runtime for standalone
StateForge Provider processes. A Provider owns all third-party-specific
behavior and communicates with the StateForge Agent exclusively through
StateForge Protocol (SFP).

The Developer RPC Library handles the generic SFP runtime. Provider authors
implement component-specific behavior without placing vendor logic inside the
Agent.

## Process boundary

A Provider is not loaded into the Agent process. It starts its own gRPC server,
publishes its local endpoint, and accepts a connection from the Agent. The
third-party framework or component normally remains unchanged by StateForge.

## Author experience

Subclass [`Provider`][stateforge_provider.provider.Provider], declare a
namespaced `identity` and the required manifest metadata, and start it. The
runtime loads or creates the stable Provider identity, allocates an endpoint
generation, starts the protected local endpoint, and negotiates SFP with the
Agent without any of that appearing in the author-facing API:

```python
from stateforge_provider import Platform, Provider


class GitProvider(Provider):
    identity = "stateforge.git"
    display_name = "Git Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"),)

    async def on_startup(self) -> None:
        """Initialize Provider resources."""

    async def on_shutdown(self) -> None:
        """Release Provider resources."""


if __name__ == "__main__":
    GitProvider().run()
```

See [Manifest declarations](manifest-authoring.md) for typed operation models,
triggers, configuration schemas, requirements, and explicit compliance roles.
An application that already owns an event loop calls
`await GitProvider().serve()` instead. See
`.claude/PROVIDER_AUTHORING_VISION.md` for the complete intended author
experience, including operations, capability assessment, and backup/disaster
recovery compliance, which land incrementally as their SFP procedures do.
