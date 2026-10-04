"""Demonstrate manifest declarations without protobuf or gRPC author code."""

from pydantic import SecretStr

from stateforge_rpc import (
    Platform,
    Provider,
    ProviderModel,
    RuntimeRequirement,
    Trigger,
    operation,
)


class Configuration(ProviderModel):
    """Describe configuration shape; no configured values are published."""

    endpoint: str
    token: SecretStr


class NormalizeInput(ProviderModel):
    """Describe a reference to normalize."""

    reference: str


class NormalizeResult(ProviderModel):
    """Describe a normalized reference."""

    reference: str


class ReferenceChanged(ProviderModel):
    """Describe a declared event payload; R1 does not publish events."""

    reference: str


class ReferenceProvider(Provider):
    """Declare generic reference metadata for the authoring example."""

    identity = "example.reference"
    display_name = "Reference Provider"
    version = "1.0.0"
    platforms = (Platform("linux", "x86_64"), Platform("darwin", "arm64"))
    configuration_model = Configuration
    runtime_requirements = (
        RuntimeRequirement("runtime.python", "Python interpreter", ">=3.11"),
    )
    triggers = (Trigger("example.reference/changed@1", ReferenceChanged),)

    @operation("example.reference/normalize@1")
    async def normalize(self, request: NormalizeInput) -> NormalizeResult:
        """Normalize a reference; R1 advertises but does not dispatch it."""
        return NormalizeResult(reference=request.reference.strip())


if __name__ == "__main__":
    ReferenceProvider().run()
