# Operation API

::: stateforge_provider.operations.OperationContext

::: stateforge_provider.operations.FrozenJsonValue

Operation handlers are declared with
[`@operation`](declarations.md) and receive the Pydantic request model declared
by their signature. The optional `OperationContext` parameter is constructed
only after canonical admission succeeds and is recursively immutable.

See [Operation admission](../operation-admission.md) for the complete handler,
validation, idempotency, capacity, and shutdown contract.
