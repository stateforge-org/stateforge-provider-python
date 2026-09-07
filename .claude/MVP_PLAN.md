# StateForge Provider Implementation MVP plan

This ledger tracks implementation of the Provider side of SFP in the Developer
RPC Library and reference Provider skeleton. All eleven procedures are already
designed; statuses refer only to executable runtime behavior.

All implementation items must converge on the public author experience in
`.claude/PROVIDER_AUTHORING_VISION.md`: a `Provider` base class, lifecycle
hooks, typed models, operation decorators, and simple synchronous or
asynchronous startup. Low-level SFP construction is not the final public API.

## Product-level MVP sequence

| Phase | Status | Exit condition |
| --- | --- | --- |
| Local SFP Agent-to-Provider foundation | `IN PROGRESS` | The Provider runtime implements the complete SFP server surface and interoperates with the Agent. |
| SF-AOP design and contracts | `ON HOLD` | The Agent-to-Control-Plane protocol is defined from proven SFP behavior. |
| StateForge Control Plane | `ON HOLD` | Required remote coordination and persistence are implemented. |
| End-to-end MVP integration | `ON HOLD` | Trigger, snapshot, backup, and disaster recovery work across every boundary. |

SF-AOP and the Control Plane are required MVP work, not optional future scope.
They are on hold because SF-AOP is not yet designed. This Provider repository
does not implement either boundary.

## Current SFP implementation

| # | Procedure | Status | Evidence or remaining work |
| ---: | --- | --- | --- |
| 1 | Endpoint Discovery and Channel Establishment | `IMPLEMENTED` | Stable identity loading, endpoint creation, gRPC startup, atomic descriptor publication, generation replacement, and cleanup exist behind the public `Provider` base class; the private `_server`/`_identity` runtime modules are no longer exported or documented as author-facing API. |
| 2 | Handshake and Version Negotiation | `IMPLEMENTED` | The Provider validates discovered identity/generation and negotiates a supported SFP version. |
| 3 | Provider Manifest Exchange | `BLOCKED` | Awaiting the manifest contract in `stateforge-protocol`. |
| 4 | Health and Availability Monitoring | `BLOCKED` | Standard gRPC health lifecycle is not exposed. |
| 5 | Capability Assessment | `BLOCKED` | Awaiting the contract and author-facing implementation surface. |
| 6 | Trigger Publication and Acknowledgement | `BLOCKED` | Trigger publication and acknowledgement state are absent. |
| 7 | Operation Admission and Idempotency | `BLOCKED` | Generic operation dispatch and the baseline in-memory registry are absent. |
| 8 | Backup Preparation | `BLOCKED` | Backup-compliance callbacks and normalized sources/references are absent. |
| 9 | Disaster-Recovery Execution | `BLOCKED` | DR-compliance callbacks for staged data/references are absent. |
| 10 | Progress, Results, and Cancellation | `BLOCKED` | Operation lifecycle observation and cancellation are absent. |
| 11 | Disconnection and Recovery | `PARTIAL` | Endpoint recreation exists; trigger and operation reconciliation cannot exist until those procedures do. |

`IMPLEMENTED` means runtime code and automated verification exist. `BLOCKED`
means a preceding schema or runtime step must land. GitHub merge state remains
user-owned and is not represented here.

## Ordered pull-request queue

All PRs target `mvp/implementation`. A blocked item becomes ready only after
its versioned Protocol contract and preceding Provider-runtime item are
available.

| ID | Status | Branch | Pull-request title | Required result |
| --- | --- | --- | --- | --- |
| R0 | `IMPLEMENTED` | Existing work | `[TASK][MVP] Implement Provider Discovery and Handshake Foundation` | Publish a ready local endpoint and negotiate one SFP session on the Agent-established channel. |
| R1 | `BLOCKED` | `mvp/provider-manifest-exchange` | `[TASK][MVP] Implement Provider Manifest Exchange` | Let Provider authors declare a validated effective manifest containing generic operation identifiers, triggers, runtime requirements, configuration schema, and explicit compliance profiles. |
| R2 | `BLOCKED` | `mvp/provider-health-monitoring` | `[TASK][MVP] Implement Provider Health and Availability Reporting` | Expose the standard gRPC health service on the same server and keep status aligned with startup, readiness, failure, and shutdown. |
| R3 | `BLOCKED` | `mvp/capability-assessment` | `[TASK][MVP] Implement Provider Capability Assessment` | Give authors a typed way to assess a declared operation against a target and return normalized support and requirements. |
| R4 | `BLOCKED` | `mvp/trigger-publication` | `[TASK][MVP] Implement Trigger Publication and Acknowledgement` | Publish normalized triggers, process acknowledgement dispositions, deduplicate retries, and expose clear author-facing trigger APIs. Persistence remains optional. |
| R5 | `BLOCKED` | `mvp/operation-admission` | `[TASK][MVP] Implement Operation Admission and Idempotency` | Dispatch namespaced operation identifiers to author implementations and provide a baseline in-memory registry for new, replayed, conflicting, and terminal requests. |
| R6 | `BLOCKED` | `mvp/operation-lifecycle` | `[TASK][MVP] Implement Operation Progress Results and Cancellation` | Let authors report progress and one terminal result and handle cancellation with explicit outcomes on the multiplexed channel. |
| R7 | `BLOCKED` | `mvp/backup-preparation` | `[TASK][MVP] Implement Backup Preparation Compliance` | Provide opt-in backup-profile APIs that prepare an Agent-owned workspace or return a supported Provider reference with consistency and verification metadata. |
| R8 | `BLOCKED` | `mvp/disaster-recovery` | `[TASK][MVP] Implement Disaster Recovery Compliance` | Provide opt-in DR-profile APIs that reconstruct and verify a component from Agent-restored staged data or a Provider reference. Do not add a generic restore operation. |
| R9 | `BLOCKED` | `mvp/sfp-reconciliation` | `[TASK][MVP] Complete Provider Disconnection and Recovery` | Re-establish the endpoint/session and reconcile trigger and operation state without forcing persistent storage on all Providers. |
| R10 | `BLOCKED` | `mvp/provider-runtime-integration` | `[TASK][MVP] Verify the Complete Provider Runtime` | Run the reference Provider as a separate process against the Agent for the full SFP lifecycle; verify public docs and distributions. |

## Cross-repository gates

- R1, R3-R9 begin only after their protobuf contracts land in
  `stateforge-protocol`.
- R2 uses standard `grpc.health.v1` and needs no custom StateForge schema.
- Compatible Provider work must precede the matching Agent integration PR.
- BackupEngine and Restic belong only to `stateforge-agent`; a Provider merely
  prepares or consumes normalized data at the SFP boundary.

## Definition of done

For each PR: keep the public authoring API small and typed; preserve the
standalone process boundary; add behavioral and failure tests; update MkDocs
and docstrings; pass Ruff, strict mypy, pytest, package build, and strict MkDocs
build; update this ledger; prepare the PR draft; and stop for human review.

Review each public API addition against
`.claude/PROVIDER_AUTHORING_VISION.md`. An implementation is incomplete when
it exposes protocol plumbing that the vision assigns to the runtime.
