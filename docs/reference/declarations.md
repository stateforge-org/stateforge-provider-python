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
