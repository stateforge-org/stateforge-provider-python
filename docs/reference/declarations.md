# Declaration API

::: stateforge_provider.declarations

::: stateforge_provider.requirements

::: stateforge_provider.ManifestError

Requirement-check methods must be asynchronous instance methods with exactly
`(self)` and a `RequirementCheckResult` return annotation. Operation
`requires` values are tuples of stable IDs declared by `@requirement_check`.
Startup rejects malformed or duplicate IDs, missing or repeated references,
invalid signatures, unresolved annotations, and metadata outside canonical
Protocol bounds.

Operation methods are asynchronous instance methods with either
`(self, request)` or `(self, request, context)`. The request and return
annotations must be `ProviderModel` subclasses. The optional third parameter
must be annotated as the public `OperationContext`; it exposes only the
operation ID, execution deadline, recursively immutable execution context,
explicit progress reporting, and cooperative cancellation state. Setting
`cancellable=True` or `progress=OperationProgressPolicy(...)` requires that
context parameter. Both decorator options are optional.
