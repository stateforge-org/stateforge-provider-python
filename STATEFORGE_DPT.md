<!-- STATEFORGE_DPT_MANIFEST
{
  "fingerprint": "2c23a27f29d5cee20e2810386c19e13066eed2362b5dca7295da44e9bd197f5f",
  "format": "stateforge-dpt-plan",
  "format_version": 1,
  "plan": {
    "project": {
      "generated_filename": "STATEFORGE_DPT.md",
      "name": "StateForge",
      "release": "MVP",
      "revision": 5,
      "slug": "stateforge"
    },
    "repositories": [
      {
        "alias": "agent",
        "github_default_branch": null,
        "github_full_name": "stateforge-org/stateforge-agent",
        "responsibility": "Agent-side integration, staging, and backup tooling."
      },
      {
        "alias": "protocol",
        "github_default_branch": null,
        "github_full_name": "stateforge-org/stateforge-protocol",
        "responsibility": "Versioned StateForge Protocol wire contracts."
      },
      {
        "alias": "provider",
        "github_default_branch": null,
        "github_full_name": "stateforge-org/stateforge-provider-implemntation",
        "responsibility": "Provider runtime and author-facing integration surface."
      }
    ],
    "schema_version": 1,
    "steps": [
      {
        "branch_name": "Existing work",
        "depends_on": [],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Bootstrap v1 selects one mutually supported wire version and binds discovered Provider identity and generation.",
        "sort_order": 1,
        "step_id": "P0",
        "title": "[TASK][MVP] Define SFP Handshake and Version Negotiation"
      },
      {
        "branch_name": "mvp/provider-manifest-exchange",
        "depends_on": [
          "P0"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Version the effective manifest, Provider identity, runtime requirements, configuration schema, namespaced operation identifiers, trigger declarations, and explicit backup/DR compliance profiles. Do not encode a closed operation enum.",
        "sort_order": 2,
        "step_id": "P1",
        "title": "[TASK][MVP] Define Provider Manifest Exchange Contract"
      },
      {
        "branch_name": "mvp/capability-assessment",
        "depends_on": [
          "P1"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Assess a declared operation identifier against a target and return normalized support, requirements, reasons, and assessment identity.",
        "sort_order": 3,
        "step_id": "P2",
        "title": "[TASK][MVP] Define Capability Assessment Contract"
      },
      {
        "branch_name": "mvp/trigger-publication",
        "depends_on": [
          "P1",
          "P2"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Define normalized trigger envelopes, source identity, idempotency, publication streaming, and acknowledgement dispositions without introducing SF-AOP.",
        "sort_order": 4,
        "step_id": "P3",
        "title": "[TASK][MVP] Define Trigger Publication and Acknowledgement Contract"
      },
      {
        "branch_name": "mvp/operation-admission",
        "depends_on": [
          "P1",
          "P2"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Define immutable operation envelopes, generic identifiers, request fingerprints, and deterministic admission dispositions.",
        "sort_order": 5,
        "step_id": "P4",
        "title": "[TASK][MVP] Define Operation Admission and Idempotency Contract"
      },
      {
        "branch_name": "mvp/operation-lifecycle",
        "depends_on": [
          "P4"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Define resumable progress observation, immutable terminal results, normalized errors, and explicit cancellation outcomes.",
        "sort_order": 6,
        "step_id": "P5",
        "title": "[TASK][MVP] Define Operation Progress Results and Cancellation Contract"
      },
      {
        "branch_name": "mvp/backup-preparation",
        "depends_on": [
          "P4",
          "P5"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Define staged-filesystem and Provider-reference sources, consistency boundaries, verification data, and cleanup ownership as a profile over operations.",
        "sort_order": 7,
        "step_id": "P6",
        "title": "[TASK][MVP] Define Backup Preparation Compliance Contract"
      },
      {
        "branch_name": "mvp/disaster-recovery",
        "depends_on": [
          "P6"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Define staged/restored inputs, Provider references, reconstructed targets, verification results, and replacement identity without a generic restore operation.",
        "sort_order": 8,
        "step_id": "P7",
        "title": "[TASK][MVP] Define Disaster Recovery Compliance Contract"
      },
      {
        "branch_name": "mvp/sfp-reconciliation",
        "depends_on": [
          "P3",
          "P5"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Define cursors and reconciliation messages needed to resume trigger and operation state after reconnect.",
        "sort_order": 9,
        "step_id": "P8",
        "title": "[TASK][MVP] Define SFP Disconnection Recovery Contracts"
      },
      {
        "branch_name": "mvp/sfp-contract-integration",
        "depends_on": [
          "P1",
          "P2",
          "P3",
          "P4",
          "P5",
          "P6",
          "P7",
          "P8"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Verify imports, package contents, generated-code freshness, compatibility checks, docs, and clean installation for the complete SFP v1 surface.",
        "sort_order": 10,
        "step_id": "P9",
        "title": "[TASK][MVP] Verify the Complete SFP Contract Surface"
      },
      {
        "branch_name": "Existing work",
        "depends_on": [
          "P0"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Publish a ready local endpoint and negotiate one SFP session on the Agent-established channel.",
        "sort_order": 11,
        "step_id": "R0",
        "title": "[TASK][MVP] Implement Provider Discovery and Handshake Foundation"
      },
      {
        "branch_name": "mvp/provider-manifest-exchange",
        "depends_on": [
          "P1"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Let Provider authors declare a validated effective manifest containing generic operation identifiers, triggers, runtime requirements, configuration schema, and explicit compliance profiles.",
        "sort_order": 12,
        "step_id": "R1",
        "title": "[TASK][MVP] Implement Provider Manifest Exchange"
      },
      {
        "branch_name": "mvp/provider-health-monitoring",
        "depends_on": [
          "R1"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Expose the standard gRPC health service on the same server and keep status aligned with startup, readiness, failure, and shutdown.",
        "sort_order": 13,
        "step_id": "R2",
        "title": "[TASK][MVP] Implement Provider Health and Availability Reporting"
      },
      {
        "branch_name": "mvp/capability-assessment",
        "depends_on": [
          "P2",
          "R1"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Give authors a typed way to assess a declared operation against a target and return normalized support and requirements.",
        "sort_order": 14,
        "step_id": "R3",
        "title": "[TASK][MVP] Implement Provider Capability Assessment"
      },
      {
        "branch_name": "mvp/trigger-publication",
        "depends_on": [
          "P3",
          "R3"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Publish normalized triggers, process acknowledgement dispositions, deduplicate retries, and expose clear author-facing trigger APIs. Persistence remains optional.",
        "sort_order": 15,
        "step_id": "R4",
        "title": "[TASK][MVP] Implement Trigger Publication and Acknowledgement"
      },
      {
        "branch_name": "mvp/operation-admission",
        "depends_on": [
          "P4",
          "R3"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Dispatch namespaced operation identifiers to author implementations and provide a baseline in-memory registry for new, replayed, conflicting, and terminal requests.",
        "sort_order": 16,
        "step_id": "R5",
        "title": "[TASK][MVP] Implement Operation Admission and Idempotency"
      },
      {
        "branch_name": "mvp/operation-lifecycle",
        "depends_on": [
          "P5",
          "R5"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Let authors report progress and one terminal result and handle cancellation with explicit outcomes on the multiplexed channel.",
        "sort_order": 17,
        "step_id": "R6",
        "title": "[TASK][MVP] Implement Operation Progress Results and Cancellation"
      },
      {
        "branch_name": "mvp/backup-preparation",
        "depends_on": [
          "P6",
          "R6"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Provide opt-in backup-profile APIs that prepare an Agent-owned workspace or return a supported Provider reference with consistency and verification metadata.",
        "sort_order": 18,
        "step_id": "R7",
        "title": "[TASK][MVP] Implement Backup Preparation Compliance"
      },
      {
        "branch_name": "mvp/disaster-recovery",
        "depends_on": [
          "P7",
          "R7"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Provide opt-in DR-profile APIs that reconstruct and verify a component from Agent-restored staged data or a Provider reference. Do not add a generic restore operation.",
        "sort_order": 19,
        "step_id": "R8",
        "title": "[TASK][MVP] Implement Disaster Recovery Compliance"
      },
      {
        "branch_name": "mvp/sfp-reconciliation",
        "depends_on": [
          "P8",
          "R4",
          "R6"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Re-establish the endpoint/session and reconcile trigger and operation state without forcing persistent storage on all Providers.",
        "sort_order": 20,
        "step_id": "R9",
        "title": "[TASK][MVP] Complete Provider Disconnection and Recovery"
      },
      {
        "branch_name": "mvp/provider-runtime-integration",
        "depends_on": [
          "R2",
          "R3",
          "R4",
          "R5",
          "R6",
          "R7",
          "R8",
          "R9"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Run the reference Provider as a separate process against the Agent for the full SFP lifecycle; verify public docs and distributions.",
        "sort_order": 21,
        "step_id": "R10",
        "title": "[TASK][MVP] Verify the Complete Provider Runtime"
      },
      {
        "branch_name": "Existing work",
        "depends_on": [
          "P0",
          "R0"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Procedures 1 and 2, daemon lifecycle, channel reuse, and reconnection foundation.",
        "sort_order": 22,
        "step_id": "A0",
        "title": "[TASK][MVP] Implement SFP Discovery and Handshake Foundation"
      },
      {
        "branch_name": "mvp/provider-manifest-exchange",
        "depends_on": [
          "P1",
          "R1"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Retrieve and validate the effective manifest after handshake and bind it to the active Provider generation. Preserve namespaced string operation identifiers.",
        "sort_order": 23,
        "step_id": "A1",
        "title": "[TASK][MVP] Integrate Provider Manifest Exchange"
      },
      {
        "branch_name": "mvp/provider-health-monitoring",
        "depends_on": [
          "A1",
          "R2"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Reuse the active channel's standard gRPC health service and maintain one local availability state. Control Plane reporting is not part of this PR.",
        "sort_order": 24,
        "step_id": "A2",
        "title": "[TASK][MVP] Integrate Provider Health and Availability Monitoring"
      },
      {
        "branch_name": "mvp/capability-assessment",
        "depends_on": [
          "A1",
          "P2",
          "R3"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Assess a named operation against a target using only normalized SFP data and the active manifest.",
        "sort_order": 25,
        "step_id": "A3",
        "title": "[TASK][MVP] Integrate Provider Capability Assessment"
      },
      {
        "branch_name": "mvp/trigger-publication",
        "depends_on": [
          "A3",
          "P3",
          "R4"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Validate, durably record, deduplicate, and acknowledge Provider triggers behind an internal boundary for later SF-AOP forwarding.",
        "sort_order": 26,
        "step_id": "A4",
        "title": "[TASK][MVP] Integrate Trigger Publication and Acknowledgement"
      },
      {
        "branch_name": "mvp/operation-admission",
        "depends_on": [
          "A3",
          "P4",
          "R5"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Submit immutable envelopes with string operation identifiers and handle new, replayed, conflicting, rejected, and terminal admissions.",
        "sort_order": 27,
        "step_id": "A5",
        "title": "[TASK][MVP] Integrate Operation Admission and Idempotency"
      },
      {
        "branch_name": "mvp/operation-lifecycle",
        "depends_on": [
          "A5",
          "P5",
          "R6"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Watch progress, accept one immutable terminal result, and request cancellation with explicit race-safe outcomes.",
        "sort_order": 28,
        "step_id": "A6",
        "title": "[TASK][MVP] Integrate Operation Progress Results and Cancellation"
      },
      {
        "branch_name": "mvp/backup-preparation",
        "depends_on": [
          "A6",
          "P6",
          "R7"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Own a protected staging workspace and accept validated staged-source metadata or a Provider reference from a compliant Provider.",
        "sort_order": 29,
        "step_id": "A7",
        "title": "[TASK][MVP] Integrate Backup Preparation Workspaces"
      },
      {
        "branch_name": "mvp/backup-engine-layer",
        "depends_on": [
          "A7"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Discover Python entry-point engines, validate capabilities, and expose a stable in-process engine contract. No BackupEngine RPC.",
        "sort_order": 30,
        "step_id": "A8",
        "title": "[TASK][MVP] Implement the BackupEngine Extension Layer"
      },
      {
        "branch_name": "mvp/restic-backup-engine",
        "depends_on": [
          "A8"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Safely execute restic without a shell, protect credentials, parse machine-readable results, and normalize backup, restore, verify, and removal behavior.",
        "sort_order": 31,
        "step_id": "A9",
        "title": "[TASK][MVP] Implement ResticBackupEngine"
      },
      {
        "branch_name": "mvp/disaster-recovery",
        "depends_on": [
          "A9",
          "P7",
          "R8"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Restore through BackupEngine into staging, then ask a compliant Provider to reconstruct and verify. Never send a generic Provider restore command.",
        "sort_order": 32,
        "step_id": "A10",
        "title": "[TASK][MVP] Integrate Provider Disaster Recovery Execution"
      },
      {
        "branch_name": "mvp/sfp-reconciliation",
        "depends_on": [
          "A4",
          "A6",
          "P8",
          "R9"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Revalidate and reconcile identity, generation, manifest, health, triggers, and operations after interruption.",
        "sort_order": 33,
        "step_id": "A11",
        "title": "[TASK][MVP] Complete SFP Disconnection and Recovery"
      },
      {
        "branch_name": "mvp/sfp-integration",
        "depends_on": [
          "A10",
          "A11",
          "A2",
          "A3",
          "A4",
          "A5",
          "A6",
          "A7",
          "A8",
          "A9",
          "P9",
          "R10"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Exercise the full local lifecycle between real standalone Provider and Agent processes and verify docs and distributions.",
        "sort_order": 34,
        "step_id": "A12",
        "title": "[TASK][MVP] Verify the Complete Local SFP Runtime"
      }
    ]
  }
}
STATEFORGE_DPT_MANIFEST -->

# StateForge Development Progress

> Generated by StateForge DPT. Edit the plan through DPT so every
> managed repository remains synchronized.

**Project:** StateForge  
**Release:** MVP  
**Revision:** 5

## Repositories

| Alias | GitHub repository | Responsibility |
| --- | --- | --- |
| `agent` | [stateforge-org/stateforge-agent](https://github.com/stateforge-org/stateforge-agent) | Agent-side integration, staging, and backup tooling. |
| `protocol` | [stateforge-org/stateforge-protocol](https://github.com/stateforge-org/stateforge-protocol) | Versioned StateForge Protocol wire contracts. |
| `provider` | [stateforge-org/stateforge-provider-implemntation](https://github.com/stateforge-org/stateforge-provider-implemntation) | Provider runtime and author-facing integration surface. |

## Implementation roadmap

| Step | Repository | Required implementation | Depends on | State | GitHub |
| --- | --- | --- | --- | --- | --- |
| `P0` | `protocol` | **[TASK][MVP] Define SFP Handshake and Version Negotiation**<br>Bootstrap v1 selects one mutually supported wire version and binds discovered Provider identity and generation. | — | `COMPLETED` | [Issue #1](https://github.com/stateforge-org/stateforge-protocol/issues/1) · [Pull Request #2](https://github.com/stateforge-org/stateforge-protocol/pull/2) |
| `P1` | `protocol` | **[TASK][MVP] Define Provider Manifest Exchange Contract**<br>Version the effective manifest, Provider identity, runtime requirements, configuration schema, namespaced operation identifiers, trigger declarations, and explicit backup/DR compliance profiles. Do not encode a closed operation enum. | `P0` | `PENDING` | [Issue #3](https://github.com/stateforge-org/stateforge-protocol/issues/3) |
| `P2` | `protocol` | **[TASK][MVP] Define Capability Assessment Contract**<br>Assess a declared operation identifier against a target and return normalized support, requirements, reasons, and assessment identity. | `P1` | `BLOCKED` | — |
| `P3` | `protocol` | **[TASK][MVP] Define Trigger Publication and Acknowledgement Contract**<br>Define normalized trigger envelopes, source identity, idempotency, publication streaming, and acknowledgement dispositions without introducing SF-AOP. | `P1`, `P2` | `BLOCKED` | — |
| `P4` | `protocol` | **[TASK][MVP] Define Operation Admission and Idempotency Contract**<br>Define immutable operation envelopes, generic identifiers, request fingerprints, and deterministic admission dispositions. | `P1`, `P2` | `BLOCKED` | — |
| `P5` | `protocol` | **[TASK][MVP] Define Operation Progress Results and Cancellation Contract**<br>Define resumable progress observation, immutable terminal results, normalized errors, and explicit cancellation outcomes. | `P4` | `BLOCKED` | — |
| `P6` | `protocol` | **[TASK][MVP] Define Backup Preparation Compliance Contract**<br>Define staged-filesystem and Provider-reference sources, consistency boundaries, verification data, and cleanup ownership as a profile over operations. | `P4`, `P5` | `BLOCKED` | — |
| `P7` | `protocol` | **[TASK][MVP] Define Disaster Recovery Compliance Contract**<br>Define staged/restored inputs, Provider references, reconstructed targets, verification results, and replacement identity without a generic restore operation. | `P6` | `BLOCKED` | — |
| `P8` | `protocol` | **[TASK][MVP] Define SFP Disconnection Recovery Contracts**<br>Define cursors and reconciliation messages needed to resume trigger and operation state after reconnect. | `P3`, `P5` | `BLOCKED` | — |
| `P9` | `protocol` | **[TASK][MVP] Verify the Complete SFP Contract Surface**<br>Verify imports, package contents, generated-code freshness, compatibility checks, docs, and clean installation for the complete SFP v1 surface. | `P1`, `P2`, `P3`, `P4`, `P5`, `P6`, `P7`, `P8` | `BLOCKED` | — |
| `R0` | `provider` | **[TASK][MVP] Implement Provider Discovery and Handshake Foundation**<br>Publish a ready local endpoint and negotiate one SFP session on the Agent-established channel. | `P0` | `COMPLETED` | [Issue #1](https://github.com/stateforge-org/stateforge-provider-implemntation/issues/1) · [Pull Request #2](https://github.com/stateforge-org/stateforge-provider-implemntation/pull/2) |
| `R1` | `provider` | **[TASK][MVP] Implement Provider Manifest Exchange**<br>Let Provider authors declare a validated effective manifest containing generic operation identifiers, triggers, runtime requirements, configuration schema, and explicit compliance profiles. | `P1` | `PENDING` | [Issue #3](https://github.com/stateforge-org/stateforge-provider-implemntation/issues/3) |
| `R2` | `provider` | **[TASK][MVP] Implement Provider Health and Availability Reporting**<br>Expose the standard gRPC health service on the same server and keep status aligned with startup, readiness, failure, and shutdown. | `R1` | `BLOCKED` | — |
| `R3` | `provider` | **[TASK][MVP] Implement Provider Capability Assessment**<br>Give authors a typed way to assess a declared operation against a target and return normalized support and requirements. | `P2`, `R1` | `BLOCKED` | — |
| `R4` | `provider` | **[TASK][MVP] Implement Trigger Publication and Acknowledgement**<br>Publish normalized triggers, process acknowledgement dispositions, deduplicate retries, and expose clear author-facing trigger APIs. Persistence remains optional. | `P3`, `R3` | `BLOCKED` | — |
| `R5` | `provider` | **[TASK][MVP] Implement Operation Admission and Idempotency**<br>Dispatch namespaced operation identifiers to author implementations and provide a baseline in-memory registry for new, replayed, conflicting, and terminal requests. | `P4`, `R3` | `BLOCKED` | — |
| `R6` | `provider` | **[TASK][MVP] Implement Operation Progress Results and Cancellation**<br>Let authors report progress and one terminal result and handle cancellation with explicit outcomes on the multiplexed channel. | `P5`, `R5` | `BLOCKED` | — |
| `R7` | `provider` | **[TASK][MVP] Implement Backup Preparation Compliance**<br>Provide opt-in backup-profile APIs that prepare an Agent-owned workspace or return a supported Provider reference with consistency and verification metadata. | `P6`, `R6` | `BLOCKED` | — |
| `R8` | `provider` | **[TASK][MVP] Implement Disaster Recovery Compliance**<br>Provide opt-in DR-profile APIs that reconstruct and verify a component from Agent-restored staged data or a Provider reference. Do not add a generic restore operation. | `P7`, `R7` | `BLOCKED` | — |
| `R9` | `provider` | **[TASK][MVP] Complete Provider Disconnection and Recovery**<br>Re-establish the endpoint/session and reconcile trigger and operation state without forcing persistent storage on all Providers. | `P8`, `R4`, `R6` | `BLOCKED` | — |
| `R10` | `provider` | **[TASK][MVP] Verify the Complete Provider Runtime**<br>Run the reference Provider as a separate process against the Agent for the full SFP lifecycle; verify public docs and distributions. | `R2`, `R3`, `R4`, `R5`, `R6`, `R7`, `R8`, `R9` | `BLOCKED` | — |
| `A0` | `agent` | **[TASK][MVP] Implement SFP Discovery and Handshake Foundation**<br>Procedures 1 and 2, daemon lifecycle, channel reuse, and reconnection foundation. | `P0`, `R0` | `COMPLETED` | [Issue #1](https://github.com/stateforge-org/stateforge-agent/issues/1) · [Pull Request #2](https://github.com/stateforge-org/stateforge-agent/pull/2) |
| `A1` | `agent` | **[TASK][MVP] Integrate Provider Manifest Exchange**<br>Retrieve and validate the effective manifest after handshake and bind it to the active Provider generation. Preserve namespaced string operation identifiers. | `P1`, `R1` | `BLOCKED` | — |
| `A2` | `agent` | **[TASK][MVP] Integrate Provider Health and Availability Monitoring**<br>Reuse the active channel's standard gRPC health service and maintain one local availability state. Control Plane reporting is not part of this PR. | `A1`, `R2` | `BLOCKED` | — |
| `A3` | `agent` | **[TASK][MVP] Integrate Provider Capability Assessment**<br>Assess a named operation against a target using only normalized SFP data and the active manifest. | `A1`, `P2`, `R3` | `BLOCKED` | — |
| `A4` | `agent` | **[TASK][MVP] Integrate Trigger Publication and Acknowledgement**<br>Validate, durably record, deduplicate, and acknowledge Provider triggers behind an internal boundary for later SF-AOP forwarding. | `A3`, `P3`, `R4` | `BLOCKED` | — |
| `A5` | `agent` | **[TASK][MVP] Integrate Operation Admission and Idempotency**<br>Submit immutable envelopes with string operation identifiers and handle new, replayed, conflicting, rejected, and terminal admissions. | `A3`, `P4`, `R5` | `BLOCKED` | — |
| `A6` | `agent` | **[TASK][MVP] Integrate Operation Progress Results and Cancellation**<br>Watch progress, accept one immutable terminal result, and request cancellation with explicit race-safe outcomes. | `A5`, `P5`, `R6` | `BLOCKED` | — |
| `A7` | `agent` | **[TASK][MVP] Integrate Backup Preparation Workspaces**<br>Own a protected staging workspace and accept validated staged-source metadata or a Provider reference from a compliant Provider. | `A6`, `P6`, `R7` | `BLOCKED` | — |
| `A8` | `agent` | **[TASK][MVP] Implement the BackupEngine Extension Layer**<br>Discover Python entry-point engines, validate capabilities, and expose a stable in-process engine contract. No BackupEngine RPC. | `A7` | `BLOCKED` | — |
| `A9` | `agent` | **[TASK][MVP] Implement ResticBackupEngine**<br>Safely execute restic without a shell, protect credentials, parse machine-readable results, and normalize backup, restore, verify, and removal behavior. | `A8` | `BLOCKED` | — |
| `A10` | `agent` | **[TASK][MVP] Integrate Provider Disaster Recovery Execution**<br>Restore through BackupEngine into staging, then ask a compliant Provider to reconstruct and verify. Never send a generic Provider restore command. | `A9`, `P7`, `R8` | `BLOCKED` | — |
| `A11` | `agent` | **[TASK][MVP] Complete SFP Disconnection and Recovery**<br>Revalidate and reconcile identity, generation, manifest, health, triggers, and operations after interruption. | `A4`, `A6`, `P8`, `R9` | `BLOCKED` | — |
| `A12` | `agent` | **[TASK][MVP] Verify the Complete Local SFP Runtime**<br>Exercise the full local lifecycle between real standalone Provider and Agent processes and verify docs and distributions. | `A10`, `A11`, `A2`, `A3`, `A4`, `A5`, `A6`, `A7`, `A8`, `A9`, `P9`, `R10` | `BLOCKED` | — |

## Delivery rules

- Every issue and pull request uses the labels `dpt:project:<project>`, `dpt:release:<release>`, and `dpt:step:<step-id>`.
- An open issue represents pending work.
- An open pull request represents work in review.
- A merged pull request represents completed work.
- A closed, unmerged pull request is cancelled, not completed.
- A dependent step becomes ready only when all prerequisites are complete.
- Human review remains the trust boundary for accepted work.

## Agent instructions

Before starting work, locate the requested step in this roadmap and verify
that every dependency is complete. Implement only the required result for
that step. Do not begin a downstream step merely because its repository is
available locally. Update the plan through StateForge DPT rather than editing
this generated file manually.
