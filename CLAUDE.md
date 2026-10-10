# StateForge Provider repository instructions

Read root `STATEFORGE_DPT.md` for the shared milestone declaration and
generated delivery snapshot, not an editable local implementation ledger.
For every milestone assignment, read and follow
`.agents/skills/stateforge-dpt-milestone/SKILL.md`. It applies equally to
agents reached through `AGENTS.md` or `CLAUDE.md`.

Read `.claude/PROVIDER_AUTHORING_VISION.md` immediately afterward. It is the
authoritative contract for the intended Provider-developer experience.

Use `stateforge-python-development` for Python, packaging, tests, and docs;
`stateforge-protocol-development` for SFP contracts or integrations; and
`stateforge-pr-review` when drafting a PR description or assisting a review.
Those engineering skills live under `.claude/skills/`.

## Delivery discipline

- Work only on the human-selected Issue and its mapped DPT step. Use the
  Issue's acceptance criteria for implementation and DPT for ownership,
  prerequisites, and the declared result. Ask about material disagreements.
- Follow `stateforge-dpt-milestone` for dependency checks, branch context,
  verification, scoped local commits, and the human handoff. Never infer the
  assignment from queue order or start a later milestone opportunistically.
- Humans own pushing, Issue/PR mutations, PR creation, formal review, and
  merging. Local implementation commits are allowed; they do not complete a
  step. End with verification evidence and a human-readable PR draft.
- Do not edit `STATEFORGE_DPT.md`, its manifest/revision/statuses, or SQLite to
  record implementation progress. Plan changes are managed through DPT in a
  separate human-requested workflow.
- A step is delivered only after its correctly associated PR has been
  reviewed by a human and merged into the intended integration branch.
  DPT reconciliation records the GitHub-derived state. A local commit,
  passing tests, an approval, or a closed Issue alone is not completion.
- This project's current source/integration branch is `mvp/implementation`.
  Prefer the human-selected Issue branch and DPT's declared branch; never use
  descriptive placeholders such as "Existing work" as branch names.
  Issue and PR titles currently use `[TASK][MVP] Title`.

## MVP boundary

The active phase is the local SFP path between standalone Provider processes
and the Agent. SF-AOP and the StateForge Control Plane are mandatory MVP
phases, but SF-AOP is not yet designed. The completed SFP path will inform that
design. Never describe those phases as optional, post-MVP, or excluded.

Do not implement SF-AOP or Control Plane behavior in this repository.

The local SFP phase must work across Protocol, Provider, and Agent, including
backup-engine-backed backup and disaster recovery. Only afterward are the
SF-AOP contracts and Control Plane milestones defined from that proven
behavior. The end-to-end MVP must let a trigger create a coordinated snapshot
and use that snapshot for disaster recovery. These are product-level exit
conditions, not permission to implement additional milestones.

## Repository boundary

This repository provides the Python Provider framework and runtime used to
implement a standalone Provider process. The Developer RPC Library and the
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

## Provider runtime invariants

Apply these rules whenever shared endpoint, lifecycle, session, discovery, or
service code changes:

- `Provider.run()` may own its event loop and process signal handlers.
  `Provider.serve()` runs inside a caller-owned loop and must not replace
  caller-owned signal handlers or other process-global state unless the caller
  explicitly opts in and the prior state is restored.
- Treat shutdown as a phased state transition. Prevent new discovery and
  admission before author resources are released; then drain or cancel
  accepted work, perform bounded author cleanup, and finish transport and
  filesystem cleanup. Exceptions and cancellation must not skip later cleanup.
- Keep cleanup failures observable while attempting every independent cleanup
  step. A missing artifact or ownership mismatch may be an intentional no-op;
  lock, parse, permission, unlink, synchronization, and transport failures are
  operational failures. Preserve the primary failure when reporting cleanup
  problems encountered during rollback.
- Treat identity, descriptor, socket, and other discovery artifacts as a
  filesystem trust boundary. Use bounded descriptor-based I/O, avoid following
  symbolic links, validate file type, ownership, mode, and filesystem identity,
  and never remove an entry merely because it has an expected pathname.
- One Provider endpoint multiplexes multiple SFP procedures. Configure its
  transport ceiling to carry every registered procedure, while each RPC
  independently enforces its own versioned request and response limits at the
  correct boundary.
- Fixed wire and identity invariants have one authoritative, version-specific
  contract owner and are not configuration. Operational capacity, concurrency,
  and timeout policy belong in typed runtime configuration when operators may
  legitimately tune them. Do not collect unrelated values in a generic
  constants module.
- Normalize dependency-specific exceptions at the runtime boundary. Keep
  remote errors and logs bounded and sanitized without hiding actionable local
  failures.

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
