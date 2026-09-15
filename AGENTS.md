# StateForge Provider Implementation agent instructions

Before planning, reviewing, or changing this repository, read these files in
order:

1. `CLAUDE.md`
2. Root `STATEFORGE_DPT.md`
3. `.agents/skills/stateforge-dpt-milestone/SKILL.md`
4. `.claude/PROVIDER_AUTHORING_VISION.md`
5. Every applicable engineering skill under `.claude/skills/`

The Provider authoring vision is an architectural contract. Internal SFP work
must preserve the public `Provider` framework, lifecycle-hook, typed-model,
and operation-decorator direction described there. Do not expose gRPC,
protobuf, endpoint descriptors, stable-instance storage, or generation
allocation as normal Provider-author responsibilities.

Follow the repository boundaries and delivery discipline in `CLAUDE.md`.
Local commits are allowed; humans own pushing, opening the PR, formal review,
and merging. Implement only the specifically requested Issue's milestone.
Do not edit the generated plan or keep a second implementation ledger.
Hand back verification evidence and a PR-description draft without marking
the DPT step done; completion is derived from the correctly associated
merged PR through DPT reconciliation.
