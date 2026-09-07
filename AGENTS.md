# StateForge Provider Implementation agent instructions

Before planning, reviewing, or changing this repository, read these files in
order:

1. `CLAUDE.md`
2. `.claude/MVP_PLAN.md`
3. `.claude/PROVIDER_AUTHORING_VISION.md`
4. Every applicable skill under `.claude/skills/`

The Provider authoring vision is an architectural contract. Internal SFP work
must preserve the public `Provider` framework, lifecycle-hook, typed-model,
and operation-decorator direction described there. Do not expose gRPC,
protobuf, endpoint descriptors, stable-instance storage, or generation
allocation as normal Provider-author responsibilities.

Follow the repository boundaries and delivery discipline in `CLAUDE.md`. The
user owns all GitHub mutations.
