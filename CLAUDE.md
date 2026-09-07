# StateForge Provider Implementation repository instructions

Read `.claude/MVP_PLAN.md` before planning or changing this repository. It is
the delivery ledger and identifies the next reviewable Provider-runtime change.
Read `.claude/PROVIDER_AUTHORING_VISION.md` immediately afterward. It is the
authoritative contract for the intended Provider-developer experience.

Use `stateforge-python-development` for Python, packaging, tests, and docs;
`stateforge-protocol-development` for SFP server behavior; and
`stateforge-pr-review` when reviewing or drafting a pull request. Their
instructions live under `.claude/skills/`.

## Delivery discipline

- Work on one plan item at a time and do not implement future procedures
  opportunistically.
- Target `mvp/implementation`. Use `mvp/<issue-slug>` for issue branches and
  `[TASK][MVP] Title` for issue and pull-request titles.
- The user owns GitHub mutations. Do not create issues, open pull requests,
  push, or merge unless explicitly instructed.
- End each completed item with a human-readable PR draft and stop for review.
- Update `.claude/MVP_PLAN.md` only when implementation evidence changes.

## MVP boundary

The active phase is the local SFP path between standalone Provider processes
and the Agent. SF-AOP and the StateForge Control Plane are mandatory MVP
phases, but SF-AOP is not yet designed. The completed SFP path will inform that
design. Never describe those phases as optional, post-MVP, or excluded.

Do not implement SF-AOP or Control Plane behavior in this repository.

## Repository boundary

This repository provides the Developer RPC Library and reference skeleton used
to implement a standalone Provider process. The Developer RPC Library and the
Provider implementation run in that same process; there is no second
"standalone RPC process." The StateForge Agent is a different process.

The runtime exposes versioned contracts from `stateforge-protocol` over one
multiplexed local gRPC channel. It may provide generic author-facing callbacks
and lifecycle facilities, but must not contain Agent coordination,
BackupEngine behavior, Control Plane communication, or concrete vendor logic.
Third-party-specific code belongs in an actual Provider built from this
skeleton.

Operations are namespaced string identifiers. Do not define a closed enum.
Backup and disaster recovery are explicit compliance profiles over the generic
operation mechanism. The Provider does not receive a generic restore command:
for disaster recovery it reconstructs a target from staged data or a supported
Provider reference.

The default runtime state, including operation admission state, is in memory.
Do not force every Provider to use persistent storage. A Provider may add its
own persistence deliberately when its guarantees require it.

## Public authoring direction

The Developer RPC Library must combine a PyTorch Lightning-style `Provider`
base class and overridable lifecycle hooks with FastAPI-style decorators for
typed, namespaced operations. Provider authors implement asynchronous Python
behavior and start it with `Provider.run()` or `await Provider.serve()`.

Provider identity persistence, endpoint generations, Unix sockets,
descriptors, protobuf adaptation, gRPC services, SFP negotiation, manifest
construction, dispatch, and error translation belong to the runtime. Do not
make authors pass or manipulate those internal values through the normal
public API.

Backup and disaster-recovery support remains an explicit compliance claim over
generic decorated operations. Never infer compliance from method names and
never move BackupEngine behavior into a Provider.

## Python and review standards

- Follow the Python Packaging User Guide, PEP 8, PEP 257, PEP 484, and the
  Python Guide. Use the repository's `pyproject.toml` as enforced policy.
- Keep implementations direct and cohesive. Add helpers only when they
  materially improve reuse, clarity, or separation of concerns.
- Tests are automated behavioral gates. Do not substitute ad hoc manual tests
  or qualitatively review test files unless requested.
- Run Ruff, strict mypy, pytest, package build, and strict MkDocs build before
  preparing a PR draft.
- Preserve unrelated files and editor state.
