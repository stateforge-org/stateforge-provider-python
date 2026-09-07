---
name: stateforge-protocol-development
description: Design, implement, or review StateForge SFP Protocol Buffer contracts and Agent/Provider gRPC integrations. Use for SFP schemas, generated contracts, Provider RPC services, Agent SFP clients, session behavior, compatibility, retries, streams, or protocol documentation. Do not use for SF-AOP or Control Plane work until that protocol is explicitly being designed.
---

# StateForge Protocol Development

Implement one SFP procedure at a time without weakening process boundaries,
wire compatibility, or recovery behavior.

## Establish the active contract

Before changing code:

1. Read the repository's `CLAUDE.md` and `.claude/MVP_PLAN.md`.
2. Read `.claude/PROVIDER_AUTHORING_VISION.md` and preserve its public API
   direction.
3. Read the specification page for the active SFP procedure.
4. Inspect the existing protobuf, generated contracts, Provider runtime, and
   Agent integration that directly precede it.
5. State which repository owns each required change and which upstream contract
   must land first.

Do not treat designed documentation as implemented code. Do not implement the
next procedure in the same pull request.

## Preserve the architecture

- The Agent and Provider are separate processes.
- The Developer RPC Library and Provider implementation run in the same
  Provider process.
- SFP uses one multiplexed local gRPC channel per active Provider endpoint.
- `stateforge-protocol` owns protobuf sources and generated contracts only.
- `stateforge-provider-implemntation` owns generic Provider server and
  author-facing runtime behavior, not vendor-specific integrations.
- `stateforge-agent` owns Agent-side coordination, workspaces, and
  BackupEngine tooling without embedding vendor knowledge.
- Backup engines are in-process Agent tools and never SFP peers.
- SF-AOP and the Control Plane are mandatory later MVP phases, but must not be
  invented during the active SFP phase.

Operations are namespaced string identifiers. Never encode supported operation
names as a closed enum. Backup and disaster recovery are explicit compliance
profiles over that generic operation model. A Provider performs disaster
recovery from staged data or a Provider reference; BackupEngine performs
storage restoration.

## Define durable wire semantics

For every message and RPC, make the following explicit in schema documentation
and tests:

- who creates, owns, persists, and may change each identifier;
- field presence, defaults, size limits, and validation;
- request identity, idempotency, replay, conflict, and retry behavior;
- deadlines, cancellation, stream termination, and reconnect behavior;
- which failures use gRPC status and which are domain results;
- ordering, monotonicity, terminal-state, and acknowledgement rules;
- compatibility across supported protocol versions.

Use versioned protobuf packages. Preserve field numbers and reserve removed
fields and enum values. Bounded protocol states may use enums with an
`UNSPECIFIED` zero value; extensible domain identifiers must remain strings.
Prefer standard protobuf timestamp, duration, empty, and well-known types where
their semantics fit.

Do not duplicate the standard gRPC health protocol. Do not add a protobuf solely
to make every documented procedure appear structurally identical.

## Implement across repositories in order

For a custom SFP procedure:

1. Define and verify the versioned contract in `stateforge-protocol`.
2. Implement the Provider server and author-facing surface.
3. Integrate the Agent client and state transitions.
4. Add cross-process interoperability coverage after both sides exist.

Never hand-edit generated protobuf modules. Change the source schema and
regenerate with the repository's checked-in Buf configuration.

The default Provider operation registry is in memory. Persistence is optional
and Provider-controlled; do not make it a universal runtime requirement.

Implement Provider-side protocol behavior behind the author-facing `Provider`
framework described in `.claude/PROVIDER_AUTHORING_VISION.md`. Generated stubs,
servicers, endpoint descriptors, instance identity storage, and generation
allocation are runtime details, not the normal public Provider API.

## Verify the result

Exercise success, invalid input, incompatible versions, deadlines,
disconnection, replay, and cancellation where they apply. Run Buf lint,
generation/freshness and compatibility checks for contracts, plus every
configured Ruff, mypy, pytest, package-build, and MkDocs gate in the affected
repository.
