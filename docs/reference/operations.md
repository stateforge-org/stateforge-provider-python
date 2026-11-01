# Operation API

Operation handlers are declared with [`@operation`](declarations.md). The
runtime supplies the typed request and, when declared, an `OperationContext`.
Authors return their annotated result model or raise a typed terminal outcome;
they never construct SFP messages.

## Execution context

::: stateforge_provider.operations.OperationContext

::: stateforge_provider.operations.FrozenJsonValue

## Progress

::: stateforge_provider.operations.OperationProgressPolicy

::: stateforge_provider.operations.ProgressPercentageMode

::: stateforge_provider.operations.OperationProgressError

## Failures and cancellation

::: stateforge_provider.operations.OperationFailedError

::: stateforge_provider.operations.OperationCancelledError

::: stateforge_provider.operations.OperationEffects

::: stateforge_provider.operations.OperationSideEffects

::: stateforge_provider.operations.OperationCleanup

See [Operations, admission, and lifecycle](../operation-admission.md) for the
complete handler, progress, result, cancellation, idempotency, capacity, and
shutdown contract.
