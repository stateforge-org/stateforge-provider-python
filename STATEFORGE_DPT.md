<!-- STATEFORGE_DPT_MANIFEST
{
  "fingerprint": "6fea1cb37d77adc526c2e84ee42e8fc48c6e7f1dd2150e9bbaaf010a42df52fa",
  "format": "stateforge-dpt-plan",
  "format_version": 1,
  "plan": {
    "project": {
      "generated_filename": "STATEFORGE_DPT.md",
      "name": "StateForge",
      "plan_source_branch": "mvp/implementation",
      "release": "MVP",
      "revision": 25,
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
        "alias": "control-plane",
        "github_default_branch": "main",
        "github_full_name": "stateforge-org/stateforge-control-plane",
        "responsibility": "StateForge Control Plane"
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
        "github_full_name": "stateforge-org/stateforge-provider-python",
        "responsibility": "Provider runtime and author-facing integration surface."
      },
      {
        "alias": "sf-aop",
        "github_default_branch": "main",
        "github_full_name": "stateforge-org/stateforge-aop",
        "responsibility": "StateForge Agent Orchestration Protocol"
      }
    ],
    "schema_version": 1,
    "steps": [
      {
        "branch_name": "Existing work",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "context-98ad6546-2e2f-4091-9f24-7e734f1b2032",
            "explanation": "Read all tests",
            "path": "tests",
            "repository_alias": "agent",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 0
          }
        ],
        "depends_on": [],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Bootstrap v1 selects one mutually supported wire version and binds discovered Provider identity and generation.",
        "sort_order": 1,
        "step_id": "P0",
        "title": "[TASK][MVP] Define SFP Handshake and Version Negotiation",
        "verification_requirements": [
          {
            "explanation": "test",
            "kind": "test",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 0,
            "target": "test",
            "verification_id": "verify-680fb7ec-6b33-4a8c-b36d-6539d4e6f027"
          }
        ]
      },
      {
        "branch_name": "mvp/provider-manifest-exchange",
        "context_resources": [],
        "depends_on": [
          "P0"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Version the effective manifest, Provider identity, runtime requirements, configuration schema, namespaced operation identifiers, trigger declarations, and explicit backup/DR compliance profiles. Do not encode a closed operation enum.",
        "sort_order": 2,
        "step_id": "P1",
        "title": "[TASK][MVP] Define Provider Manifest Exchange Contract",
        "verification_requirements": [
          {
            "explanation": "Listing of files",
            "kind": "test",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 0,
            "target": "ls -al",
            "verification_id": "verify-4bb3f27e-4bfb-4e23-9675-6a9934e548b8"
          }
        ]
      },
      {
        "branch_name": "mvp/capability-assessment",
        "context_resources": [],
        "depends_on": [
          "P1"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Assess a declared operation identifier against a target and return normalized support, requirements, reasons, and assessment identity.",
        "sort_order": 3,
        "step_id": "P2",
        "title": "[TASK][MVP] Define Capability Assessment Contract",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/trigger-publication",
        "context_resources": [],
        "depends_on": [
          "P1"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "## Outcome and ownership\n\nDefine the Protocol-only SFP contract for Provider-originated, manifest-declared trigger publication and acknowledgements on an Agent-initiated bidirectional stream over the existing channel. See `docs/procedures/triggers.md` and the SFP Trigger Publication and Acknowledgement specification.\n\n## Required behavior\n\n- Define a bounded envelope with stable publication ID, versioned trigger identifier, schema-bound payload, and event time. Bind the publisher to the authenticated Provider instance and active SFP session; do not add a generic target, source, or resource identity to the envelope. Trigger-specific source/resource identity, when required, belongs in the declared trigger payload schema.\n- Specify field ownership, presence/defaults, schema validation, limits, ordering, and canonical content equality. A retransmission keeps the same ID and semantic content; ID reuse with different content is a conflict.\n- Define ACCEPTED_NEW, ACCEPTED_DUPLICATE, and REJECTED acknowledgements, rejection reasons, correlation, retryability, and stream termination/backpressure. Separate event-delivery identity from any later policy-run identity.\n- ACCEPTED_NEW means the Agent durably assumed delivery responsibility before acknowledging. How the Agent satisfies that responsibility locally or later hands work downstream is outside P3 and is not exposed to the Provider. Losing an acknowledgement permits replay, not a second logical publication.\n- State retention/replay limitations explicitly, including reconnect and optional Provider persistence. Do not promise exactly-once business execution from delivery deduplication.\n\n## Acceptance evidence\n\nShip versioned protobuf sources, generated bindings, contract documentation, and reusable valid/invalid fixtures. Cover serialization, authenticated service/session identity, unknown or undeclared trigger IDs, invalid payload/envelope/session, duplicate versus conflicting content, lost-ack replay, bounded messages, acknowledgement correlation, and the absence of generic target/source/resource fields. Describe independent Agent/Provider implementation behavior without implementing either runtime.\n\n## Non-goals\n\nNo generic target/source/resource abstraction, SF-AOP transport, Control Plane mapping, policy evaluation, trigger-to-component inference, or mandatory persistent Provider database.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 4,
        "step_id": "P3",
        "title": "[TASK][MVP] Define Trigger Publication and Acknowledgement Contract",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/operation-admission",
        "context_resources": [],
        "depends_on": [
          "P1",
          "P2"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "## Outcome and ownership\n\nDefine the Protocol-only generic operation-admission contract. Any manifest-declared operation may be invoked; backup/DR are explicit profiles, not a closed list of transport commands. See `docs/procedures/operation-admission.md` and the SFP admission specification.\n\n## Required behavior\n\n- Define an immutable invocation: Agent-assigned operation ID before contact, versioned operation identifier, normalized target, validated payload, deadline, pinned schema/profile context where applicable, and execution context. Specify field ownership, presence, limits, and current-session validation.\n- Define the canonical fingerprint projection and golden vectors. Distinguish semantic invocation fields from transport/session fields so reconnecting does not turn an identical retry into a different execution.\n- Admission is atomic before author/vendor behavior starts. A new ID creates one record and dispatch; matching ID/fingerprint resolves the existing state/result; the same ID with different content conflicts. Concurrent duplicate submissions must not dispatch twice.\n- Keep ACCEPTED_NEW and RESOLVED_EXISTING as successful admission dispositions. Invalid, undeclared, incompatible, busy, or conflicting requests use specified gRPC statuses and structured reasons; rejection creates no accepted record.\n- Define deadline boundaries, retry guidance, and externally observable retention/expiry behavior. Lost responses can be resolved with the same immutable request while state is retained; lost/expired admitted state is unresolved, not permission for automatic redispatch. A genuinely new authorized attempt needs a new ID.\n- Separate SFP delivery idempotency from the underlying action's business idempotency. Do not add execution metadata by silently changing P1 schema 1.\n\n## Acceptance evidence\n\nShip versioned sources/bindings, explicit status/reason tables, fingerprints, and contract fixtures covering defaults, invalid IDs/payloads, unknown operations, equivalent retry, changed target/payload/context, concurrent duplicate semantics, deadline-before-admission, replay of terminal records, and retention/state-loss boundaries. Contract tests do not implement a registry.\n\n## Non-goals\n\nNo Provider scheduler, Agent dispatch implementation, universal persistent registry, automatic retry of indeterminate side effects, arbitrary shell execution, SF-AOP, or policy engine.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 5,
        "step_id": "P4",
        "title": "[TASK][MVP] Define Operation Admission and Idempotency Contract",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/operation-lifecycle",
        "context_resources": [],
        "depends_on": [
          "P4"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "## Outcome and ownership\n\nDefine generic operation observation, terminal outcomes, and cancellation in Protocol, building on P4. See `docs/procedures/progress-results-cancellation.md` and the SFP lifecycle specification.\n\n## Required behavior\n\n- Specify ACCEPTED, RUNNING, CANCELLATION_REQUESTED, SUCCEEDED, FAILED, and CANCELLED, their legal transitions, presence rules, and the difference between wire status and operation outcome.\n- Observation attaches only to an already admitted operation; it never dispatches work. Replay current state/latest retained progress immediately and the immutable result when terminal.\n- Define per-operation monotonic sequence/cursor semantics, bounded retention and coalescing, gap handling, reconnect behavior, and slow-observer backpressure. Do not promise unlimited history; never discard a terminal result while its record is retained.\n- Success contains a schema-valid typed result. Failure contains structured, sanitized reasons and relevant partial-side-effect/cleanup metadata without secrets or remote tracebacks. Define invalid author-result handling.\n- Specify cancellation accepted/requested, unsupported, and already-terminal outcomes. CANCELLED means execution actually stopped, not that a request arrived. The first terminal outcome wins a completion/cancellation race and remains immutable.\n- Cancelling a Watch or losing transport does not cancel business execution. Cancellation is operation-scoped; it must not terminate the shared Provider process or unrelated streams. An RPC deadline is not proof that side effects stopped.\n\n## Acceptance evidence\n\nShip schemas/bindings, transition and error tables, and fixtures/tests for initial/late Watch, sequence replay/gaps, terminal immutability, result-schema errors, failure metadata, cancellation races, unsupported cancellation, unknown IDs, and stream termination. Document what is retained versus indeterminate.\n\n## Non-goals\n\nNo runtime task manager, full event-log service, process-kill cancellation, backup-specific transport command, or invented Control Plane response to uncertainty.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 6,
        "step_id": "P5",
        "title": "[TASK][MVP] Define Operation Progress Results and Cancellation Contract",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/provider-health-contract",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "p6-dpt-milestone-skills",
            "explanation": "DPT milestone workflow and agent handoff requirements.",
            "path": ".agents/skills",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "p6-protocol-development-skills",
            "explanation": "Protocol, Python, and PR-review engineering instructions.",
            "path": ".claude/skills",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "p6-health-procedure",
            "explanation": "Existing health overview that must become the normative client-facing procedure.",
            "path": "docs/procedures/health.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "p6-health-diagram",
            "explanation": "Existing cross-runtime sequence diagram that must match the completed contract.",
            "path": "docs/assets/diagrams/health-and-availability-monitoring.png",
            "repository_alias": "protocol",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "canonical",
            "context_id": "p6-manifest-procedure",
            "explanation": "Accepted manifest semantics that combine with service health to determine Agent eligibility.",
            "path": "docs/procedures/provider-manifest.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "canonical",
            "context_id": "p6-repository-instructions",
            "explanation": "Repository-wide protocol development and delivery rules.",
            "path": "AGENTS.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 5
          }
        ],
        "depends_on": [
          "P0",
          "P1",
          "P10"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "## Outcome and ownership\n\nDefine the Protocol contract for Provider service health and Agent operational eligibility by standardizing StateForge's use of `grpc.health.v1` on the existing multiplexed SFP channel. This milestone owns normative cross-runtime semantics and documentation; it must not introduce a custom StateForge health protobuf.\n\n## Required behavior\n\n- Specify the exact versioned SFP service name or names registered with the standard gRPC Health service and how the empty service name and unknown services are handled.\n- Define Provider lifecycle transitions for startup, validated readiness, `SERVING`, `NOT_SERVING`, degraded or maintenance state, and bounded shutdown. Stop advertising eligibility for new work before teardown.\n- Define Check as diagnostic and Watch as the authoritative ongoing health observation, including initial replay, ordered changes, bounded observers, backpressure, stream termination, retry, and recovery.\n- Separate Provider-supplied service health from Agent-derived operational eligibility. Eligibility requires current transport, a valid handshake/session/generation, a compatible accepted manifest, and `SERVING` health.\n- Fence stale health updates after session or endpoint-generation replacement, manifest rejection, reconnect, or shutdown.\n- Specify that health loss blocks new operation admission but does not rewrite, cancel, or replace already admitted operations or terminal results.\n- State explicitly that `SERVING` is not capability assessment, target-specific availability, authorization, or proof that every declared operation can currently succeed.\n- Define bounded diagnostics and sanitized failures without exposing Provider configuration, credentials, customer data, or vendor-specific probe details.\n\n- Extend the reusable P10 Protocol CI/CD framework with health-owned conformance fixtures and validation scenarios, and register them in the standard pull-request, integration, and release-candidate workflows rather than creating a duplicate top-level pipeline.\n\n## Acceptance evidence\n\nCI/CD evidence must show that the exact built Protocol artifacts contain and pass the health procedure's valid, invalid, lifecycle, compatibility, and boundary cases.\n\nPublish a complete client-facing procedure and updated sequence diagram. Cover startup and shutdown, named and unknown services, Check and Watch, initial state, state changes, Watch loss and recovery, stale-session fencing, valid health with an invalid manifest, and admitted work surviving health loss. Document independent Agent and Provider obligations and verify that no custom health protobuf, second channel, Control Plane reporting, or vendor polling contract is introduced.\n\n## Non-goals\n\nNo Provider implementation, Agent availability coordinator, capability assessment, operation admission implementation, business-operation cancellation, Control Plane status, SF-AOP contract, or vendor-specific health probes.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed SFP 1.0 contracts, public APIs, repository boundaries, and standard gRPC Health semantics. Current code wins existing disagreements with prose. New incompatible behavior requires explicit versioning. Implement only the assigned Issue, add applicable contract checks and documentation, and preserve the human-owned Issue, PR, review, and merge workflow.",
        "sort_order": 7,
        "step_id": "P6",
        "title": "[TASK][MVP] Define Provider Health and Operational Eligibility Contract",
        "verification_requirements": [
          {
            "explanation": "Keep the complete Protocol source tree valid even though this contract adds no custom health protobuf.",
            "kind": "lint",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 0,
            "target": "buf lint",
            "verification_id": "p6-buf-lint"
          },
          {
            "explanation": "Preserve all configured Python, typing, and behavioral gates.",
            "kind": "test",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 1,
            "target": ".venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest",
            "verification_id": "p6-python-checks"
          },
          {
            "explanation": "Prove the normative procedure and diagram render without documentation errors.",
            "kind": "command",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 2,
            "target": ".venv/bin/mkdocs build \u002d\u002dstrict",
            "verification_id": "p6-docs-build"
          },
          {
            "explanation": "Verify the distributable Protocol package remains buildable and unchanged health semantics introduce no packaging regression.",
            "kind": "command",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 3,
            "target": ".venv/bin/python -m build",
            "verification_id": "p6-package-build"
          },
          {
            "explanation": "A human verifies ownership boundaries, standard gRPC Health usage, lifecycle semantics, and cross-runtime clarity before merge.",
            "kind": "human",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 4,
            "target": "GitHub Review",
            "verification_id": "p6-human-review"
          }
        ]
      },
      {
        "branch_name": "mvp/protocol-ci-automation",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "p10-agent-instructions",
            "explanation": "Preserve the Protocol repository boundary, generated-plan discipline, and human delivery authority.",
            "path": "AGENTS.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "p10-package-contract",
            "explanation": "Defines the package, supported Python versions, dependencies, and quality gates.",
            "path": "pyproject.toml",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "p10-buf-contract",
            "explanation": "Canonical protobuf lint and module configuration must drive CI validation.",
            "path": "buf.yaml",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "p10-generation-contract",
            "explanation": "Canonical generation configuration must remain the source of generated bindings.",
            "path": "buf.gen.yaml",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "canonical",
            "context_id": "p10-generated-drift",
            "explanation": "Reuse or minimally adapt the generated-source drift check for local and CI parity.",
            "path": "scripts/check_generated.py",
            "repository_alias": "protocol",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "canonical",
            "context_id": "p10-protobuf-sources",
            "explanation": "Validate canonical contract sources without changing protocol semantics.",
            "path": "proto",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 5
          },
          {
            "authority": "canonical",
            "context_id": "p10-contract-tests",
            "explanation": "Existing contract tests and fixtures define the behavior the pipelines must prove.",
            "path": "tests",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 6
          },
          {
            "authority": "canonical",
            "context_id": "p10-documentation",
            "explanation": "Strict documentation validation remains part of the gate.",
            "path": "docs",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 7
          },
          {
            "authority": "canonical",
            "context_id": "p10-readme",
            "explanation": "Document local parity, workflow entry points, and tested-artifact consumption.",
            "path": "README.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 8
          }
        ],
        "depends_on": [
          "P5"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "## Outcome and ownership\n\nCreate a reusable GitHub Actions ecosystem for StateForge Protocol contract validation and Python package delivery. Generation, validation, package construction, installed-artifact verification, and evidence collection are written once and composed by pull-request, integration, release-candidate, and future publication workflows. Do not create a second protocol model or monolithic test harness.\n\n## Required behavior\n\n- Keep contract generation and package construction available through documented local commands using the canonical Buf configuration, protobuf sources, generation check, and Python metadata.\n- Organize repository-local composite actions by responsibility under `.github/actions/`: contract generation/validation, Python artifact construction, installed-package verification, and evidence collection. Scenario checks compose these actions instead of copying setup.\n- Provide reusable `workflow_call` workflows under `.github/workflows/` that build wheel and sdist once, record checksums/provenance, and upload immutable artifacts. Verification and future publication consume those exact bytes.\n- Verify Buf linting, deterministic generation, committed-binding drift, protobuf imports, ProtoJSON/schema fixtures, and the complete contract suite.\n- Install the exact wheel in clean environments outside the checkout and without repository `PYTHONPATH`; prove metadata, typed marker, generated protobuf/gRPC modules, schemas, and fixtures work on every supported Python version and applicable operating system.\n- Pin external actions to immutable SHAs; keep permissions read-only, credentials out of build/test jobs, jobs bounded, caches dependency-keyed, and artifact/evidence retention explicit.\n- Preserve bounded failure evidence and document local parity commands, action inputs/outputs, artifact identity, and how consumers reuse the tested artifact.\n- Prefer declarative actions and existing commands. Add shell or Python only where portable logic requires it; do not duplicate package, Buf, or test behavior in workflow YAML.\n\n## Acceptance evidence\n\nValidate action/workflow metadata; run Buf lint and deterministic generation/drift checks; build wheel and sdist once; verify hashes/provenance; install the exact wheel outside the checkout across supported Python versions; import representative protobuf/gRPC modules; load packaged resources; run the contract suite; and retain failure evidence. Pass Ruff, formatting, strict mypy, pytest, generated-source validation, package build, installed-package smoke tests, and strict docs.\n\n## Non-goals\n\nNo SFP semantic or protobuf changes, generated-code fork, compatibility-policy change, publication/signing, Agent or Provider runtime implementation, cross-process system-test framework, or organization-wide workflow repository.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed SFP contracts, package/import paths, generation policy, supported Python versions, repository checks, and human Issue/PR/review/merge authority. Reusable workflows own job topology, composite actions own repeated runner steps, and project commands remain the local source of truth.",
        "sort_order": 8,
        "step_id": "P10",
        "title": "[TASK][MVP] Build Reusable Protocol Package and Contract CI/CD Pipelines",
        "verification_requirements": [
          {
            "explanation": "Validate metadata, reusable-workflow syntax, immutable pins, permissions, and shell syntax.",
            "kind": "lint",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 0,
            "target": ".github/actions and .github/workflows",
            "verification_id": "p10-actions"
          },
          {
            "explanation": "Prove sources lint, generate deterministically, and match committed bindings.",
            "kind": "command",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 1,
            "target": "buf lint && buf generate && python scripts/check_generated.py",
            "verification_id": "p10-buf"
          },
          {
            "explanation": "Build wheel and sdist once and record hashes/provenance.",
            "kind": "command",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 2,
            "target": "python -m build",
            "verification_id": "p10-build"
          },
          {
            "explanation": "Install exact wheel outside checkout and verify metadata, imports, modules, typed marker, schemas, and fixtures.",
            "kind": "test",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 3,
            "target": "clean installed-artifact matrix",
            "verification_id": "p10-installed"
          },
          {
            "explanation": "Run the complete Protocol contract suite.",
            "kind": "test",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 4,
            "target": "pytest",
            "verification_id": "p10-tests"
          },
          {
            "explanation": "Preserve repository quality and docs gates.",
            "kind": "command",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 5,
            "target": "ruff check, ruff format \u002d\u002dcheck, mypy, mkdocs build \u002d\u002dstrict",
            "verification_id": "p10-repository-gates"
          },
          {
            "explanation": "Human confirms reuse of immutable artifacts and no SFP semantic changes.",
            "kind": "human",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 6,
            "target": "GitHub pull request review",
            "verification_id": "p10-human-review"
          }
        ]
      },
      {
        "branch_name": "mvp/sfp-reconciliation",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "p8-dpt-skill",
            "explanation": "Milestone workflow, cross-repository blast-radius audit, and ownership closure gate.",
            "path": ".agents/skills/stateforge-dpt-milestone",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "p8-protocol-skill",
            "explanation": "Canonical SFP ownership, compatibility, and contract-development rules.",
            "path": ".claude/skills/stateforge-protocol-development",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "p8-recovery-diagram",
            "explanation": "Recovery sequence that the completed contract and scenarios must preserve.",
            "path": "docs/assets/diagrams/disconnection-and-recovery.png",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "p8-recovery-procedure",
            "explanation": "Client-facing recovery procedure and normative behavior.",
            "path": "docs/procedures/disconnection-recovery.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "canonical",
            "context_id": "p8-repository-instructions",
            "explanation": "Repository-wide Protocol implementation and delivery rules.",
            "path": "AGENTS.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "canonical",
            "context_id": "p8-responsibility-boundaries",
            "explanation": "Single-owner boundary between versioned Protocol rules and runtime-local policy.",
            "path": "docs/reference/responsibility-boundaries.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 5
          },
          {
            "authority": "canonical",
            "context_id": "p8-protocol-sfp-surface",
            "explanation": "Every packaged SFP contract, validator, shared scalar, descriptor rule, and aggregate endpoint limit affected by recovery.",
            "path": "src/stateforge_protocol/sfp",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 6
          },
          {
            "authority": "reference",
            "context_id": "p8-agent-consumer-surface",
            "explanation": "Agent consumer surface inspected for compatibility and duplicated normative rules; this context does not authorize Agent edits.",
            "path": "src/stateforge_agent/_sfp",
            "repository_alias": "agent",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 7
          },
          {
            "authority": "reference",
            "context_id": "p8-provider-consumer-surface",
            "explanation": "Provider consumer surface inspected for compatibility and duplicated normative rules; this context does not authorize Provider edits.",
            "path": "src/stateforge_provider",
            "repository_alias": "provider",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 8
          }
        ],
        "depends_on": [
          "P10",
          "P3",
          "P5",
          "P6"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "## Outcome and ownership\n\nComplete Protocol semantics for safe reconnect and reconciliation across discovery/bootstrap, manifest, health, triggers, and admitted operations. See `docs/procedures/disconnection-recovery.md` and the SFP recovery specification.\n\n## Required behavior\n\n- Distinguish transport loss, endpoint-generation replacement, same-installation process restart, and replacement installation. Re-handshake and validate manifest/health before new admission; an old session is not reusable authority.\n- Reuse P3/P5 publication IDs, operation IDs, and cursors where sufficient. Add only genuinely required missing wire messages; do not invent a second reconciliation service merely for symmetry.\n- A live Provider process may continue work during channel loss and replay retained state/results after reconnect. Lost Watch/acknowledgement does not start another execution or logically duplicate a trigger.\n- Define retained, lost/expired, incompatible, and replacement outcomes. A replacement instance cannot claim another instance's executions. Missing previously admitted state is indeterminate, not FAILED and not authorization to retry with a new ID.\n- Stable persisted Provider installation identity does not imply persisted operation/trigger state. Baseline runtime state is in memory; stronger Provider-owned persistence is optional. Document restart limitations and retention boundaries.\n- Specify stale-stream fencing, identity correlation, cursor gaps, backoff/retryability, and safe acknowledgement replay. Unknown outcome remains visible to a later decision-maker; SFP does not choose the business remediation.\n\n- Extend the reusable P10 Protocol CI/CD framework with recovery-owned conformance fixtures and validation scenarios, and register them in the standard pull-request, integration, and release-candidate workflows rather than creating a duplicate top-level pipeline.\n\n## Acceptance evidence\n\nCI/CD evidence must show that the exact built Protocol artifacts contain and pass the recovery procedure's reconnect, replay, stale-session, state-loss, compatibility, and boundary cases.\n\nContract scenarios cover lost admission reply, lost trigger acknowledgement, interrupted Watch, same-process reconnect, changed generation, process restart with lost state, persisted-state recovery where supported, new-instance replacement, stale replies, and invalid/expired cursors. Verify recovery composes with P3/P4/P5 without changing their identity semantics.\n\n## Non-goals\n\nNo runtime reconnect loop, compulsory persistent Provider storage, automatic re-execution after uncertainty, SF-AOP protocol, or Control Plane/operator remediation implementation.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 9,
        "step_id": "P8",
        "title": "[TASK][MVP] Define SFP Disconnection Recovery Contracts",
        "verification_requirements": [
          {
            "explanation": "All Protocol tests, including recovery semantics and contract ownership, pass.",
            "kind": "test",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 0,
            "target": "python -m pytest -q",
            "verification_id": "p8-protocol-tests"
          },
          {
            "explanation": "Generated bindings and packaged contract artifacts match their authoritative sources.",
            "kind": "generated",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 1,
            "target": "python scripts/check_generated.py",
            "verification_id": "p8-generated-freshness"
          },
          {
            "explanation": "Versioned protobuf sources pass the repository's Buf rules.",
            "kind": "lint",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 2,
            "target": "buf lint",
            "verification_id": "p8-buf-lint"
          },
          {
            "explanation": "Recovery coverage proves the shipped artifacts, not only the source checkout.",
            "kind": "integration",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 3,
            "target": "Execute the recovery conformance scenarios from the exact built wheel and sdist through the standard P10 workflows.",
            "verification_id": "p8-artifact-conformance"
          },
          {
            "explanation": "No copied service identity, limit, scalar parser, descriptor rule, or context-independent validator remains unclassified or consumer-owned.",
            "kind": "human",
            "repository_alias": null,
            "required": true,
            "sort_order": 4,
            "target": "Review the final SFP responsibility matrix against Protocol, Agent, and Provider and account for every registered procedure and recovery boundary.",
            "verification_id": "p8-ownership-matrix"
          }
        ]
      },
      {
        "branch_name": "mvp/sfp-contract-verification",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "p9-dpt-skill",
            "explanation": "Cross-repository audit and completion-claim requirements.",
            "path": ".agents/skills/stateforge-dpt-milestone",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "p9-protocol-skill",
            "explanation": "Canonical SFP ownership and contract verification rules.",
            "path": ".claude/skills/stateforge-protocol-development",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "p9-responsibility-boundaries",
            "explanation": "Release-wide responsibility matrix that must match all three implementations.",
            "path": "docs/reference/responsibility-boundaries.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "p9-protobuf-surface",
            "explanation": "Complete authoritative SFP wire-shape surface.",
            "path": "proto/stateforge_protocol/sfp",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "canonical",
            "context_id": "p9-python-contract-surface",
            "explanation": "Complete packaged identities, limits, scalars, descriptor semantics, validators, and shared endpoint inventory.",
            "path": "src/stateforge_protocol/sfp",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "compatibility",
            "context_id": "p9-agent-consumer",
            "explanation": "Complete Agent SFP consumer audited for imports, contextual policy, and duplicate normative rules.",
            "path": "src/stateforge_agent/_sfp",
            "repository_alias": "agent",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 5
          },
          {
            "authority": "compatibility",
            "context_id": "p9-provider-consumer",
            "explanation": "Complete Provider SFP consumer audited for imports, contextual policy, and duplicate normative rules.",
            "path": "src/stateforge_provider",
            "repository_alias": "provider",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 6
          }
        ],
        "depends_on": [
          "P1",
          "P10",
          "P2",
          "P3",
          "P4",
          "P5",
          "P6",
          "P8"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "## Outcome and ownership\n\nVerify that the complete local SFP transport and generic-operation contract package can be consumed independently by Agent and Provider developers. This is Protocol integration/conformance work, not business-operation or runtime implementation.\n\n## Required behavior\n\n- Verify bootstrap, manifest, capability assessment, triggers, generic operation admission, lifecycle/progress/results/cancellation, and reconnect/recovery compose coherently. Identifier ownership, session/generation validation, versioning, error taxonomy, retention, and replay semantics must agree.\n- Prove SFP transports arbitrary declared operations through their own typed payload/result schemas without interpreting application meaning. Backup preparation, restore, disaster recovery, and BackupEngine behavior are not SFP procedures or Protocol-owned schemas.\n- Preserve landed bootstrap and manifest contracts. Keep operations as versioned namespaced strings, retain generic `implements` declarations without assigning Protocol-owned backup/DR meaning, and document only the current active contract.\n- Supply reusable conformance fixtures for ordinary operations, invalid schemas/results, duplicate/conflicting admission, progress/cancellation, trigger replay, channel loss, and state-loss recovery.\n- Check Buf lint, reproducible generation, generated-source freshness and compatibility. Generated modules must never be hand-edited. Ensure required protobuf/schema fixtures, typing markers, and documentation are included in wheel and sdist.\n- Verify clean installation/imports and dependency compatibility for supported Python versions/platforms. Separate build tooling from runtime dependencies and build strict documentation.\n\n- Maintain a machine-checked coverage inventory mapping every SFP procedure to its packaged conformance assets and standard CI entry points; missing procedure coverage is a release-blocking failure.\n\n## Acceptance evidence\n\nCI/CD evidence must prove every planned SFP procedure is represented in the exact wheel and sdist and is executed by the full contract matrix.\n\nAll configured Protocol gates pass, installed-package consumers load every generic SFP service/schema/fixture, and independent Agent/Provider test peers make the same transport, validation, identity, idempotency, and recovery decisions. No fixture requires knowledge of BackupEngine or a predefined backup/DR operation.\n\n## Non-goals\n\nNo Agent/Provider runtime, business-operation catalogue, backup/DR schema, BackupEngine implementation, SF-AOP design, or Control Plane contract.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose. Choose compatible implementation details from the current codebase and document tradeoffs for human review. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step.",
        "sort_order": 10,
        "step_id": "P9",
        "title": "[TASK][MVP] Verify the Complete SFP Contract Surface",
        "verification_requirements": [
          {
            "explanation": "The complete Protocol contract and conformance suite passes.",
            "kind": "test",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 0,
            "target": "python -m pytest -q",
            "verification_id": "p9-protocol-tests"
          },
          {
            "explanation": "Schemas lint and generated artifacts are reproducible and current.",
            "kind": "lint",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 1,
            "target": "buf lint && buf generate && python scripts/check_generated.py",
            "verification_id": "p9-buf"
          },
          {
            "explanation": "Every procedure's authoritative contract and fixtures ship and execute from exact artifacts.",
            "kind": "integration",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 2,
            "target": "Build wheel and sdist, inspect their contents, and run the full installed-package conformance matrix.",
            "verification_id": "p9-package"
          },
          {
            "explanation": "Both consumers reach the same wire decisions by importing Protocol, not by reimplementing it.",
            "kind": "integration",
            "repository_alias": null,
            "required": true,
            "sort_order": 3,
            "target": "Run Agent and Provider consumer suites against the exact built Protocol wheel.",
            "verification_id": "p9-consumer-conformance"
          },
          {
            "explanation": "The release gate fails if any service identity, RPC path, limit, scalar rule, descriptor semantic, context-independent validator, or transport ceiling lacks exactly one authoritative owner.",
            "kind": "human",
            "repository_alias": null,
            "required": true,
            "sort_order": 4,
            "target": "Approve a complete responsibility matrix for every SFP procedure and shared endpoint resource across Protocol, Agent, and Provider.",
            "verification_id": "p9-ownership-closure"
          }
        ]
      },
      {
        "branch_name": "Existing work",
        "context_resources": [],
        "depends_on": [
          "P0"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Publish a ready local endpoint and negotiate one SFP session on the Agent-established channel.",
        "sort_order": 11,
        "step_id": "R0",
        "title": "[TASK][MVP] Implement Provider Discovery and Handshake Foundation",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/provider-manifest-exchange",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "context-bf9f122c-a865-4955-9085-aa4675a9ba40",
            "explanation": "Update docs respectfully to the change.",
            "path": "docs",
            "repository_alias": "provider",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "context-a73b6239-9754-4b58-a839-7938b7279f1c",
            "explanation": "Dependencies probably.",
            "path": "pyproject.toml",
            "repository_alias": "provider",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "context-5cb6e462-b651-4d95-8b99-a298eec596ca",
            "explanation": "Where implementation would live.",
            "path": "src/stateforge_provider",
            "repository_alias": "provider",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "context-a54dff67-e9e1-4a51-b8a0-b354a347d9e0",
            "explanation": "Manifest exchange protocol buffers.",
            "path": "proto/stateforge_protocol/sfp/manifest",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "canonical",
            "context_id": "context-2dab1372-1cc5-4403-a1f5-18e1483d59de",
            "explanation": "Manifest change diagram.",
            "path": "docs/assets/diagrams/provider-manifest-exchange.png",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "canonical",
            "context_id": "context-1cf95e1e-acc4-4335-9b2c-b04c977e82f3",
            "explanation": "Generate protobuf python binding.",
            "path": "src/stateforge_protocol/sfp/manifest",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 5
          },
          {
            "authority": "canonical",
            "context_id": "context-1039e246-ebb8-4829-99fa-c3f8aa7d1997",
            "explanation": "Manifest exchange docs.",
            "path": "docs/procedures/provider-manifest.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 6
          }
        ],
        "depends_on": [
          "P1"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Let Provider authors declare a validated effective manifest containing generic operation identifiers, triggers, runtime requirements, configuration schema, and explicit compliance profiles.",
        "sort_order": 12,
        "step_id": "R1",
        "title": "[TASK][MVP] Implement Provider Manifest Exchange",
        "verification_requirements": [
          {
            "explanation": "Human In The loop involved.",
            "kind": "human",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 0,
            "target": "Review passed?",
            "verification_id": "verify-8a5477ed-8022-42e4-ab75-c16fc079311c"
          }
        ]
      },
      {
        "branch_name": "mvp/provider-health-monitoring",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "context-4be49a9a-b3e2-45e8-b27c-a3e079e8d691",
            "explanation": "Health procedure diagram.",
            "path": "docs/assets/diagrams/health-and-availability-monitoring.png",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "context-84a63d0e-b6b5-4dbb-9d5e-5fedd9a64755",
            "explanation": "Initial description of the health and availability monitoring procedures.",
            "path": "docs/procedures/health.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "context-bb12e6b0-70a3-4d23-a8e5-587814c09880",
            "explanation": "Skills needed to modify this project.",
            "path": ".claude/skills",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "context-def817b4-d231-4b35-bee1-76663537df6b",
            "explanation": "Skill that explains DPT.",
            "path": ".agents/skills/stateforge-dpt-milestone",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "canonical",
            "context_id": "context-6cbec76b-8efe-4a5f-8eb9-33866e019e9e",
            "explanation": "Explanation toward agents before editing this repository.",
            "path": "AGENTS.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 4
          }
        ],
        "depends_on": [
          "P6",
          "R1",
          "R11"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "## Outcome and ownership\n\nExpose standard `grpc.health.v1` on the existing standalone Provider server and connect it to the public Provider lifecycle/health hook. Use standard generated health contracts, not a new StateForge health protobuf.\n\n## Required behavior\n\n- Register the actual negotiated operational service name(s) on the same multiplexed server/channel. Explicitly define startup NOT_SERVING, validated readiness SERVING, failed/degraded readiness, maintenance, and bounded shutdown behavior.\n- Keep author-facing status typed and simple; the runtime adapts it to standard Check/Watch. Health does not become a vendor polling scheduler or expose protobuf construction to authors.\n- Watch emits current status and changes with bounded observers/backpressure; invalid services and stream failures follow standard health semantics. Check is diagnostic, not a replacement for ongoing Watch.\n- Stop new operation eligibility before maintenance/shutdown. A health transition does not itself cancel admitted operations, and SERVING does not override an invalid manifest/session or guarantee target-specific capability.\n- Sanitize unexpected hook failures, prevent stale readiness from surviving a generation change, and clean up watchers/resources owned by this runtime only.\n\n- Extend the reusable R11 Provider scenario catalogue with health-specific installed-runtime coverage using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket; do not substitute a simulated Agent transport.\n\n## Acceptance evidence\n\nCI/CD evidence must include the focused health scenario in pull requests and the unchanged full Provider scenario matrix.\n\nExercise real gRPC Check/Watch on the same endpoint as handshake/manifest, initial and changed status, unknown service, hook failure, slow/disconnected observers, restart, and shutdown. Verify typed author examples and no duplicate server/channel or custom StateForge health contract.\n\n## Non-goals\n\nNo Agent availability coordinator, Control Plane reporting, business-operation cancellation, vendor-specific health logic, or implementation of later admission APIs.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 13,
        "step_id": "R2",
        "title": "[TASK][MVP] Implement Provider Health and Availability Reporting",
        "verification_requirements": [
          {
            "explanation": "Human In The Loop.",
            "kind": "human",
            "repository_alias": "protocol",
            "required": true,
            "sort_order": 0,
            "target": "GitHub review",
            "verification_id": "verify-d56fcae2-d0ce-4be7-a0a5-90ff033bc2ff"
          }
        ]
      },
      {
        "branch_name": "mvp/capability-assessment",
        "context_resources": [],
        "depends_on": [
          "P2",
          "R1",
          "R11",
          "R2"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "## Outcome and ownership\n\nImplement the locked P2 capability-assessment contract behind a typed, overridable Provider capability hook, compatible with R1 manifest declarations and R2 readiness. P2's issued requirements remain unchanged.\n\n## Required behavior\n\n- Validate negotiated session/generation, target kind, requested versioned operation IDs, configuration/execution context, payload limits, and current declarations before invoking author code.\n- Perform only bounded read-only inspection. Return the contract's normalized SUPPORTED, SUPPORTED_WITH_REQUIREMENTS, UNSUPPORTED, or INDETERMINATE findings and correlation identity, with explicit reasons/requirements for each requested operation as the landed contract permits.\n- Preserve the difference between declared support, runtime/target compatibility, temporary unavailability, and proven satisfaction of prerequisites. Unknown requirements or a manifest declaration alone are not evidence of support.\n- Keep capability findings operation-generic: never add or echo backup-preparation result variants, storage-tool choices, or other operation-specific result fields. Profile conformance belongs to the declared versioned operation schemas and later admission/execution paths. Keep target-specific business inspection in author code; the runtime never assigns logical StateForge component IDs.\n- Negative assessment is a valid domain result, not automatically an RPC failure. Invalid protocol input and hook/transport failures follow P2's error mapping; sanitize remote diagnostics and honor finite deadlines/cancellation of the read.\n- Reuse the Provider framework and existing schema/model facilities. Do not independently reinterpret or redesign P2 while implementing its consumer.\n\n- Extend the reusable R11 Provider scenario catalogue with capability-assessment installed-runtime coverage using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket; do not substitute a simulated Agent transport.\n\n## Acceptance evidence\n\nCI/CD evidence must include focused capability success, rejection, malformed-response, deadline, stale-session, and limit scenarios plus the unchanged full Provider matrix.\n\nCover generic and profile-related assessment, all support statuses, conditional/unknown requirements, undeclared IDs/kinds, malformed context, correlation, stale session, hook exception/deadline, absence of operation-specific result fields, and absence of target mutation. Verify public hook documentation and configured gates.\n\n## Non-goals\n\nNo operation dispatch, target mutation, mandatory persistence, Agent/Control Plane mapping, policy evaluation, or universal vendor-version evaluator.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 14,
        "step_id": "R3",
        "title": "[TASK][MVP] Implement Provider Capability Assessment",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/trigger-publication",
        "context_resources": [],
        "depends_on": [
          "P3",
          "R1",
          "R11",
          "R2"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "## Outcome and ownership\n\nImplement P3 Provider publication with a simple typed author-facing trigger API on the existing Provider framework. The runtime owns envelopes, stream adaptation, acknowledgement, and retries.\n\n## Required behavior\n\n- Publish only manifest-declared versioned trigger IDs and schema-valid payloads. Derive authenticated installation/session identity internally. Do not accept a generic target, source, or resource identity; any trigger-specific resource/source information is ordinary schema-validated payload data.\n- Allocate/preserve stable publication identity and canonical semantic content. Keep bounded pending state until accepted/rejected, correlate acknowledgements, handle new/duplicate/rejected dispositions, and surface rejection safely to authors.\n- Lost acknowledgements and transient streams replay the original ID/content with bounded backoff/backpressure. Conflicting content under one ID is never silently accepted. Stop retrying non-retryable rejection as defined by P3.\n- Respect startup/shutdown, generation/session fencing, deadlines and pending-queue limits without blocking unrelated channel services. Document queue-full and disconnected publication behavior.\n- Baseline pending state may be in memory. Provider-controlled persistence is optional; document what a process crash can lose rather than promising durable delivery from stable installation identity alone.\n- Keep generated messages, gRPC streams, canonical envelope construction and secret redaction private. A trigger does not by itself prove a policy ran or a backup completed.\n\n- Extend the reusable R11 Provider scenario catalogue with trigger-publication installed-runtime coverage using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket; do not substitute a simulated Agent transport.\n\n## Acceptance evidence\n\nCI/CD evidence must include focused acknowledgement, replay, duplicate, conflict, backpressure, reconnect, and shutdown scenarios plus the unchanged full Provider matrix.\n\nTest public publication and real stream transport, payload/ID rejection, accepted new/duplicate, lost-ack replay, content conflict, rejection retryability, bounded queue, disconnect/reconnect, optional-state limitations, shutdown, and the absence of generic source/target parameters. No human-facing author example requires protobuf or session/generation management.\n\n## Non-goals\n\nNo generic target/source/resource abstraction, Control Plane connection, policy executor, StateForge binding assignment, mandatory persistent Provider event log, or backup-only trigger taxonomy.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 15,
        "step_id": "R4",
        "title": "[TASK][MVP] Implement Trigger Publication and Acknowledgement",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/operation-admission",
        "context_resources": [],
        "depends_on": [
          "P4",
          "R11",
          "R2",
          "R3"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "## Outcome and ownership\n\nImplement P4 admission and generic typed operation dispatch behind the public Provider framework. Providers can expose arbitrary declared operations; no backup/DR claim is required for ordinary operations.\n\n## Required behavior\n\n- Provide compatible typed request/result models and async `@operation()` registration on Provider subclasses, reusing R1 facilities. Use landed `namespace/name@major` IDs, not legacy unversioned dotted examples; reject duplicate/invalid declarations and align derived schemas with the manifest.\n- Keep installation/session/generation, protobuf adaptation, fingerprints and registry management private. Provide a typed OperationContext carrying operation identity, deadline and approved execution context; extend it for P5 lifecycle in R6.\n- Validate active session, R2 readiness, declared operation/target and input schema before author behavior. Use P4's canonical fingerprint and atomic admission record before dispatch. Matching concurrent retries resolve one execution; changed content conflicts.\n- Return P4's successful dispositions and rejection statuses/reasons. Busy/invalid/deadline-before-admission requests create no accepted record. Terminal IDs are not repurposed; document bounded retention/expiry and lost-state limitations.\n- Default accepted-operation state is in memory; optional stronger persistence remains Provider-controlled. Delivery deduplication does not guarantee the vendor action is idempotent or justify retry after a process lost admitted state.\n- Validate author outputs and sanitize exceptions using the established lifecycle/error boundary; do not opportunistically implement full progress/Watch/cancellation or backup profiles in this step.\n\n- Extend the reusable R11 Provider scenario catalogue with operation-admission installed-runtime coverage using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket; do not substitute a simulated Agent transport.\n\n## Acceptance evidence\n\nCI/CD evidence must include focused admission, idempotency, concurrency, conflict, deadline, schema, and limit scenarios plus the unchanged full Provider matrix.\n\nCover a typed non-backup operation, schema derivation, duplicate registrations, invalid requests, readiness rejection, concurrency, identical lost-response retry, changed content, terminal replay/ID immutability, deadlines, safe exceptions, and expiry. Prove author examples require no gRPC/protobuf plumbing and dispatch occurs once per accepted identity.\n\n## Non-goals\n\nNo arbitrary shell-command API, vendor integration, mandatory persistent operation database, backup/DR requirement for generic operations, SF-AOP, or policy-run scheduling.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 16,
        "step_id": "R5",
        "title": "[TASK][MVP] Implement Operation Admission and Idempotency",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/operation-lifecycle",
        "context_resources": [],
        "depends_on": [
          "P5",
          "R11",
          "R5"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "## Outcome and ownership\n\nImplement P5 generic operation progress, results, and cancellation behind Provider/OperationContext, extending R5's accepted registry rather than adding a second execution ledger.\n\n## Required behavior\n\n- Enforce the contract's state transitions and one immutable terminal result. Validate typed result schemas; translate expected/unexpected author exceptions into sanitized structured errors with relevant side-effect/cleanup evidence.\n- Offer author progress reporting and cooperative cancellation state/checkpoints without exposing gRPC. Keep per-operation sequence monotonic and replay current/latest retained state on Watch attachment; Watch never dispatches an operation.\n- Bound progress retention and slow-watcher queues, coalesce only permitted progress, and preserve terminal replay while records are retained. Isolate concurrent operations/observers on the shared server.\n- Cancellation request and execution stopped are distinct. Handle unsupported and already-terminal outcomes; first terminal outcome wins races. Set CANCELLED only when actual author execution stopped according to the contract.\n- Watch cancellation, client deadline, transport loss and health changes do not implicitly stop business execution. Never kill the whole Provider process or unrelated tasks to cancel one operation.\n- Shutdown stops new admission, performs bounded graceful handling, and reports unresolved work honestly. Preserve R5 in-memory baseline and optional Provider persistence; no crash-proof result promise without evidence.\n\n- Extend the reusable R11 Provider scenario catalogue with operation-lifecycle installed-runtime coverage using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket; do not substitute a simulated Agent transport.\n\n## Acceptance evidence\n\nCI/CD evidence must include focused progress, replay, cancellation, terminal-race, invalid-result, interruption, and limit scenarios plus the unchanged full Provider matrix.\n\nExercise progress/terminal replay, late/slow/disconnected watchers, sequence/cursor behavior, invalid author results, sanitized failure, parallel operations, cancellation completion/races, unsupported/already-terminal cancellation, Watch-only cancellation, shutdown, and no redispatch. Update typed author examples and configured checks.\n\n## Non-goals\n\nNo unbounded history service, process-level force kill, invented operation states, backup-specific lifecycle implementation, or automatic remediation after unknown side effects.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 17,
        "step_id": "R6",
        "title": "[TASK][MVP] Implement Operation Progress Results and Cancellation",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/provider-ci-automation",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "r11-agent-instructions",
            "explanation": "Preserve the authoring vision, runtime abstraction, and human delivery authority.",
            "path": "AGENTS.md",
            "repository_alias": "provider",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "r11-package-contract",
            "explanation": "Defines the package, Python support, dependencies, coverage, and gates.",
            "path": "pyproject.toml",
            "repository_alias": "provider",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "r11-public-provider-api",
            "explanation": "Fixtures and scenarios must use the public authoring/lifecycle surface.",
            "path": "src/stateforge_provider/provider.py",
            "repository_alias": "provider",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "r11-runtime",
            "explanation": "Exercise endpoint ownership, startup, sessions, shutdown, and cleanup without duplicating runtime logic.",
            "path": "src/stateforge_provider/_runtime",
            "repository_alias": "provider",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "canonical",
            "context_id": "r11-services",
            "explanation": "Verify implemented Bootstrap and Manifest services through public wire behavior.",
            "path": "src/stateforge_provider/_services",
            "repository_alias": "provider",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "canonical",
            "context_id": "r11-tests",
            "explanation": "Existing tests remain authoritative and stay in the aggregate gate.",
            "path": "tests",
            "repository_alias": "provider",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 5
          },
          {
            "authority": "canonical",
            "context_id": "r11-docs",
            "explanation": "Architecture and authoring docs define boundaries the fixtures must respect.",
            "path": "docs",
            "repository_alias": "provider",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 6
          },
          {
            "authority": "canonical",
            "context_id": "r11-readme",
            "explanation": "Document local parity, inputs, scenario composition, and artifact reuse.",
            "path": "README.md",
            "repository_alias": "provider",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 7
          }
        ],
        "depends_on": [
          "R1"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "## Outcome and ownership\n\nCreate a reusable GitHub Actions ecosystem for building and validating the Provider Implementation package and its installed runtime. Package construction, dependency selection, public Provider fixtures, runtime lifecycle, SFP assertions, scenarios, and evidence collection are written once and composed by PR, integration, release-candidate, and future publication workflows. Test the public authoring surface and installed package; do not create a second runtime or execute from a source checkout.\n\n## Required behavior\n\n- Build wheel and sdist once through a documented local command using canonical package metadata; record checksums and artifact/dependency provenance.\n- Organize focused composite actions under `.github/actions/` for package build, installed-package checks, Provider fixture creation, runtime start/stop, Bootstrap assertion, Manifest assertion, and evidence collection. Scenarios compose actions rather than growing one large action.\n- Provide reusable `workflow_call` workflows for artifact build, installed-package checks, runtime scenarios, and an aggregate gate. Thin PR/integration and manual release-candidate callers copy no environment or test logic.\n- Accept `protocol-ref`, defaulting to `mvp/implementation` while allowing an explicit ref or SHA. Record the resolved Protocol commit and artifact hash.\n- Install exact Provider and Protocol artifacts in clean environments outside both checkouts and without repository `PYTHONPATH`; prove package identity, import location, typed public API, descriptor/socket behavior, Bootstrap, Manifest, and clean shutdown.\n- Supply small declarative dummy Providers through the public API. Cover normal exchange/shutdown, concurrent distinct instances, same-instance replacement/generation, invalid peers, abrupt failure, restart, and uninstall/reinstall. Faults and evidence must be deterministic and bounded.\n- Separate platform-independent package/import checks from supported runtime checks. Do not imply Windows runtime support where Unix-domain sockets are required.\n- Pin external actions to immutable SHAs; keep permissions read-only, credentials absent, jobs bounded, caches dependency-keyed, and retention explicit.\n- Prefer action composition and existing commands. Add shell or Python only for reusable logic that cannot be expressed safely elsewhere; never duplicate runtime behavior in the harness.\n\n## Acceptance evidence\n\nValidate action/workflow metadata; build wheel and sdist once; verify hashes/provenance; install exact artifacts outside the checkout; prove installed import origins and public authoring API; exercise valid Bootstrap/Manifest, multiple Providers, replacement, invalid peers, crash, restart, cleanup, uninstall, and reinstall; retain failure evidence. Pass Ruff, formatting, strict mypy, pytest/coverage, package build, installed-package checks, runtime scenario tiers, and strict docs.\n\n## Non-goals\n\nNo production Provider, new SFP semantics, Agent features, Control Plane integration, operation/trigger behavior, publication/signing, OS service package, cloud infrastructure, or organization-wide workflow repository.\n\n## Compatibility, discretion, and delivery\n\nPreserve the public Provider framework, typed models, decorators, lifecycle hooks, internal SFP abstraction, landed Bootstrap/Manifest behavior, supported Python versions, and human Issue/PR/review/merge authority. Reusable workflows own job topology, composite actions own repeated runner steps, and the installed package plus public API remain the system under test.",
        "sort_order": 18,
        "step_id": "R11",
        "title": "[TASK][MVP] Build Reusable Provider Package and Runtime CI/CD Pipelines",
        "verification_requirements": [
          {
            "explanation": "Validate metadata, workflow syntax, immutable pins, permissions, and shell syntax.",
            "kind": "lint",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 0,
            "target": ".github/actions and .github/workflows",
            "verification_id": "r11-actions"
          },
          {
            "explanation": "Build wheel and sdist once and record artifact/dependency provenance.",
            "kind": "command",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 1,
            "target": "python -m build",
            "verification_id": "r11-build"
          },
          {
            "explanation": "Install exact Provider/Protocol artifacts outside checkouts and verify metadata, import origin, public API, uninstall, and reinstall.",
            "kind": "test",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 2,
            "target": "clean installed-artifact matrix",
            "verification_id": "r11-installed"
          },
          {
            "explanation": "Exercise startup, Bootstrap, Manifest, multi-Provider, replacement, invalid peer, crash, restart, shutdown, cleanup, and evidence.",
            "kind": "test",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 3,
            "target": "composable installed-runtime scenarios",
            "verification_id": "r11-runtime-scenarios"
          },
          {
            "explanation": "Run the complete Provider suite with its coverage contract.",
            "kind": "test",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 4,
            "target": "pytest with configured coverage threshold",
            "verification_id": "r11-tests"
          },
          {
            "explanation": "Preserve repository quality and docs gates.",
            "kind": "command",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 5,
            "target": "ruff check, ruff format \u002d\u002dcheck, mypy, mkdocs build \u002d\u002dstrict",
            "verification_id": "r11-repository-gates"
          },
          {
            "explanation": "Human confirms public APIs, exact artifact reuse, and no duplicated runtime.",
            "kind": "human",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 6,
            "target": "GitHub pull request review",
            "verification_id": "r11-human-review"
          }
        ]
      },
      {
        "branch_name": "mvp/sfp-reconciliation",
        "context_resources": [],
        "depends_on": [
          "P8",
          "R11",
          "R4",
          "R6"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "## Outcome and ownership\n\nImplement P8 Provider reconnect/state-reconciliation behavior by composing existing runtime identity, manifest, health, trigger and operation facilities.\n\n## Required behavior\n\n- Separate channel loss from process death: accepted work may continue while the server process survives. Rebind new channels to validated handshake/session/generation before serving operational state.\n- Retain current operations/terminal results and pending trigger IDs/content for their documented in-process retention; replay existing state/results/acknowledgement work without redispatching author operations.\n- Keep installation identity/generation storage independent from execution persistence. Baseline process restart may lose operation/trigger state; optional Provider persistence may recover only verifiable records.\n- Return the contract's explicit indeterminate/lost/expired outcome for unresolved admitted identities. Never manufacture FAILED/SUCCEEDED, silently create a new record for reconciliation, or claim executions belonging to a replaced instance.\n- Fence stale sessions/watchers/acknowledgements, respect cursor gaps and backpressure, and coordinate bounded shutdown/restart. Remove only descriptor/socket/resources owned by the current generation.\n- Document exactly what survives transport interruption versus process restart and how callers detect limitations. Business/operator remediation belongs above SFP, not in the generic runtime.\n\n- Extend the reusable R11 Provider scenario catalogue with deterministic disconnection and recovery scenarios using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket.\n\n## Acceptance evidence\n\nCI/CD evidence must cover connection loss, generation replacement, Provider restart with retained or lost state, stale responses, expiry, and indeterminate outcomes without redispatch.\n\nCross-process scenarios cover lost admission reply, ongoing execution during transport loss, terminal replay, pending-trigger replay, generation replacement, stable-installation restart with state loss, new-instance replacement, stale stream responses, retention expiry, and supported optional persistence. Prove no author redispatch on reconciliation.\n\n## Non-goals\n\nNo mandatory persistent Provider registry, Agent reconnect manager, Control Plane remediation, automatic re-execution, or broader process-supervision redesign.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 20,
        "step_id": "R9",
        "title": "[TASK][MVP] Complete Provider Disconnection and Recovery",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/provider-runtime-verification",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "r10-dpt-skill",
            "explanation": "Cross-repository audit and completion-claim requirements.",
            "path": ".agents/skills/stateforge-dpt-milestone",
            "repository_alias": "provider",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "r10-protocol-skill",
            "explanation": "Provider consumer ownership and runtime boundary rules.",
            "path": ".claude/skills/stateforge-protocol-development",
            "repository_alias": "provider",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "r10-authoring-vision",
            "explanation": "Public Provider framework contract that internal SFP plumbing must preserve.",
            "path": ".claude/PROVIDER_AUTHORING_VISION.md",
            "repository_alias": "provider",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "r10-responsibility-boundaries",
            "explanation": "Canonical split between Protocol rules and Provider-local policy.",
            "path": "docs/reference/responsibility-boundaries.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "compatibility",
            "context_id": "r10-protocol-contracts",
            "explanation": "Every authoritative SFP contract the Provider must consume.",
            "path": "src/stateforge_protocol/sfp",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "canonical",
            "context_id": "r10-provider-runtime",
            "explanation": "Complete Provider runtime and author-facing surface.",
            "path": "src/stateforge_provider",
            "repository_alias": "provider",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 5
          },
          {
            "authority": "reference",
            "context_id": "r10-agent-peer",
            "explanation": "Independent Agent peer surface used to confirm interoperability and ownership.",
            "path": "src/stateforge_agent/_sfp",
            "repository_alias": "agent",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 6
          },
          {
            "authority": "canonical",
            "context_id": "r10-provider-tests",
            "explanation": "Focused, ownership, package, lifecycle, and real-process evidence.",
            "path": "tests",
            "repository_alias": "provider",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 7
          }
        ],
        "depends_on": [
          "R11",
          "R2",
          "R3",
          "R4",
          "R5",
          "R6",
          "R9"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "## Outcome and ownership\n\nVerify the generic Provider framework/runtime against an independent Agent-side SFP test peer using installed contracts. The real Agent-daemon integration gate is A12.\n\n## Required behavior\n\n- Run the reference Provider in a separate process through public `Provider.run()` and `serve()` paths. Exercise discovery/handshake, manifest, standard health, read-only capability assessment, triggers, arbitrary typed operation admission, progress/results/cancellation, and reconnect.\n- Prove Provider authors can expose unrelated namespaced operations with their own request/result models. The runtime must not recognize backup, restore, disaster recovery, BackupEngine, or other business-operation categories.\n- Exercise concurrent streams/operations and the safety matrix: lost replies/acknowledgements, duplicate/conflicting IDs, invalid author results, cancellation races, slow observers, deadlines, stale generations, restart, and indeterminate state. No scenario may silently redispatch unresolved work.\n- Verify authored models/decorators, hook lifecycle, schema derivation, generic `implements` declaration transport, and sanitized exceptions. Normal public examples must not require servicers, protobufs, descriptors, instance storage, or generation allocation.\n- Build wheel/sdist, verify packaged typing/resources and clean installed startup, and pass Ruff, strict mypy, pytest, package, and strict documentation gates. Use reusable Protocol conformance fixtures where available.\n\n- Maintain a machine-checked coverage inventory mapping every implemented Provider SFP surface to its focused R11 scenario and full installed-runtime matrix; missing coverage is a release-blocking failure.\n\n## Acceptance evidence\n\nCI/CD evidence must prove the exact Protocol wheel, Provider wheel, and Agent RPM pass the complete Linux/Unix-socket Provider matrix without replacing real peers with transport mocks.\n\nAutomated bounded subprocess coverage and a documented generic SFP coverage matrix. Include multiple unrelated operation schemas and prove the Provider runtime dispatches them without operation-specific branches. Report actual supported operating-system/runtime limits.\n\n## Non-goals\n\nNo production vendor Provider, Agent daemon, Agent workspace, BackupEngine, backup/DR workflow, SF-AOP/Control Plane, or unreviewed public API redesign.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose. Choose compatible implementation details from the current codebase and document tradeoffs for human review. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step.",
        "sort_order": 21,
        "step_id": "R10",
        "title": "[TASK][MVP] Verify the Complete Provider Runtime",
        "verification_requirements": [
          {
            "explanation": "The complete Provider suite passes.",
            "kind": "test",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 0,
            "target": "python -m pytest -q",
            "verification_id": "r10-provider-tests"
          },
          {
            "explanation": "Formatting, linting, typing, and strict documentation pass.",
            "kind": "command",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 1,
            "target": "python -m ruff format \u002d\u002dcheck . && python -m ruff check . && python -m mypy src && python -m mkdocs build \u002d\u002dstrict",
            "verification_id": "r10-provider-quality"
          },
          {
            "explanation": "The shipped Provider behaves correctly with real independent artifacts.",
            "kind": "integration",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 2,
            "target": "Build and clean-install the Provider wheel and sdist, then execute the full R11 installed-runtime matrix with the exact Protocol wheel and Agent RPM.",
            "verification_id": "r10-package"
          },
          {
            "explanation": "Context-independent validation delegates to Protocol while only runtime-state policy remains in Provider.",
            "kind": "test",
            "repository_alias": "provider",
            "required": true,
            "sort_order": 3,
            "target": "Run Provider ownership/delegation tests for every registered SFP procedure.",
            "verification_id": "r10-ownership-tests"
          },
          {
            "explanation": "No copied normative contract or unclassified Provider rule remains before runtime completion is claimed.",
            "kind": "human",
            "repository_alias": null,
            "required": true,
            "sort_order": 4,
            "target": "Review the Provider row of the complete SFP responsibility matrix against Protocol and Agent.",
            "verification_id": "r10-ownership-closure"
          }
        ]
      },
      {
        "branch_name": "Existing work",
        "context_resources": [],
        "depends_on": [
          "P0",
          "R0"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "Procedures 1 and 2, daemon lifecycle, channel reuse, and reconnection foundation.",
        "sort_order": 22,
        "step_id": "A0",
        "title": "[TASK][MVP] Implement SFP Discovery and Handshake Foundation",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/provider-manifest-exchange",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "context-5583dd08-aa31-42d1-a092-d91ae466ade8",
            "explanation": "Protocol description",
            "path": "proto/stateforge_protocol/sfp/manifest/v1/manifest.proto",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "context-43ee22b2-5164-4488-9034-dd0260894422",
            "explanation": "Provider implementation ",
            "path": "src/stateforge_provider/_services/manifest",
            "repository_alias": "provider",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "context-dfe9cef5-5e3f-43ad-8878-3dcc443de1f4",
            "explanation": "Skills to edit this repo",
            "path": ".claude",
            "repository_alias": "agent",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "context-51c98175-9c2d-4e6f-b151-4d1904f3a31d",
            "explanation": "Skills to edit this repo",
            "path": ".agents",
            "repository_alias": "agent",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "canonical",
            "context_id": "context-75ebaead-6ef9-44ae-be7b-a612317c74ce",
            "explanation": "Agent instructions.",
            "path": "AGENTS.md",
            "repository_alias": "agent",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "canonical",
            "context_id": "context-4d3d6ac6-08b5-4350-92c4-28444dd4e749",
            "explanation": "Manifest exchange protocol description",
            "path": "docs/procedures/provider-manifest.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 5
          },
          {
            "authority": "canonical",
            "context_id": "context-b3527042-a290-4af4-9821-17c3855720d1",
            "explanation": "Manifest exchange diagram",
            "path": "docs/assets/diagrams/provider-manifest-exchange.png",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 6
          }
        ],
        "depends_on": [
          "P1",
          "R1"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nIntegrate the landed P1/R1 manifest exchange into the Agent's existing session manager/channel. See the Protocol manifest procedure and checked-in schema/revision conformance vector.\n\n## Required behavior\n\n- Retrieve only after successful handshake with expected installation/generation, finite deadlines, bounded read retry and an explicit supported-schema offer. Accept only an offered/understood version and a complete atomic response.\n- Enforce current P1 ProtoJSON/schema rules, embedded local-reference validation, size/nesting bounds and safe secret handling. Preserve versioned string IDs, target kinds, role claims, requirements and explicit platform pairs.\n- Compute the exact schema-1 revision preimage `{manifest, manifestSchemaVersion, providerInstanceId}` using RFC 8785 with ProtoJSON defaults emitted. Exclude generation/revision, not installation identity; do not substitute deterministic protobuf bytes or older DOCX hashing rules.\n- Cache only validated declarations under installation/SFP version/schema/revision. Reuse an unchanged declaration without merging unvalidated fields, but always check current generation/session. A digest is a change detector, not authentication.\n- Invalid/incompatible manifest blocks operational use independently of healthy transport. Replace valid changed declarations atomically and invalidate dependent local decisions; stale responses cannot activate a superseded session.\n- Transport/session connection state is not full operational availability. Compose with the upcoming A2 health gate rather than treating bootstrap success alone as sufficient. Preserve existing connection replacement behavior.\n\n## Acceptance evidence\n\nTest a real manifest peer, conformance hash, unchanged cache reuse, changed/new-installation revision, complete-response validation, bad header/digest/schema/reference, offered-version mismatch, limits/secrets, stale generation, transport retry and invalid-manifest gating. Ensure no extra channel or vendor-specific interpretation.\n\n## Non-goals\n\nNo modification of locked P1/R1, new schema-1 fields, health implementation, capability/admission dispatch, mandatory inventory redesign, SF-AOP or Control Plane reporting.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 23,
        "step_id": "A1",
        "title": "[TASK][MVP] Integrate Provider Manifest Exchange",
        "verification_requirements": [
          {
            "explanation": "Human In The Loop",
            "kind": "human",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 0,
            "target": "GitHub Review",
            "verification_id": "verify-2a9b7867-6697-4ba1-85b5-700698a5d04c"
          }
        ]
      },
      {
        "branch_name": "mvp/provider-health-monitoring",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "a2-dpt-skill",
            "explanation": "Milestone workflow, cross-repository blast-radius audit, and ownership closure gate.",
            "path": ".agents/skills/stateforge-dpt-milestone",
            "repository_alias": "agent",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "a2-protocol-skill",
            "explanation": "SFP consumer ownership and runtime integration rules.",
            "path": ".claude/skills/stateforge-protocol-development",
            "repository_alias": "agent",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "a2-health-procedure",
            "explanation": "Canonical standard Health and Agent eligibility semantics.",
            "path": "docs/procedures/health.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "a2-responsibility-boundaries",
            "explanation": "Single-owner boundary between versioned Protocol rules and Agent-local state or policy.",
            "path": "docs/reference/responsibility-boundaries.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "canonical",
            "context_id": "a2-health-contract",
            "explanation": "Canonical service identity, monitored key, bounds, and status vocabulary consumed by the Agent.",
            "path": "src/stateforge_protocol/sfp/health_contract.py",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_understand",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "reference",
            "context_id": "a2-provider-health",
            "explanation": "Provider-side standard Health behavior used by the real integration peer; this context does not authorize Provider edits.",
            "path": "src/stateforge_provider/_services/health",
            "repository_alias": "provider",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 5
          },
          {
            "authority": "canonical",
            "context_id": "a2-agent-sfp",
            "explanation": "Agent SFP client, session fencing, and availability coordination surface.",
            "path": "src/stateforge_agent/_sfp",
            "repository_alias": "agent",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 6
          },
          {
            "authority": "canonical",
            "context_id": "a2-agent-tests",
            "explanation": "Behavioral, ownership, and real-process integration evidence.",
            "path": "tests",
            "repository_alias": "agent",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 7
          }
        ],
        "depends_on": [
          "A1",
          "A13",
          "P6",
          "R2"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nWatch standard `grpc.health.v1` on the current Agent-established Provider channel and maintain coherent local operational eligibility with A1's manifest acceptance.\n\n## Required behavior\n\n- Watch the proper versioned operational service on the existing channel; Check is diagnostic. Initial/unknown/NOT_SERVING states block new operation admission.\n- Availability requires current transport, validated handshake/session/generation, compatible valid manifest, and SERVING health. Keep connection state and eligibility distinguishable using existing state boundaries, not parallel unsynchronized ledgers.\n- On Watch end/failure, mark health unknown/unavailable and stop new admission while reconnect/Watch retry is bounded. Resume only after current-session prerequisites are valid again.\n- Fence stale Watch updates after generation replacement, manifest rejection or shutdown. Changes affect new-work eligibility, not the truth of already admitted operations or their terminal results.\n- Expose local status/reasons for diagnostics and later internal consumers without inventing Control Plane reporting. Do not embed vendor-specific health probes.\n\n- Extend the reusable A13 installed-Agent scenario catalogue with health and eligibility coverage using the exact Agent RPM, Protocol wheel, and Provider wheel in separate real processes over the Unix socket.\n\n## Acceptance evidence\n\nCI/CD evidence must include focused health/eligibility scenarios in pull requests and the unchanged full installed-Agent matrix.\n\nExercise initial replay, SERVING/NOT_SERVING, unknown service, Watch loss/recovery, invalid manifest despite SERVING, generation replacement/stale update, concurrent channel streams, and shutdown. Verify readiness transitions are coherent and admitted work is not automatically cancelled by health loss.\n\n## Non-goals\n\nNo custom health protobuf, second channel, remote Control Plane status, business-operation retry/cancellation, or wholesale replacement of landed session-management APIs.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 24,
        "step_id": "A2",
        "title": "[TASK][MVP] Integrate Provider Health and Availability Monitoring",
        "verification_requirements": [
          {
            "explanation": "Agent health, eligibility, session-fencing, recovery, and ownership tests pass.",
            "kind": "test",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 0,
            "target": "python -m pytest -q",
            "verification_id": "a2-agent-tests"
          },
          {
            "explanation": "The Agent integration remains strictly typed.",
            "kind": "typecheck",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 1,
            "target": "python -m mypy src",
            "verification_id": "a2-agent-typecheck"
          },
          {
            "explanation": "The Agent source and tests pass formatting and lint gates.",
            "kind": "lint",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 2,
            "target": "python -m ruff format \u002d\u002dcheck . && python -m ruff check .",
            "verification_id": "a2-agent-lint"
          },
          {
            "explanation": "Evidence covers startup, Watch, health loss and recovery, stale-session fencing, invalid manifest, shutdown, and admitted-work preservation.",
            "kind": "integration",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 3,
            "target": "Run the A13 installed-Agent Standard Health scenarios with the exact Agent RPM, Protocol wheel, and Provider wheel in separate processes over the Unix socket.",
            "verification_id": "a2-installed-integration"
          },
          {
            "explanation": "Agent contains no copied canonical service names, wire limits, status vocabulary, scalar rules, or context-independent validators; only availability and retry policy remain local.",
            "kind": "human",
            "repository_alias": null,
            "required": true,
            "sort_order": 4,
            "target": "Review the Health responsibility matrix and consumer imports across Protocol, Agent, and Provider.",
            "verification_id": "a2-ownership-audit"
          }
        ]
      },
      {
        "branch_name": "mvp/capability-assessment",
        "context_resources": [],
        "depends_on": [
          "A1",
          "A13",
          "A2",
          "P2",
          "R3"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nConsume locked P2/R3 capability assessment using only normalized SFP data, A1 declarations and A2 current eligibility. Preserve P2's issued contract/requirements.\n\n## Required behavior\n\n- Validate current session/generation, declared versioned operation/target kind and bounded request/context before a finite read-only RPC. Reject unsupported declarations locally without assuming vendor knowledge.\n- Normalize/correlate the contract's per-operation support, requirements, reasons and assessment identity. Preserve SUPPORTED_WITH_REQUIREMENTS, UNSUPPORTED and INDETERMINATE distinctions; negative support is a domain finding, not successful eligibility.\n- A manifest advertises potential support, not current target compatibility or satisfied runtime prerequisites. Unknown requirements remain unresolved; do not infer Backup/DR compliance from operation names, capability findings, or operation-specific result shapes.\n- Any reusable assessment is bound to the relevant target/context and active declaration/session; invalidate stale decisions when identity/generation/manifest changes. Read-only retry may inspect a newer state and does not authorize business execution.\n- Surface temporary unavailability, malformed responses, deadline/transport errors and sanitized reasons distinctly. Keep a clean internal boundary for later authorized dispatch, not a policy interpreter.\n\n- Extend the reusable A13 installed-Agent scenario catalogue with capability-assessment coverage using the exact Agent RPM, Protocol wheel, and Provider wheel in separate real processes over the Unix socket.\n\n## Acceptance evidence\n\nCI/CD evidence must include focused capability normalization, rejection, timeout, stale-session, malformed-response, and limit scenarios plus the unchanged full installed-Agent matrix.\n\nCover generic non-backup and profile-related assessment, all support findings, unmet/unknown prerequisites, invalid/undeclared IDs/kinds, malformed/correlation-mismatched reply, readiness gate, stale cache/context, changed generation/manifest and read-only retry. Verify no target mutation or Provider/vendor imports.\n\n## Non-goals\n\nNo P2 redesign, operation dispatch, StateForge component assignment, policy selection, Control Plane connection or universal vendor requirement evaluator.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 25,
        "step_id": "A3",
        "title": "[TASK][MVP] Integrate Provider Capability Assessment",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/trigger-publication",
        "context_resources": [],
        "depends_on": [
          "A1",
          "A13",
          "A2",
          "P3",
          "R4"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nReceive P3/R4 Provider triggers, durably accept delivery responsibility, deduplicate, and acknowledge on the existing SFP stream. Keep an internal forwarding boundary for the later SF-AOP phase.\n\n## Required behavior\n\n- Validate the authenticated Provider/session/generation, declared versioned trigger, schema-bound payload, stable publication ID, canonical content equality, and limits. SFP has no generic target/source/resource identity; any trigger-specific resource/source identity remains payload data and is not interpreted as a StateForge project/component assignment.\n- Commit an accepted event and Agent-owned responsibility state durably before ACCEPTED_NEW. A matching replay returns ACCEPTED_DUPLICATE without duplicate logical delivery; same ID/different semantic content rejects as a conflict.\n- Acknowledgement loss and Agent restart must recover the accepted event/responsibility without forcing a new ID or dropping it silently. A local durable acceptance is not proof that the Control Plane processed it, and downstream handoff is not part of the P3 wire acknowledgement.\n- Retain a bounded, recoverable pending-forward boundary with explicit queue-full/backpressure, rejection/retryability and retention behavior. Until SF-AOP exists, retain accepted events rather than pretending remote forwarding succeeded.\n- Fence stale streams/acks and handle reconnect/shutdown without acknowledging uncommitted work. Keep persistence implementation aligned with the current Agent; no prescribed database engine or new transport architecture.\n- This Provider-originated SFP route remains distinct from any legacy application/developer local-trigger interface; avoid conflating their identifiers or permissions.\n\n- Extend the reusable A13 installed-Agent scenario catalogue with trigger-publication coverage using the exact Agent RPM, Protocol wheel, and Provider wheel in separate real processes over the Unix socket.\n\n## Acceptance evidence\n\nCI/CD evidence must include focused responsibility-transfer, acknowledgement-loss, replay, duplicate, conflict, backpressure, and reconnect scenarios plus the unchanged full installed-Agent matrix.\n\nTest valid/invalid publication, commit-before-ack, crash before commit/after commit-before-ack, lost acknowledgement, durable restart, matching duplicate, conflicting content, queue pressure, reconnect, stale generation, absent downstream transport, and the absence of generic source/target handling. Prove one retained logical event and honest forwarding status.\n\n## Non-goals\n\nNo generic target/source/resource abstraction, SF-AOP wire protocol, Control Plane policy evaluation/component mapping, legacy Local API redesign, or exactly-once policy execution claim.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 26,
        "step_id": "A4",
        "title": "[TASK][MVP] Integrate Trigger Publication and Acknowledgement",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/operation-admission",
        "context_resources": [],
        "depends_on": [
          "A13",
          "A2",
          "A3",
          "P4",
          "R5"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nSubmit immutable P4/R5 generic operations behind the Agent's local coordination boundary using active declarations, A2 readiness and A3 findings. Do not select policy business actions here.\n\n## Required behavior\n\n- Allocate an operation ID before contact; keep the versioned identifier, target, schema-valid payload, deadline and authorized execution context immutable for that attempt. Track attempted/accepted/rejected/unresolved state using current Agent persistence patterns where recovery requires it.\n- Validate manifest declaration and relevant requirements/explicit profiles, current session/generation and readiness before submission. An arbitrary operation remains usable without Backup/DR compliance; an operation identifier is not an arbitrary shell command.\n- Handle ACCEPTED_NEW and RESOLVED_EXISTING, terminal resolution and structured rejection exactly as P4. Rejection does not create a successful execution; busy retry guidance does not authorize changing the request under the same ID.\n- A lost response uses the same semantic request/ID to resolve retained Provider state. Do not create a fresh ID because transport failed; retain uncertainty when admission/external effects cannot be established.\n- Keep delivery deduplication separate from vendor-action idempotency. Document retention/expiry and safe-retry boundaries; unresolved admitted work cannot be automatically repeated after Provider state loss.\n- Fence stale replies/session replacement and prevent concurrent local submissions from becoming duplicate attempts. Keep an internal authority/context boundary ready for future SF-AOP commands without designing that protocol.\n\n- Extend the reusable A13 installed-Agent scenario catalogue with operation-admission coverage using the exact Agent RPM, Protocol wheel, and Provider wheel in separate real processes over the Unix socket.\n\n## Acceptance evidence\n\nCI/CD evidence must include focused admission, idempotency, concurrency, conflict, deadline, schema, and limit scenarios plus the unchanged full installed-Agent matrix.\n\nTest a generic non-backup invocation, invalid/undeclared input, readiness/requirement rejection, successful new/replayed/terminal admission, changed-request conflict, lost-response resolution, concurrent submission, deadline-before-admission, stale generation and retention/state-loss uncertainty. Prove no new execution identity is silently substituted.\n\n## Non-goals\n\nNo policy engine, vendor code, automatic remediation/new attempt, SF-AOP schema, full lifecycle Watch implementation or BackupEngine invocation.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 27,
        "step_id": "A5",
        "title": "[TASK][MVP] Integrate Operation Admission and Idempotency",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/operation-lifecycle",
        "context_resources": [],
        "depends_on": [
          "A13",
          "A5",
          "P5",
          "R6"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nObserve P5/R6 admitted operations, normalize progress/results, and request race-safe operation-scoped cancellation without redispatch.\n\n## Required behavior\n\n- Attach Watch only to known admitted identities; consume current-state/latest-progress replay, monotonic sequences and contract cursor/gap rules. Bound local buffering and fence stale responses from replaced sessions.\n- Validate typed terminal results against pinned declaration/profile context and accept one immutable terminal outcome. Preserve structured failure/partial-side-effect/cleanup evidence and sanitized diagnostics.\n- Request cancellation using the contract, distinguishing accepted/requested, unsupported and already-terminal. Record CANCELLED only after confirmed execution stopped; a successful request or RPC deadline is not confirmation.\n- Completion/cancellation races resolve to the first valid terminal outcome. Cancelling an observer, disconnecting, health loss or timeout does not fabricate FAILED/CANCELLED or stop unrelated work on the channel.\n- Persist/retain the evidence needed to reconcile outstanding attempts using current Agent facilities. Resume observation after interruption without resubmitting business work; P8/A11 provide complete state-loss reconciliation later.\n- Expose normalized local operation status through a clean coordination boundary, not direct vendor hooks or invented Control Plane reporting.\n\n- Extend the reusable A13 installed-Agent scenario catalogue with operation-lifecycle coverage using the exact Agent RPM, Protocol wheel, and Provider wheel in separate real processes over the Unix socket.\n\n## Acceptance evidence\n\nCI/CD evidence must include focused progress, replay, cancellation, terminal-race, interruption, restart-of-observation, and no-redispatch scenarios plus the unchanged full installed-Agent matrix.\n\nTest initial/late/terminal replay, progress coalescing/gaps, slow observer, invalid result/correlation, terminal immutability, cancellation races, unsupported/already-terminal cases, interrupted Watch, stale session, partial effects and Agent restart of observation. Prove Watch and cancellation never cause a second dispatch.\n\n## Non-goals\n\nNo unlimited event-history system, process-wide cancellation, guessed rollback, generic auto-retry of side effects, policy executor or SF-AOP transport.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 28,
        "step_id": "A6",
        "title": "[TASK][MVP] Integrate Operation Progress Results and Cancellation",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/backup-workspaces",
        "context_resources": [],
        "depends_on": [
          "A13",
          "A6"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nImplement protected Agent-owned workspaces used as BackupEngine sources and restore destinations. Workspaces are Agent tooling, not SFP resources or Provider-owned storage.\n\n## Required behavior\n\n- Allocate scoped source/restore workspace identities and paths with safe permissions, quotas, lifetime, ownership, and crash-recovery cleanup state. Reject traversal, unsafe symlink escape, and access outside authorized roots.\n- Let an Agent workflow expose an authorized workspace path to an ordinary Provider operation only through that operation's declared payload when configured. SFP treats the payload as operation data and assigns no backup meaning to it.\n- Support engine-only workflows where the managed entity needs no Provider preparation or native backup/restore API. A Provider preparation or post-restore operation is optional workflow behavior, not a prerequisite for using a BackupEngine.\n- Keep workspaces alive while an operation or BackupEngine still owns them. Cleanup may remove only Agent-owned workspace resources after all consumers release them.\n- Record enough local provenance and lifecycle state to associate later engine results with the selected source/destination without turning an ordinary Provider response into standardized backup evidence.\n- Keep repository credentials and BackupEngine configuration out of Provider payloads, SFP metadata, and workspace-visible files unless an engine-specific secure mechanism explicitly requires them.\n\n- Extend the reusable A13 installed-Agent scenario catalogue with workspace security and lifecycle coverage against the exact installed Agent RPM, including deterministic filesystem faults and bounded retained evidence.\n\n## Acceptance evidence\n\nCI/CD evidence must cover isolation, traversal and symlink escape, permissions, quotas, concurrency, interruption, ownership transfer, retention, and cleanup.\n\nTest allocation, isolation, paths with spaces, traversal/symlink escape, permissions, quotas, concurrent workspaces, lifecycle handoff, cancellation, Agent interruption/recovery, in-use retention, and safe cleanup. Demonstrate both an engine-only workspace and a workspace path passed through an ordinary test operation payload.\n\n## Non-goals\n\nNo Protocol backup/DR contract, predefined operation identifier/schema/role, BackupEngine implementation, Restic adapter, Control Plane Snapshot, policy scheduling, or arbitrary filesystem deletion.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose. Choose compatible implementation details from the current codebase and document tradeoffs for human review. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step.",
        "sort_order": 29,
        "step_id": "A7",
        "title": "[TASK][MVP] Implement Agent-Managed Backup Workspaces",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/backup-engine-layer",
        "context_resources": [],
        "depends_on": [
          "A13",
          "A7"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nImplement a typed, stable in-process Agent BackupEngine extension layer over A7 workspaces. Engines are Agent tools/plugins, never Providers, operations, or SFP peers.\n\n## Required behavior\n\n- Discover engines through documented Python entry points and validate plugin identity, version, capabilities, and configuration. Keep plugin packaging independent from the Agent distribution and runtime construction explicit.\n- Define normalized create, restore, verify, inspect, and remove behavior with typed handles/results, finite deadlines, cooperative cancellation, bounded progress, errors, and cleanup ownership. Choose exact Python signatures from current Agent patterns and document them.\n- Create backups only from authorized Agent-selected sources/workspaces and restore only into authorized destinations/workspaces. The engine must not require the managed entity or its Provider to expose a native backup/restore operation.\n- Keep repository credentials/configuration inside the Agent/engine boundary and redact them from SFP, Provider operation payloads/results, CLI output, logs, and public diagnostics.\n- Make unsupported operation, capability, version, and configuration failures explicit before unsafe work. Isolate plugin failure without corrupting workspace ownership or durable backup evidence.\n- Distinguish a successful physical engine backup from any optional Provider preparation operation and from a future coordinated Control Plane Snapshot.\n\n- Extend the reusable A13 installed-Agent scenario catalogue with an independently packaged test BackupEngine, exercising installed-plugin discovery and deterministic lifecycle, compatibility, cancellation, failure, and credential-redaction cases.\n\n## Acceptance evidence\n\nCI/CD evidence must prove the exact Agent RPM discovers and isolates the packaged engine while preserving workspace ownership and the existing installed-Agent matrix.\n\nUse an independently packaged test engine to exercise discovery, capabilities, create/restore/verify/inspect/remove, invalid/missing/duplicate plugin, incompatible version/configuration, errors, deadlines, cancellation, scoped paths/handles, credential redaction, concurrent isolation, and an entity with no native backup API. Verify installed-package discovery and configured gates.\n\n## Non-goals\n\nNo BackupEngine RPC, Provider-side storage code, Protocol backup schema, concrete Restic adapter, vendor Provider, Control Plane retention scheduler, or mandatory native-language migration.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Choose compatible implementation details from the current codebase and document tradeoffs for human review. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step.",
        "sort_order": 30,
        "step_id": "A8",
        "title": "[TASK][MVP] Implement the BackupEngine Extension Layer",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/agent-rpm-ci-automation",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "a13-agent-instructions",
            "explanation": "Repository-wide implementation and human delivery rules.",
            "path": "AGENTS.md",
            "repository_alias": "agent",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "a13-rpm-packaging",
            "explanation": "Canonical RPM spec and service packaging consumed by reusable automation.",
            "path": "packaging/rpm",
            "repository_alias": "agent",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "a13-package-contract",
            "explanation": "Package version, build backend, Python support, and runtime dependency metadata.",
            "path": "pyproject.toml",
            "repository_alias": "agent",
            "required": true,
            "role": "must_verify",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "canonical",
            "context_id": "a13-existing-linux-tests",
            "explanation": "Existing Linux validation remains separate and must not be replaced by the packaging gate.",
            "path": "tools/linux-test",
            "repository_alias": "agent",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "canonical",
            "context_id": "a13-existing-tests",
            "explanation": "Existing behavioral gates remain authoritative while automation contract tests are added.",
            "path": "tests",
            "repository_alias": "agent",
            "required": true,
            "role": "must_preserve",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "canonical",
            "context_id": "a13-readme",
            "explanation": "Document the reusable local RPM build and installed-package verification commands.",
            "path": "README.md",
            "repository_alias": "agent",
            "required": true,
            "role": "expected_to_change",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 5
          }
        ],
        "depends_on": [
          "A1"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nCreate reusable GitHub Actions building blocks for the StateForge Agent RPM. Build and test logic is written once and reused by pull-request, pre-publication, and future publishing workflows. The implementation may combine YAML with Bash or Python where each is appropriate; it must not introduce a separate scenario framework or duplicate the Agent runtime.\n\n## Required behavior\n\n- Keep RPM construction in one documented, locally runnable command that uses the canonical RPM spec and produces the binary RPM, source RPM, checksums, and machine-readable build metadata.\n- Expose that command through a repository-local composite action with typed inputs and outputs, including version, artifact paths, and binary RPM SHA-256.\n- Provide a reusable `workflow_call` build workflow that builds once and uploads the immutable RPM artifact. Downstream testing and future publication must consume those exact bytes rather than rebuild.\n- Provide a reusable installed-RPM test action and workflow that download the artifact, verify checksums, install the binary RPM in clean supported Linux, verify package identity, files, ownership, import location, packaged service/configuration surface, and removal, and upload bounded evidence even on failure.\n- Provide a reusable gate that composes build then installed-package verification, plus thin pull-request/integration and manual release-candidate callers containing no copied setup or build commands.\n- Keep external actions pinned to immutable commit SHAs, permissions read-only, credentials out of build/test jobs, jobs bounded, and artifact retention explicit.\n- Keep shell commands independently runnable for local parity and document how later runtime tests and publishers consume the tested RPM artifact.\n- Be explicit about current packaging boundaries: until runtime dependencies are distributed as system packages, the packaging gate may verify artifact-owned surfaces without claiming the full daemon can start.\n\n## Acceptance evidence\n\nRun workflow/action validation; build the binary and source RPM on Linux; verify checksums and metadata; install the exact binary RPM in a clean Fedora environment; prove executable, Python package, systemd unit, configuration, sysusers, and tmpfiles content are owned by the RPM and not a checkout; remove the RPM; and retain evidence. Pass shell syntax checks, focused automation contract tests, Ruff, strict mypy, the existing Linux test suite, and strict documentation build.\n\n## Non-goals\n\nNo custom system-test framework, scenario DSL, dummy Provider suite, full runtime/service integration matrix, package signing/publication, organization-wide workflow repository, cloud infrastructure, or new Agent/SFP behavior.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed Agent behavior, existing repository checks, RPM layout, and human Issue/PR/review/merge authority. Prefer reusable workflows for job topology, composite actions for repeated runner steps, and small shell/Python commands for portable implementation details.",
        "sort_order": 31,
        "step_id": "A13",
        "title": "[TASK][MVP] Build Reusable Agent RPM CI/CD Pipelines",
        "verification_requirements": [
          {
            "explanation": "Validate reusable workflow syntax and interfaces.",
            "kind": "lint",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 0,
            "target": "actionlint .github/workflows/*.yml and composite-action metadata validation",
            "verification_id": "a13-workflow-validation"
          },
          {
            "explanation": "Validate the reusable local command layer.",
            "kind": "lint",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 1,
            "target": "bash -n packaging/rpm/*.sh",
            "verification_id": "a13-shell-contract"
          },
          {
            "explanation": "Enforce centralized build logic, exact-artifact handoff, thin callers, and immutable action pinning.",
            "kind": "test",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 2,
            "target": ".venv/bin/pytest -q -o addopts='' tests/test_rpm_automation.py",
            "verification_id": "a13-automation-contract-tests"
          },
          {
            "explanation": "Build the canonical binary RPM, source RPM, checksums, and metadata.",
            "kind": "command",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 3,
            "target": "packaging/rpm/build-rpm.sh",
            "verification_id": "a13-rpm-build"
          },
          {
            "explanation": "Install, verify, evidence, and remove the exact RPM in clean Fedora.",
            "kind": "test",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 4,
            "target": "packaging/rpm/test-installed-rpm.sh \u002d\u002drpm <built-binary-rpm>",
            "verification_id": "a13-rpm-install"
          },
          {
            "explanation": "Preserve project quality, behavior, typing, and documentation.",
            "kind": "test",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 5,
            "target": "ruff format \u002d\u002dcheck . && ruff check . && mypy src && pytest && mkdocs build \u002d\u002dstrict",
            "verification_id": "a13-repository-gates"
          },
          {
            "explanation": "Review artifact provenance, permissions, pinning, packaging boundaries, and reuse.",
            "kind": "human",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 6,
            "target": "GitHub Review",
            "verification_id": "a13-human-review"
          }
        ]
      },
      {
        "branch_name": "mvp/restic-backup-engine",
        "context_resources": [],
        "depends_on": [
          "A13",
          "A8"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nImplement `ResticBackupEngine` through A8's Agent-only extension contract. It provides physical backup and restoration for Agent-authorized data independently of Provider vendor behavior or native backup support.\n\n## Required behavior\n\n- Resolve an explicit trusted executable and validate the supported Restic version/capabilities. Build argument arrays without a shell; validate configuration and prevent executable/argument injection.\n- Keep repository credentials in controlled environment/files/input according to supported Restic interfaces, never command-line arguments, SFP, Provider payloads/results, or logs. Bound output, redact diagnostics, parse machine-readable output, and validate normalized handles/results.\n- Implement create from an authorized A7 source, restore into an authorized A7 destination, inspect, verify, and removal of an explicitly authorized engine-owned snapshot.\n- Preserve durable backup identity, provenance, and integrity evidence only after storage success. Never convert partial/nonzero-exit work into successful backup evidence.\n- Honor finite deadlines and cooperative/process-scoped cancellation with bounded subprocess termination/reaping and honest partial-effect reporting. Never terminate the Agent or unrelated engine work.\n- Support clean plugin packaging/configuration and diagnose a missing binary or incompatible version safely.\n\n- Extend the reusable A13 installed-Agent scenario catalogue with bounded real-Restic tests against the exact Agent RPM and packaged engine, using disposable repositories and deterministic failure injection.\n\n## Acceptance evidence\n\nCI/CD evidence must include create, inspect, verify, restore, remove, corruption, interruption, concurrency, credential-redaction, and cleanup cases.\n\nAutomated fixture/subprocess tests plus a bounded real-Restic local-repository create/inspect/verify/restore/remove round trip. Cover paths with spaces, no-shell execution, malformed output/nonzero exit, credential/log redaction, corrupt/missing backup, unauthorized handle/path, timeout/cancellation, concurrency, and an engine-only backup with no Provider operation.\n\n## Non-goals\n\nNo Restic service/RPC, Provider operation or vendor consistency logic, automatic retention/prune scheduler, unconstrained repository deletion, cloud credential provisioning, or platform-wide Snapshot coordination.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Choose compatible implementation details from the current codebase and document tradeoffs for human review. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step.",
        "sort_order": 31,
        "step_id": "A9",
        "title": "[TASK][MVP] Implement ResticBackupEngine",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/backup-restore-orchestration",
        "context_resources": [],
        "depends_on": [
          "A13",
          "A6",
          "A9",
          "R6"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nCompose Agent-owned BackupEngine work with optional ordinary Provider operations. The Agent performs physical backup/restore; Providers only execute explicitly configured generic operations through SFP.\n\n## Required behavior\n\n- Implement a local orchestration boundary that can create an engine backup from an authorized source and restore it to an authorized destination without requiring any Provider-native backup or restore feature.\n- Allow workflow configuration to invoke an ordinary declared Provider operation before backup, after backup, before restore, or after restore when the managed system needs quiesce, export, resume, import, reload, reconstruction, or verification behavior.\n- Send those calls through normal P4/P5 operation admission/lifecycle using each operation's own identifier and typed payload/result schema. The Agent and SFP must not recognize a predefined backup/DR role, operation name, payload, or result.\n- When configured, allocate an A7 workspace and place its authorized path and operation-specific data in the ordinary operation payload. The Agent already owns the path; it does not discover a standardized backup source from the Provider response.\n- Keep BackupEngine handles, repository credentials, physical storage results, and integrity checks inside the Agent. Validate restored data before any configured Provider post-restore operation and retain staging until all consumers release it.\n- Preserve immutable invocation identity, cancellation, deadlines, partial effects, and indeterminate outcomes. Do not automatically repeat a Provider operation or engine action after an ambiguous result.\n\n- Extend the reusable A13 installed-Agent scenario catalogue with backup-orchestration scenarios using the exact Agent RPM and packaged engine; flows involving Provider operations must use the exact Provider and Protocol wheels in a separate real process over the Unix socket.\n\n## Acceptance evidence\n\nCI/CD evidence must cover engine-only, prepare-then-create, restore-then-consume, failure, cancellation, ambiguous outcomes, workspace lifetime, credential isolation, and no duplicated side effects.\n\nTest an engine-only create/restore flow for an entity with no native backup API; a prepare-operation-to-engine-create flow; and an engine-restore-to-ordinary-Provider-operation flow. Cover corrupt data, operation rejection/failure, engine failure, cancellation, lost results, workspace lifetime, cleanup, credential isolation, and no duplicated side effects.\n\n## Non-goals\n\nNo Protocol backup/DR contract, Provider compliance layer, hard-coded operation catalogue, vendor-specific Agent code, Control Plane policy selection/Snapshot coordinator, or automatic retry after uncertainty.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed generic SFP contracts and repository boundaries. Choose orchestration interfaces from current Agent patterns so later SF-AOP/Control Plane plans can authorize the same local actions without redefining SFP. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step.",
        "sort_order": 32,
        "step_id": "A10",
        "title": "[TASK][MVP] Integrate Agent Backup and Restore Orchestration",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/sfp-reconciliation",
        "context_resources": [],
        "depends_on": [
          "A13",
          "A4",
          "A6",
          "P8",
          "R9"
        ],
        "release": "MVP",
        "repository_alias": "agent",
        "required_result": "## Outcome and ownership\n\nComplete Agent P8/R9 recovery by composing session replacement, manifest validation, health eligibility, durable triggers and admitted-operation evidence.\n\n## Required behavior\n\n- Distinguish transport interruption, same-installation new generation/process, and replacement installation. Rediscovers/re-handshakes use current identity/generation; retrieve or validate manifest and establish health before new admission.\n- Reconcile prior operations with original IDs through existing query/Watch semantics; replay retained progress/terminal evidence without redispatch. Retry pending trigger delivery/ack responsibility with original publication IDs and content.\n- Agent restart recovers its required journals/evidence and resumes responsibility; stable Provider installation identity alone is not proof the Provider retained execution state.\n- Missing/expired previously admitted records become explicit indeterminate outcomes. Never mark them failed/cancelled/succeeded by inference, manufacture a new ID, or automatically repeat an action with possibly completed side effects.\n- Replacement instances cannot inherit earlier executions. Fence stale session responses, old health/watch streams, changed manifest decisions and cursor gaps; preserve bounded backoff/backpressure and shutdown behavior.\n- Surface pending/indeterminate/cleanup evidence for later authority or human resolution through an internal boundary. Choose durable implementation from current Agent patterns; do not invent SF-AOP remediation messages.\n\n- Extend the reusable A13 installed-Agent scenario catalogue with deterministic disconnection and recovery coverage using exact artifacts and separate real Agent and Provider processes over the Unix socket.\n\n## Acceptance evidence\n\nCI/CD evidence must cover channel loss, lost replies and acknowledgements, generation replacement, Agent and Provider restart, retained and lost state, stale responses, expiry, and indeterminate outcomes without redispatch.\n\nAutomated scenarios cover channel loss with continuing work, lost admission reply/result/trigger ack, generation replacement, Agent restart, Provider restart with/without supported retained state, new installation, stale responses, expiry and workspace ownership. Prove each accepted execution/event is reconciled, not blindly repeated or dropped.\n\n## Non-goals\n\nNo compulsory Provider persistence, automatic business retry/remediation, Control Plane operator workflow, new SF-AOP contract or unrelated connection-manager redesign.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.\n\nChoose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here.",
        "sort_order": 33,
        "step_id": "A11",
        "title": "[TASK][MVP] Complete SFP Disconnection and Recovery",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/local-runtime-integration",
        "context_resources": [
          {
            "authority": "canonical",
            "context_id": "a12-dpt-skill",
            "explanation": "Cross-repository audit and completion-claim requirements.",
            "path": ".agents/skills/stateforge-dpt-milestone",
            "repository_alias": "agent",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 0
          },
          {
            "authority": "canonical",
            "context_id": "a12-protocol-skill",
            "explanation": "Agent consumer ownership and complete SFP verification rules.",
            "path": ".claude/skills/stateforge-protocol-development",
            "repository_alias": "agent",
            "required": true,
            "role": "must_understand",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 1
          },
          {
            "authority": "canonical",
            "context_id": "a12-responsibility-boundaries",
            "explanation": "Release-wide boundary matrix reconciled against the final installed system.",
            "path": "docs/reference/responsibility-boundaries.md",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "file",
            "selector_value": null,
            "sort_order": 2
          },
          {
            "authority": "compatibility",
            "context_id": "a12-protocol-contracts",
            "explanation": "All authoritative SFP contracts used by the complete runtime.",
            "path": "src/stateforge_protocol/sfp",
            "repository_alias": "protocol",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 3
          },
          {
            "authority": "compatibility",
            "context_id": "a12-provider-runtime",
            "explanation": "Complete Provider runtime and author-facing integration surface.",
            "path": "src/stateforge_provider",
            "repository_alias": "provider",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 4
          },
          {
            "authority": "canonical",
            "context_id": "a12-agent-sfp",
            "explanation": "Complete Agent SFP consumer, availability, recovery, and session surface.",
            "path": "src/stateforge_agent/_sfp",
            "repository_alias": "agent",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 5
          },
          {
            "authority": "canonical",
            "context_id": "a12-agent-actions",
            "explanation": "Reusable installed-artifact test framework and complete scenario catalogue.",
            "path": ".github/actions",
            "repository_alias": "agent",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 6
          },
          {
            "authority": "compatibility",
            "context_id": "a12-provider-actions",
            "explanation": "Reusable Provider fixture and runtime scenario actions used by the system matrix.",
            "path": ".github/actions",
            "repository_alias": "provider",
            "required": true,
            "role": "must_verify",
            "selector_kind": "directory",
            "selector_value": null,
            "sort_order": 7
          }
        ],
        "depends_on": [
          "A10",
          "A11",
          "A13",
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
        "required_result": "## Outcome and ownership\n\nVerify the complete local Agent/Provider foundation using separate real processes plus an installed BackupEngine/Restic plugin. Prove generic SFP and Agent-owned backup tooling compose without adding backup semantics to the Protocol or Provider runtime.\n\n## Required behavior\n\n- Exercise discovery/identity/handshake, manifest validation/revision caching, standard health, capability assessment, durable triggers, arbitrary typed operation admission, progress/results/cancellation, and reconnect over one multiplexed channel per active endpoint.\n- Demonstrate multiple unrelated Provider operations whose payload/result schemas are opaque to SFP. No test may require a predefined backup/DR operation identifier, compliance role, Protocol backup schema, or Provider knowledge of BackupEngine.\n- Exercise an engine-only physical backup/restore for an entity with no native backup API. Also exercise an optional ordinary Provider preparation operation before engine create and an optional ordinary Provider consume/reload operation after engine restore.\n- Cover concurrency and failure/crash boundaries: duplicate/conflicting IDs, lost replies/acknowledgements, invalid schemas/results, readiness changes, stale generations, cancellation races, corrupt storage, process restarts, indeterminate state, and scoped cleanup. Do not automatically repeat unresolved effects.\n- Verify local backup identity/provenance, engine integrity evidence, operation evidence, and workspace ownership remain distinct and available through clean internal coordination boundaries. Do not claim local physical backups are already coordinated Control Plane Snapshots.\n- Build and clean-install involved distributions, verify packaged contracts/typing/plugin resources/public docs, and pass all applicable gates on the supported runtime/platform matrix.\n\n- Maintain a machine-checked coverage inventory mapping every planned SFP and Agent-owned backup capability to focused scenarios and the full installed-artifact matrix; missing coverage is a release-blocking failure.\n\n## Acceptance evidence\n\nCI/CD evidence must prove the exact Protocol wheel, Provider wheel, Agent RPM, test BackupEngine package, and Restic integration pass the complete supported Linux runtime matrix.\n\nA repeatable automated real-process matrix proves generic SFP interoperability, engine-only backup/restore, optional Provider-operation choreography, credential isolation, and honest recovery from uncertainty. Record the local phase exit evidence and open questions for the later required SF-AOP and Control Plane phases.\n\n## Non-goals\n\nNo SF-AOP/Control Plane implementation, Protocol backup/DR profile, fabricated global consistency guarantee, vendor-specific Agent code, production policy engine, or broad architecture migration.\n\n## Compatibility, discretion, and delivery\n\nPreserve landed generic contracts and repository boundaries. Current code wins existing disagreements with prose. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step.",
        "sort_order": 34,
        "step_id": "A12",
        "title": "[TASK][MVP] Verify the Complete Local Agent and Provider Runtime",
        "verification_requirements": [
          {
            "explanation": "The complete Agent suite passes.",
            "kind": "test",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 0,
            "target": "python -m pytest -q",
            "verification_id": "a12-agent-tests"
          },
          {
            "explanation": "Formatting, linting, typing, and strict documentation pass.",
            "kind": "command",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 1,
            "target": "python -m ruff format \u002d\u002dcheck . && python -m ruff check . && python -m mypy src && python -m mkdocs build \u002d\u002dstrict",
            "verification_id": "a12-agent-quality"
          },
          {
            "explanation": "The shipped system exercises every planned SFP procedure, backup capability, failure boundary, and supported Linux runtime.",
            "kind": "integration",
            "repository_alias": "agent",
            "required": true,
            "sort_order": 2,
            "target": "Run the complete installed-artifact matrix with the exact Protocol wheel, Provider wheel, Agent RPM, BackupEngine fixture, and Restic integration in separate processes.",
            "verification_id": "a12-installed-system"
          },
          {
            "explanation": "Equivalent behavior comes from one canonical contract rather than duplicated implementations.",
            "kind": "integration",
            "repository_alias": null,
            "required": true,
            "sort_order": 3,
            "target": "Run Protocol contract tests and Agent/Provider ownership-delegation suites against the exact artifacts used by the system matrix.",
            "verification_id": "a12-ownership-tests"
          },
          {
            "explanation": "No unaudited repository, unclassified rule, missing scenario, or duplicate normative implementation remains when local runtime completion is claimed.",
            "kind": "human",
            "repository_alias": null,
            "required": true,
            "sort_order": 4,
            "target": "Approve the final responsibility and coverage inventories for every SFP procedure and shared endpoint resource.",
            "verification_id": "a12-release-closure"
          }
        ]
      },
      {
        "branch_name": "mvp/provider-views-contract",
        "context_resources": [],
        "depends_on": [
          "P1",
          "P10",
          "P3",
          "P4"
        ],
        "release": "MVP",
        "repository_alias": "protocol",
        "required_result": "Extend the existing Provider Manifest Exchange contract so manifest-declared operations and triggers can carry safe declarative presentation metadata and reference bounded, content-addressed Provider-owned assets. Keep presentation revisioning separate from operational contract revisioning so visual-only changes do not alter execution semantics, invalidate operation admission, or disrupt trigger streams. Operation Admission and Trigger Publication continue to use their existing endpoints and identifiers, resolve views through the accepted declaration snapshot, and gain documentation and conformance coverage without new RPC services. Define strict formats, limits, digest validation, reference integrity, and safe fallback behavior; prohibit executable frontend code and unrestricted remote resources.",
        "sort_order": 35,
        "step_id": "P11",
        "title": "[TASK][MVP] Add Versioned Provider Views to Manifest-Declared Operations and Triggers",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/provider-view-dsl",
        "context_resources": [],
        "depends_on": [
          "P11",
          "R1",
          "R11",
          "R4",
          "R5"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Provide typed Python authoring constructs that let Provider developers attach declarative views directly to operation and trigger declarations. The DSL must produce the Protocol-owned presentation model without requiring authors to construct protobuf messages, preserve static typing and inherited declaration behavior, validate references deterministically, and expose no arbitrary HTML, CSS, JavaScript, or executable frontend extension point.",
        "sort_order": 36,
        "step_id": "R12",
        "title": "[TASK][MVP] Add Declarative Operation and Trigger Views to the Provider Python DSL",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/provider-presentation-assets",
        "context_resources": [],
        "depends_on": [
          "P11",
          "R11",
          "R12"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Allow Provider packages to ship the icons, logos, illustrations, diagrams, images, SVG resources, and other bounded static visual assets referenced by their declarative operation and trigger views. Discover and package assets reproducibly, calculate content digests, validate media types, dimensions and size limits, reject traversal, symlink, malformed, executable, and remote-resource hazards, and deduplicate identical content without exposing arbitrary Provider filesystem paths.",
        "sort_order": 37,
        "step_id": "R13",
        "title": "[TASK][MVP] Package Provider-Owned Icons, Images, and Presentation Assets",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/provider-view-manifest-publication",
        "context_resources": [],
        "depends_on": [
          "P11",
          "R1",
          "R11",
          "R12",
          "R13"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Integrate Provider-authored operation views, trigger views, and validated asset references into the existing manifest construction and GetManifest response. Produce deterministic presentation revisions and canonical output while preserving the independent operational manifest revision and all existing session, schema-negotiation, size, and stale-response fences. Presentation-only changes must be observable without changing operation or trigger execution contracts and must not require another SFP endpoint.",
        "sort_order": 38,
        "step_id": "R14",
        "title": "[TASK][MVP] Publish Versioned Provider Views through Manifest Exchange",
        "verification_requirements": []
      },
      {
        "branch_name": "mvp/provider-view-verification",
        "context_resources": [],
        "depends_on": [
          "P11",
          "R11",
          "R12",
          "R13",
          "R14"
        ],
        "release": "MVP",
        "repository_alias": "provider",
        "required_result": "Add conformance and installed-package coverage for operation and trigger view authoring, safe fallback declarations, asset packaging and rejection, deterministic content digests, canonical presentation revisions, and manifest publication. Prove that a presentation-only edit changes the presentation revision without changing the operational manifest revision or affecting existing operation-admission and trigger-publication behavior, and preserve evidence through the reusable Provider CI/CD framework.",
        "sort_order": 39,
        "step_id": "R15",
        "title": "[TASK][MVP] Verify Provider View Declarations, Assets, and Revision Semantics",
        "verification_requirements": []
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
**Revision:** 25

## Repositories

| Alias | GitHub repository | Responsibility |
| --- | --- | --- |
| `agent` | [stateforge-org/stateforge-agent](https://github.com/stateforge-org/stateforge-agent) | Agent-side integration, staging, and backup tooling. |
| `protocol` | [stateforge-org/stateforge-protocol](https://github.com/stateforge-org/stateforge-protocol) | Versioned StateForge Protocol wire contracts. |
| `provider` | [stateforge-org/stateforge-provider-python](https://github.com/stateforge-org/stateforge-provider-python) | Provider runtime and author-facing integration surface. |
| `control-plane` | [stateforge-org/stateforge-control-plane](https://github.com/stateforge-org/stateforge-control-plane) | StateForge Control Plane |
| `sf-aop` | [stateforge-org/stateforge-aop](https://github.com/stateforge-org/stateforge-aop) | StateForge Agent Orchestration Protocol |

## Implementation roadmap

| Step | Repository | Required implementation | Depends on | State | GitHub |
| --- | --- | --- | --- | --- | --- |
| `P0` | `protocol` | **[TASK][MVP] Define SFP Handshake and Version Negotiation**<br>Bootstrap v1 selects one mutually supported wire version and binds discovered Provider identity and generation. | — | `COMPLETED` | [Issue #1](https://github.com/stateforge-org/stateforge-protocol/issues/1) · [Pull Request #2](https://github.com/stateforge-org/stateforge-protocol/pull/2) |
| `P1` | `protocol` | **[TASK][MVP] Define Provider Manifest Exchange Contract**<br>Version the effective manifest, Provider identity, runtime requirements, configuration schema, namespaced operation identifiers, trigger declarations, and explicit backup/DR compliance profiles. Do not encode a closed operation enum. | `P0` | `COMPLETED` | [Issue #3](https://github.com/stateforge-org/stateforge-protocol/issues/3) · [Pull Request #4](https://github.com/stateforge-org/stateforge-protocol/pull/4) |
| `P2` | `protocol` | **[TASK][MVP] Define Capability Assessment Contract**<br>Assess a declared operation identifier against a target and return normalized support, requirements, reasons, and assessment identity. | `P1` | `COMPLETED` | [Issue #5](https://github.com/stateforge-org/stateforge-protocol/issues/5) · [Pull Request #9](https://github.com/stateforge-org/stateforge-protocol/pull/9) |
| `P3` | `protocol` | **[TASK][MVP] Define Trigger Publication and Acknowledgement Contract**<br>## Outcome and ownership  Define the Protocol-only SFP contract for Provider-originated, manifest-declared trigger publication and acknowledgements on an Agent-initiated bidirectional stream over the existing channel. See `docs/procedures/triggers.md` and the SFP Trigger Publication and Acknowledgement specification.  ## Required behavior  - Define a bounded envelope with stable publication ID, versioned trigger identifier, schema-bound payload, and event time. Bind the publisher to the authenticated Provider instance and active SFP session; do not add a generic target, source, or resource identity to the envelope. Trigger-specific source/resource identity, when required, belongs in the declared trigger payload schema. - Specify field ownership, presence/defaults, schema validation, limits, ordering, and canonical content equality. A retransmission keeps the same ID and semantic content; ID reuse with different content is a conflict. - Define ACCEPTED_NEW, ACCEPTED_DUPLICATE, and REJECTED acknowledgements, rejection reasons, correlation, retryability, and stream termination/backpressure. Separate event-delivery identity from any later policy-run identity. - ACCEPTED_NEW means the Agent durably assumed delivery responsibility before acknowledging. How the Agent satisfies that responsibility locally or later hands work downstream is outside P3 and is not exposed to the Provider. Losing an acknowledgement permits replay, not a second logical publication. - State retention/replay limitations explicitly, including reconnect and optional Provider persistence. Do not promise exactly-once business execution from delivery deduplication.  ## Acceptance evidence  Ship versioned protobuf sources, generated bindings, contract documentation, and reusable valid/invalid fixtures. Cover serialization, authenticated service/session identity, unknown or undeclared trigger IDs, invalid payload/envelope/session, duplicate versus conflicting content, lost-ack replay, bounded messages, acknowledgement correlation, and the absence of generic target/source/resource fields. Describe independent Agent/Provider implementation behavior without implementing either runtime.  ## Non-goals  No generic target/source/resource abstraction, SF-AOP transport, Control Plane mapping, policy evaluation, trigger-to-component inference, or mandatory persistent Provider database.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P1` | `COMPLETED` | [Issue #17](https://github.com/stateforge-org/stateforge-protocol/issues/17) · [Pull Request #23](https://github.com/stateforge-org/stateforge-protocol/pull/23) |
| `P4` | `protocol` | **[TASK][MVP] Define Operation Admission and Idempotency Contract**<br>## Outcome and ownership  Define the Protocol-only generic operation-admission contract. Any manifest-declared operation may be invoked; backup/DR are explicit profiles, not a closed list of transport commands. See `docs/procedures/operation-admission.md` and the SFP admission specification.  ## Required behavior  - Define an immutable invocation: Agent-assigned operation ID before contact, versioned operation identifier, normalized target, validated payload, deadline, pinned schema/profile context where applicable, and execution context. Specify field ownership, presence, limits, and current-session validation. - Define the canonical fingerprint projection and golden vectors. Distinguish semantic invocation fields from transport/session fields so reconnecting does not turn an identical retry into a different execution. - Admission is atomic before author/vendor behavior starts. A new ID creates one record and dispatch; matching ID/fingerprint resolves the existing state/result; the same ID with different content conflicts. Concurrent duplicate submissions must not dispatch twice. - Keep ACCEPTED_NEW and RESOLVED_EXISTING as successful admission dispositions. Invalid, undeclared, incompatible, busy, or conflicting requests use specified gRPC statuses and structured reasons; rejection creates no accepted record. - Define deadline boundaries, retry guidance, and externally observable retention/expiry behavior. Lost responses can be resolved with the same immutable request while state is retained; lost/expired admitted state is unresolved, not permission for automatic redispatch. A genuinely new authorized attempt needs a new ID. - Separate SFP delivery idempotency from the underlying action's business idempotency. Do not add execution metadata by silently changing P1 schema 1.  ## Acceptance evidence  Ship versioned sources/bindings, explicit status/reason tables, fingerprints, and contract fixtures covering defaults, invalid IDs/payloads, unknown operations, equivalent retry, changed target/payload/context, concurrent duplicate semantics, deadline-before-admission, replay of terminal records, and retention/state-loss boundaries. Contract tests do not implement a registry.  ## Non-goals  No Provider scheduler, Agent dispatch implementation, universal persistent registry, automatic retry of indeterminate side effects, arbitrary shell execution, SF-AOP, or policy engine.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P1`, `P2` | `COMPLETED` | [Issue #16](https://github.com/stateforge-org/stateforge-protocol/issues/16) · [Pull Request #20](https://github.com/stateforge-org/stateforge-protocol/pull/20) |
| `P5` | `protocol` | **[TASK][MVP] Define Operation Progress Results and Cancellation Contract**<br>## Outcome and ownership  Define generic operation observation, terminal outcomes, and cancellation in Protocol, building on P4. See `docs/procedures/progress-results-cancellation.md` and the SFP lifecycle specification.  ## Required behavior  - Specify ACCEPTED, RUNNING, CANCELLATION_REQUESTED, SUCCEEDED, FAILED, and CANCELLED, their legal transitions, presence rules, and the difference between wire status and operation outcome. - Observation attaches only to an already admitted operation; it never dispatches work. Replay current state/latest retained progress immediately and the immutable result when terminal. - Define per-operation monotonic sequence/cursor semantics, bounded retention and coalescing, gap handling, reconnect behavior, and slow-observer backpressure. Do not promise unlimited history; never discard a terminal result while its record is retained. - Success contains a schema-valid typed result. Failure contains structured, sanitized reasons and relevant partial-side-effect/cleanup metadata without secrets or remote tracebacks. Define invalid author-result handling. - Specify cancellation accepted/requested, unsupported, and already-terminal outcomes. CANCELLED means execution actually stopped, not that a request arrived. The first terminal outcome wins a completion/cancellation race and remains immutable. - Cancelling a Watch or losing transport does not cancel business execution. Cancellation is operation-scoped; it must not terminate the shared Provider process or unrelated streams. An RPC deadline is not proof that side effects stopped.  ## Acceptance evidence  Ship schemas/bindings, transition and error tables, and fixtures/tests for initial/late Watch, sequence replay/gaps, terminal immutability, result-schema errors, failure metadata, cancellation races, unsupported cancellation, unknown IDs, and stream termination. Document what is retained versus indeterminate.  ## Non-goals  No runtime task manager, full event-log service, process-kill cancellation, backup-specific transport command, or invented Control Plane response to uncertainty.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P4` | `COMPLETED` | [Issue #21](https://github.com/stateforge-org/stateforge-protocol/issues/21) · [Pull Request #22](https://github.com/stateforge-org/stateforge-protocol/pull/22) |
| `P6` | `protocol` | **[TASK][MVP] Define Provider Health and Operational Eligibility Contract**<br>## Outcome and ownership  Define the Protocol contract for Provider service health and Agent operational eligibility by standardizing StateForge's use of `grpc.health.v1` on the existing multiplexed SFP channel. This milestone owns normative cross-runtime semantics and documentation; it must not introduce a custom StateForge health protobuf.  ## Required behavior  - Specify the exact versioned SFP service name or names registered with the standard gRPC Health service and how the empty service name and unknown services are handled. - Define Provider lifecycle transitions for startup, validated readiness, `SERVING`, `NOT_SERVING`, degraded or maintenance state, and bounded shutdown. Stop advertising eligibility for new work before teardown. - Define Check as diagnostic and Watch as the authoritative ongoing health observation, including initial replay, ordered changes, bounded observers, backpressure, stream termination, retry, and recovery. - Separate Provider-supplied service health from Agent-derived operational eligibility. Eligibility requires current transport, a valid handshake/session/generation, a compatible accepted manifest, and `SERVING` health. - Fence stale health updates after session or endpoint-generation replacement, manifest rejection, reconnect, or shutdown. - Specify that health loss blocks new operation admission but does not rewrite, cancel, or replace already admitted operations or terminal results. - State explicitly that `SERVING` is not capability assessment, target-specific availability, authorization, or proof that every declared operation can currently succeed. - Define bounded diagnostics and sanitized failures without exposing Provider configuration, credentials, customer data, or vendor-specific probe details.  - Extend the reusable P10 Protocol CI/CD framework with health-owned conformance fixtures and validation scenarios, and register them in the standard pull-request, integration, and release-candidate workflows rather than creating a duplicate top-level pipeline.  ## Acceptance evidence  CI/CD evidence must show that the exact built Protocol artifacts contain and pass the health procedure's valid, invalid, lifecycle, compatibility, and boundary cases.  Publish a complete client-facing procedure and updated sequence diagram. Cover startup and shutdown, named and unknown services, Check and Watch, initial state, state changes, Watch loss and recovery, stale-session fencing, valid health with an invalid manifest, and admitted work surviving health loss. Document independent Agent and Provider obligations and verify that no custom health protobuf, second channel, Control Plane reporting, or vendor polling contract is introduced.  ## Non-goals  No Provider implementation, Agent availability coordinator, capability assessment, operation admission implementation, business-operation cancellation, Control Plane status, SF-AOP contract, or vendor-specific health probes.  ## Compatibility, discretion, and delivery  Preserve landed SFP 1.0 contracts, public APIs, repository boundaries, and standard gRPC Health semantics. Current code wins existing disagreements with prose. New incompatible behavior requires explicit versioning. Implement only the assigned Issue, add applicable contract checks and documentation, and preserve the human-owned Issue, PR, review, and merge workflow. | `P0`, `P1`, `P10` | `COMPLETED` | [Issue #27](https://github.com/stateforge-org/stateforge-protocol/issues/27) · [Pull Request #33](https://github.com/stateforge-org/stateforge-protocol/pull/33) |
| `P10` | `protocol` | **[TASK][MVP] Build Reusable Protocol Package and Contract CI/CD Pipelines**<br>## Outcome and ownership  Create a reusable GitHub Actions ecosystem for StateForge Protocol contract validation and Python package delivery. Generation, validation, package construction, installed-artifact verification, and evidence collection are written once and composed by pull-request, integration, release-candidate, and future publication workflows. Do not create a second protocol model or monolithic test harness.  ## Required behavior  - Keep contract generation and package construction available through documented local commands using the canonical Buf configuration, protobuf sources, generation check, and Python metadata. - Organize repository-local composite actions by responsibility under `.github/actions/`: contract generation/validation, Python artifact construction, installed-package verification, and evidence collection. Scenario checks compose these actions instead of copying setup. - Provide reusable `workflow_call` workflows under `.github/workflows/` that build wheel and sdist once, record checksums/provenance, and upload immutable artifacts. Verification and future publication consume those exact bytes. - Verify Buf linting, deterministic generation, committed-binding drift, protobuf imports, ProtoJSON/schema fixtures, and the complete contract suite. - Install the exact wheel in clean environments outside the checkout and without repository `PYTHONPATH`; prove metadata, typed marker, generated protobuf/gRPC modules, schemas, and fixtures work on every supported Python version and applicable operating system. - Pin external actions to immutable SHAs; keep permissions read-only, credentials out of build/test jobs, jobs bounded, caches dependency-keyed, and artifact/evidence retention explicit. - Preserve bounded failure evidence and document local parity commands, action inputs/outputs, artifact identity, and how consumers reuse the tested artifact. - Prefer declarative actions and existing commands. Add shell or Python only where portable logic requires it; do not duplicate package, Buf, or test behavior in workflow YAML.  ## Acceptance evidence  Validate action/workflow metadata; run Buf lint and deterministic generation/drift checks; build wheel and sdist once; verify hashes/provenance; install the exact wheel outside the checkout across supported Python versions; import representative protobuf/gRPC modules; load packaged resources; run the contract suite; and retain failure evidence. Pass Ruff, formatting, strict mypy, pytest, generated-source validation, package build, installed-package smoke tests, and strict docs.  ## Non-goals  No SFP semantic or protobuf changes, generated-code fork, compatibility-policy change, publication/signing, Agent or Provider runtime implementation, cross-process system-test framework, or organization-wide workflow repository.  ## Compatibility, discretion, and delivery  Preserve landed SFP contracts, package/import paths, generation policy, supported Python versions, repository checks, and human Issue/PR/review/merge authority. Reusable workflows own job topology, composite actions own repeated runner steps, and project commands remain the local source of truth. | `P5` | `COMPLETED` | [Issue #28](https://github.com/stateforge-org/stateforge-protocol/issues/28) · [Pull Request #30](https://github.com/stateforge-org/stateforge-protocol/pull/30) |
| `P8` | `protocol` | **[TASK][MVP] Define SFP Disconnection Recovery Contracts**<br>## Outcome and ownership  Complete Protocol semantics for safe reconnect and reconciliation across discovery/bootstrap, manifest, health, triggers, and admitted operations. See `docs/procedures/disconnection-recovery.md` and the SFP recovery specification.  ## Required behavior  - Distinguish transport loss, endpoint-generation replacement, same-installation process restart, and replacement installation. Re-handshake and validate manifest/health before new admission; an old session is not reusable authority. - Reuse P3/P5 publication IDs, operation IDs, and cursors where sufficient. Add only genuinely required missing wire messages; do not invent a second reconciliation service merely for symmetry. - A live Provider process may continue work during channel loss and replay retained state/results after reconnect. Lost Watch/acknowledgement does not start another execution or logically duplicate a trigger. - Define retained, lost/expired, incompatible, and replacement outcomes. A replacement instance cannot claim another instance's executions. Missing previously admitted state is indeterminate, not FAILED and not authorization to retry with a new ID. - Stable persisted Provider installation identity does not imply persisted operation/trigger state. Baseline runtime state is in memory; stronger Provider-owned persistence is optional. Document restart limitations and retention boundaries. - Specify stale-stream fencing, identity correlation, cursor gaps, backoff/retryability, and safe acknowledgement replay. Unknown outcome remains visible to a later decision-maker; SFP does not choose the business remediation.  - Extend the reusable P10 Protocol CI/CD framework with recovery-owned conformance fixtures and validation scenarios, and register them in the standard pull-request, integration, and release-candidate workflows rather than creating a duplicate top-level pipeline.  ## Acceptance evidence  CI/CD evidence must show that the exact built Protocol artifacts contain and pass the recovery procedure's reconnect, replay, stale-session, state-loss, compatibility, and boundary cases.  Contract scenarios cover lost admission reply, lost trigger acknowledgement, interrupted Watch, same-process reconnect, changed generation, process restart with lost state, persisted-state recovery where supported, new-instance replacement, stale replies, and invalid/expired cursors. Verify recovery composes with P3/P4/P5 without changing their identity semantics.  ## Non-goals  No runtime reconnect loop, compulsory persistent Provider storage, automatic re-execution after uncertainty, SF-AOP protocol, or Control Plane/operator remediation implementation.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P10`, `P3`, `P5`, `P6` | `PENDING` | [Issue #26](https://github.com/stateforge-org/stateforge-protocol/issues/26) |
| `P9` | `protocol` | **[TASK][MVP] Verify the Complete SFP Contract Surface**<br>## Outcome and ownership  Verify that the complete local SFP transport and generic-operation contract package can be consumed independently by Agent and Provider developers. This is Protocol integration/conformance work, not business-operation or runtime implementation.  ## Required behavior  - Verify bootstrap, manifest, capability assessment, triggers, generic operation admission, lifecycle/progress/results/cancellation, and reconnect/recovery compose coherently. Identifier ownership, session/generation validation, versioning, error taxonomy, retention, and replay semantics must agree. - Prove SFP transports arbitrary declared operations through their own typed payload/result schemas without interpreting application meaning. Backup preparation, restore, disaster recovery, and BackupEngine behavior are not SFP procedures or Protocol-owned schemas. - Preserve landed bootstrap and manifest contracts. Keep operations as versioned namespaced strings, retain generic `implements` declarations without assigning Protocol-owned backup/DR meaning, and document only the current active contract. - Supply reusable conformance fixtures for ordinary operations, invalid schemas/results, duplicate/conflicting admission, progress/cancellation, trigger replay, channel loss, and state-loss recovery. - Check Buf lint, reproducible generation, generated-source freshness and compatibility. Generated modules must never be hand-edited. Ensure required protobuf/schema fixtures, typing markers, and documentation are included in wheel and sdist. - Verify clean installation/imports and dependency compatibility for supported Python versions/platforms. Separate build tooling from runtime dependencies and build strict documentation.  - Maintain a machine-checked coverage inventory mapping every SFP procedure to its packaged conformance assets and standard CI entry points; missing procedure coverage is a release-blocking failure.  ## Acceptance evidence  CI/CD evidence must prove every planned SFP procedure is represented in the exact wheel and sdist and is executed by the full contract matrix.  All configured Protocol gates pass, installed-package consumers load every generic SFP service/schema/fixture, and independent Agent/Provider test peers make the same transport, validation, identity, idempotency, and recovery decisions. No fixture requires knowledge of BackupEngine or a predefined backup/DR operation.  ## Non-goals  No Agent/Provider runtime, business-operation catalogue, backup/DR schema, BackupEngine implementation, SF-AOP design, or Control Plane contract.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose. Choose compatible implementation details from the current codebase and document tradeoffs for human review. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. | `P1`, `P10`, `P2`, `P3`, `P4`, `P5`, `P6`, `P8` | `BLOCKED` | — |
| `R0` | `provider` | **[TASK][MVP] Implement Provider Discovery and Handshake Foundation**<br>Publish a ready local endpoint and negotiate one SFP session on the Agent-established channel. | `P0` | `COMPLETED` | [Issue #1](https://github.com/stateforge-org/stateforge-provider-python/issues/1) · [Pull Request #2](https://github.com/stateforge-org/stateforge-provider-python/pull/2) |
| `R1` | `provider` | **[TASK][MVP] Implement Provider Manifest Exchange**<br>Let Provider authors declare a validated effective manifest containing generic operation identifiers, triggers, runtime requirements, configuration schema, and explicit compliance profiles. | `P1` | `COMPLETED` | [Issue #3](https://github.com/stateforge-org/stateforge-provider-python/issues/3) · [Pull Request #10](https://github.com/stateforge-org/stateforge-provider-python/pull/10) |
| `R2` | `provider` | **[TASK][MVP] Implement Provider Health and Availability Reporting**<br>## Outcome and ownership  Expose standard `grpc.health.v1` on the existing standalone Provider server and connect it to the public Provider lifecycle/health hook. Use standard generated health contracts, not a new StateForge health protobuf.  ## Required behavior  - Register the actual negotiated operational service name(s) on the same multiplexed server/channel. Explicitly define startup NOT_SERVING, validated readiness SERVING, failed/degraded readiness, maintenance, and bounded shutdown behavior. - Keep author-facing status typed and simple; the runtime adapts it to standard Check/Watch. Health does not become a vendor polling scheduler or expose protobuf construction to authors. - Watch emits current status and changes with bounded observers/backpressure; invalid services and stream failures follow standard health semantics. Check is diagnostic, not a replacement for ongoing Watch. - Stop new operation eligibility before maintenance/shutdown. A health transition does not itself cancel admitted operations, and SERVING does not override an invalid manifest/session or guarantee target-specific capability. - Sanitize unexpected hook failures, prevent stale readiness from surviving a generation change, and clean up watchers/resources owned by this runtime only.  - Extend the reusable R11 Provider scenario catalogue with health-specific installed-runtime coverage using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket; do not substitute a simulated Agent transport.  ## Acceptance evidence  CI/CD evidence must include the focused health scenario in pull requests and the unchanged full Provider scenario matrix.  Exercise real gRPC Check/Watch on the same endpoint as handshake/manifest, initial and changed status, unknown service, hook failure, slow/disconnected observers, restart, and shutdown. Verify typed author examples and no duplicate server/channel or custom StateForge health contract.  ## Non-goals  No Agent availability coordinator, Control Plane reporting, business-operation cancellation, vendor-specific health logic, or implementation of later admission APIs.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P6`, `R1`, `R11` | `COMPLETED` | [Issue #16](https://github.com/stateforge-org/stateforge-provider-python/issues/16) · [Pull Request #22](https://github.com/stateforge-org/stateforge-provider-python/pull/22) |
| `R3` | `provider` | **[TASK][MVP] Implement Provider Capability Assessment**<br>## Outcome and ownership  Implement the locked P2 capability-assessment contract behind a typed, overridable Provider capability hook, compatible with R1 manifest declarations and R2 readiness. P2's issued requirements remain unchanged.  ## Required behavior  - Validate negotiated session/generation, target kind, requested versioned operation IDs, configuration/execution context, payload limits, and current declarations before invoking author code. - Perform only bounded read-only inspection. Return the contract's normalized SUPPORTED, SUPPORTED_WITH_REQUIREMENTS, UNSUPPORTED, or INDETERMINATE findings and correlation identity, with explicit reasons/requirements for each requested operation as the landed contract permits. - Preserve the difference between declared support, runtime/target compatibility, temporary unavailability, and proven satisfaction of prerequisites. Unknown requirements or a manifest declaration alone are not evidence of support. - Keep capability findings operation-generic: never add or echo backup-preparation result variants, storage-tool choices, or other operation-specific result fields. Profile conformance belongs to the declared versioned operation schemas and later admission/execution paths. Keep target-specific business inspection in author code; the runtime never assigns logical StateForge component IDs. - Negative assessment is a valid domain result, not automatically an RPC failure. Invalid protocol input and hook/transport failures follow P2's error mapping; sanitize remote diagnostics and honor finite deadlines/cancellation of the read. - Reuse the Provider framework and existing schema/model facilities. Do not independently reinterpret or redesign P2 while implementing its consumer.  - Extend the reusable R11 Provider scenario catalogue with capability-assessment installed-runtime coverage using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket; do not substitute a simulated Agent transport.  ## Acceptance evidence  CI/CD evidence must include focused capability success, rejection, malformed-response, deadline, stale-session, and limit scenarios plus the unchanged full Provider matrix.  Cover generic and profile-related assessment, all support statuses, conditional/unknown requirements, undeclared IDs/kinds, malformed context, correlation, stale session, hook exception/deadline, absence of operation-specific result fields, and absence of target mutation. Verify public hook documentation and configured gates.  ## Non-goals  No operation dispatch, target mutation, mandatory persistence, Agent/Control Plane mapping, policy evaluation, or universal vendor-version evaluator.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P2`, `R1`, `R11`, `R2` | `PENDING` | [Issue #23](https://github.com/stateforge-org/stateforge-provider-python/issues/23) |
| `R4` | `provider` | **[TASK][MVP] Implement Trigger Publication and Acknowledgement**<br>## Outcome and ownership  Implement P3 Provider publication with a simple typed author-facing trigger API on the existing Provider framework. The runtime owns envelopes, stream adaptation, acknowledgement, and retries.  ## Required behavior  - Publish only manifest-declared versioned trigger IDs and schema-valid payloads. Derive authenticated installation/session identity internally. Do not accept a generic target, source, or resource identity; any trigger-specific resource/source information is ordinary schema-validated payload data. - Allocate/preserve stable publication identity and canonical semantic content. Keep bounded pending state until accepted/rejected, correlate acknowledgements, handle new/duplicate/rejected dispositions, and surface rejection safely to authors. - Lost acknowledgements and transient streams replay the original ID/content with bounded backoff/backpressure. Conflicting content under one ID is never silently accepted. Stop retrying non-retryable rejection as defined by P3. - Respect startup/shutdown, generation/session fencing, deadlines and pending-queue limits without blocking unrelated channel services. Document queue-full and disconnected publication behavior. - Baseline pending state may be in memory. Provider-controlled persistence is optional; document what a process crash can lose rather than promising durable delivery from stable installation identity alone. - Keep generated messages, gRPC streams, canonical envelope construction and secret redaction private. A trigger does not by itself prove a policy ran or a backup completed.  - Extend the reusable R11 Provider scenario catalogue with trigger-publication installed-runtime coverage using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket; do not substitute a simulated Agent transport.  ## Acceptance evidence  CI/CD evidence must include focused acknowledgement, replay, duplicate, conflict, backpressure, reconnect, and shutdown scenarios plus the unchanged full Provider matrix.  Test public publication and real stream transport, payload/ID rejection, accepted new/duplicate, lost-ack replay, content conflict, rejection retryability, bounded queue, disconnect/reconnect, optional-state limitations, shutdown, and the absence of generic source/target parameters. No human-facing author example requires protobuf or session/generation management.  ## Non-goals  No generic target/source/resource abstraction, Control Plane connection, policy executor, StateForge binding assignment, mandatory persistent Provider event log, or backup-only trigger taxonomy.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P3`, `R1`, `R11`, `R2` | `PENDING` | [Issue #24](https://github.com/stateforge-org/stateforge-provider-python/issues/24) |
| `R5` | `provider` | **[TASK][MVP] Implement Operation Admission and Idempotency**<br>## Outcome and ownership  Implement P4 admission and generic typed operation dispatch behind the public Provider framework. Providers can expose arbitrary declared operations; no backup/DR claim is required for ordinary operations.  ## Required behavior  - Provide compatible typed request/result models and async `@operation()` registration on Provider subclasses, reusing R1 facilities. Use landed `namespace/name@major` IDs, not legacy unversioned dotted examples; reject duplicate/invalid declarations and align derived schemas with the manifest. - Keep installation/session/generation, protobuf adaptation, fingerprints and registry management private. Provide a typed OperationContext carrying operation identity, deadline and approved execution context; extend it for P5 lifecycle in R6. - Validate active session, R2 readiness, declared operation/target and input schema before author behavior. Use P4's canonical fingerprint and atomic admission record before dispatch. Matching concurrent retries resolve one execution; changed content conflicts. - Return P4's successful dispositions and rejection statuses/reasons. Busy/invalid/deadline-before-admission requests create no accepted record. Terminal IDs are not repurposed; document bounded retention/expiry and lost-state limitations. - Default accepted-operation state is in memory; optional stronger persistence remains Provider-controlled. Delivery deduplication does not guarantee the vendor action is idempotent or justify retry after a process lost admitted state. - Validate author outputs and sanitize exceptions using the established lifecycle/error boundary; do not opportunistically implement full progress/Watch/cancellation or backup profiles in this step.  - Extend the reusable R11 Provider scenario catalogue with operation-admission installed-runtime coverage using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket; do not substitute a simulated Agent transport.  ## Acceptance evidence  CI/CD evidence must include focused admission, idempotency, concurrency, conflict, deadline, schema, and limit scenarios plus the unchanged full Provider matrix.  Cover a typed non-backup operation, schema derivation, duplicate registrations, invalid requests, readiness rejection, concurrency, identical lost-response retry, changed content, terminal replay/ID immutability, deadlines, safe exceptions, and expiry. Prove author examples require no gRPC/protobuf plumbing and dispatch occurs once per accepted identity.  ## Non-goals  No arbitrary shell-command API, vendor integration, mandatory persistent operation database, backup/DR requirement for generic operations, SF-AOP, or policy-run scheduling.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P4`, `R11`, `R2`, `R3` | `BLOCKED` | — |
| `R6` | `provider` | **[TASK][MVP] Implement Operation Progress Results and Cancellation**<br>## Outcome and ownership  Implement P5 generic operation progress, results, and cancellation behind Provider/OperationContext, extending R5's accepted registry rather than adding a second execution ledger.  ## Required behavior  - Enforce the contract's state transitions and one immutable terminal result. Validate typed result schemas; translate expected/unexpected author exceptions into sanitized structured errors with relevant side-effect/cleanup evidence. - Offer author progress reporting and cooperative cancellation state/checkpoints without exposing gRPC. Keep per-operation sequence monotonic and replay current/latest retained state on Watch attachment; Watch never dispatches an operation. - Bound progress retention and slow-watcher queues, coalesce only permitted progress, and preserve terminal replay while records are retained. Isolate concurrent operations/observers on the shared server. - Cancellation request and execution stopped are distinct. Handle unsupported and already-terminal outcomes; first terminal outcome wins races. Set CANCELLED only when actual author execution stopped according to the contract. - Watch cancellation, client deadline, transport loss and health changes do not implicitly stop business execution. Never kill the whole Provider process or unrelated tasks to cancel one operation. - Shutdown stops new admission, performs bounded graceful handling, and reports unresolved work honestly. Preserve R5 in-memory baseline and optional Provider persistence; no crash-proof result promise without evidence.  - Extend the reusable R11 Provider scenario catalogue with operation-lifecycle installed-runtime coverage using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket; do not substitute a simulated Agent transport.  ## Acceptance evidence  CI/CD evidence must include focused progress, replay, cancellation, terminal-race, invalid-result, interruption, and limit scenarios plus the unchanged full Provider matrix.  Exercise progress/terminal replay, late/slow/disconnected watchers, sequence/cursor behavior, invalid author results, sanitized failure, parallel operations, cancellation completion/races, unsupported/already-terminal cancellation, Watch-only cancellation, shutdown, and no redispatch. Update typed author examples and configured checks.  ## Non-goals  No unbounded history service, process-level force kill, invented operation states, backup-specific lifecycle implementation, or automatic remediation after unknown side effects.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P5`, `R11`, `R5` | `BLOCKED` | — |
| `R11` | `provider` | **[TASK][MVP] Build Reusable Provider Package and Runtime CI/CD Pipelines**<br>## Outcome and ownership  Create a reusable GitHub Actions ecosystem for building and validating the Provider Implementation package and its installed runtime. Package construction, dependency selection, public Provider fixtures, runtime lifecycle, SFP assertions, scenarios, and evidence collection are written once and composed by PR, integration, release-candidate, and future publication workflows. Test the public authoring surface and installed package; do not create a second runtime or execute from a source checkout.  ## Required behavior  - Build wheel and sdist once through a documented local command using canonical package metadata; record checksums and artifact/dependency provenance. - Organize focused composite actions under `.github/actions/` for package build, installed-package checks, Provider fixture creation, runtime start/stop, Bootstrap assertion, Manifest assertion, and evidence collection. Scenarios compose actions rather than growing one large action. - Provide reusable `workflow_call` workflows for artifact build, installed-package checks, runtime scenarios, and an aggregate gate. Thin PR/integration and manual release-candidate callers copy no environment or test logic. - Accept `protocol-ref`, defaulting to `mvp/implementation` while allowing an explicit ref or SHA. Record the resolved Protocol commit and artifact hash. - Install exact Provider and Protocol artifacts in clean environments outside both checkouts and without repository `PYTHONPATH`; prove package identity, import location, typed public API, descriptor/socket behavior, Bootstrap, Manifest, and clean shutdown. - Supply small declarative dummy Providers through the public API. Cover normal exchange/shutdown, concurrent distinct instances, same-instance replacement/generation, invalid peers, abrupt failure, restart, and uninstall/reinstall. Faults and evidence must be deterministic and bounded. - Separate platform-independent package/import checks from supported runtime checks. Do not imply Windows runtime support where Unix-domain sockets are required. - Pin external actions to immutable SHAs; keep permissions read-only, credentials absent, jobs bounded, caches dependency-keyed, and retention explicit. - Prefer action composition and existing commands. Add shell or Python only for reusable logic that cannot be expressed safely elsewhere; never duplicate runtime behavior in the harness.  ## Acceptance evidence  Validate action/workflow metadata; build wheel and sdist once; verify hashes/provenance; install exact artifacts outside the checkout; prove installed import origins and public authoring API; exercise valid Bootstrap/Manifest, multiple Providers, replacement, invalid peers, crash, restart, cleanup, uninstall, and reinstall; retain failure evidence. Pass Ruff, formatting, strict mypy, pytest/coverage, package build, installed-package checks, runtime scenario tiers, and strict docs.  ## Non-goals  No production Provider, new SFP semantics, Agent features, Control Plane integration, operation/trigger behavior, publication/signing, OS service package, cloud infrastructure, or organization-wide workflow repository.  ## Compatibility, discretion, and delivery  Preserve the public Provider framework, typed models, decorators, lifecycle hooks, internal SFP abstraction, landed Bootstrap/Manifest behavior, supported Python versions, and human Issue/PR/review/merge authority. Reusable workflows own job topology, composite actions own repeated runner steps, and the installed package plus public API remain the system under test. | `R1` | `COMPLETED` | [Issue #19](https://github.com/stateforge-org/stateforge-provider-python/issues/19) · [Pull Request #21](https://github.com/stateforge-org/stateforge-provider-python/pull/21) |
| `R9` | `provider` | **[TASK][MVP] Complete Provider Disconnection and Recovery**<br>## Outcome and ownership  Implement P8 Provider reconnect/state-reconciliation behavior by composing existing runtime identity, manifest, health, trigger and operation facilities.  ## Required behavior  - Separate channel loss from process death: accepted work may continue while the server process survives. Rebind new channels to validated handshake/session/generation before serving operational state. - Retain current operations/terminal results and pending trigger IDs/content for their documented in-process retention; replay existing state/results/acknowledgement work without redispatching author operations. - Keep installation identity/generation storage independent from execution persistence. Baseline process restart may lose operation/trigger state; optional Provider persistence may recover only verifiable records. - Return the contract's explicit indeterminate/lost/expired outcome for unresolved admitted identities. Never manufacture FAILED/SUCCEEDED, silently create a new record for reconciliation, or claim executions belonging to a replaced instance. - Fence stale sessions/watchers/acknowledgements, respect cursor gaps and backpressure, and coordinate bounded shutdown/restart. Remove only descriptor/socket/resources owned by the current generation. - Document exactly what survives transport interruption versus process restart and how callers detect limitations. Business/operator remediation belongs above SFP, not in the generic runtime.  - Extend the reusable R11 Provider scenario catalogue with deterministic disconnection and recovery scenarios using the exact Protocol wheel, Provider wheel, and built Agent RPM on Linux over the real Unix socket.  ## Acceptance evidence  CI/CD evidence must cover connection loss, generation replacement, Provider restart with retained or lost state, stale responses, expiry, and indeterminate outcomes without redispatch.  Cross-process scenarios cover lost admission reply, ongoing execution during transport loss, terminal replay, pending-trigger replay, generation replacement, stable-installation restart with state loss, new-instance replacement, stale stream responses, retention expiry, and supported optional persistence. Prove no author redispatch on reconciliation.  ## Non-goals  No mandatory persistent Provider registry, Agent reconnect manager, Control Plane remediation, automatic re-execution, or broader process-supervision redesign.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P8`, `R11`, `R4`, `R6` | `BLOCKED` | — |
| `R10` | `provider` | **[TASK][MVP] Verify the Complete Provider Runtime**<br>## Outcome and ownership  Verify the generic Provider framework/runtime against an independent Agent-side SFP test peer using installed contracts. The real Agent-daemon integration gate is A12.  ## Required behavior  - Run the reference Provider in a separate process through public `Provider.run()` and `serve()` paths. Exercise discovery/handshake, manifest, standard health, read-only capability assessment, triggers, arbitrary typed operation admission, progress/results/cancellation, and reconnect. - Prove Provider authors can expose unrelated namespaced operations with their own request/result models. The runtime must not recognize backup, restore, disaster recovery, BackupEngine, or other business-operation categories. - Exercise concurrent streams/operations and the safety matrix: lost replies/acknowledgements, duplicate/conflicting IDs, invalid author results, cancellation races, slow observers, deadlines, stale generations, restart, and indeterminate state. No scenario may silently redispatch unresolved work. - Verify authored models/decorators, hook lifecycle, schema derivation, generic `implements` declaration transport, and sanitized exceptions. Normal public examples must not require servicers, protobufs, descriptors, instance storage, or generation allocation. - Build wheel/sdist, verify packaged typing/resources and clean installed startup, and pass Ruff, strict mypy, pytest, package, and strict documentation gates. Use reusable Protocol conformance fixtures where available.  - Maintain a machine-checked coverage inventory mapping every implemented Provider SFP surface to its focused R11 scenario and full installed-runtime matrix; missing coverage is a release-blocking failure.  ## Acceptance evidence  CI/CD evidence must prove the exact Protocol wheel, Provider wheel, and Agent RPM pass the complete Linux/Unix-socket Provider matrix without replacing real peers with transport mocks.  Automated bounded subprocess coverage and a documented generic SFP coverage matrix. Include multiple unrelated operation schemas and prove the Provider runtime dispatches them without operation-specific branches. Report actual supported operating-system/runtime limits.  ## Non-goals  No production vendor Provider, Agent daemon, Agent workspace, BackupEngine, backup/DR workflow, SF-AOP/Control Plane, or unreviewed public API redesign.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose. Choose compatible implementation details from the current codebase and document tradeoffs for human review. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. | `R11`, `R2`, `R3`, `R4`, `R5`, `R6`, `R9` | `BLOCKED` | — |
| `A0` | `agent` | **[TASK][MVP] Implement SFP Discovery and Handshake Foundation**<br>Procedures 1 and 2, daemon lifecycle, channel reuse, and reconnection foundation. | `P0`, `R0` | `COMPLETED` | [Issue #1](https://github.com/stateforge-org/stateforge-agent/issues/1) · [Pull Request #2](https://github.com/stateforge-org/stateforge-agent/pull/2) |
| `A1` | `agent` | **[TASK][MVP] Integrate Provider Manifest Exchange**<br>## Outcome and ownership  Integrate the landed P1/R1 manifest exchange into the Agent's existing session manager/channel. See the Protocol manifest procedure and checked-in schema/revision conformance vector.  ## Required behavior  - Retrieve only after successful handshake with expected installation/generation, finite deadlines, bounded read retry and an explicit supported-schema offer. Accept only an offered/understood version and a complete atomic response. - Enforce current P1 ProtoJSON/schema rules, embedded local-reference validation, size/nesting bounds and safe secret handling. Preserve versioned string IDs, target kinds, role claims, requirements and explicit platform pairs. - Compute the exact schema-1 revision preimage `{manifest, manifestSchemaVersion, providerInstanceId}` using RFC 8785 with ProtoJSON defaults emitted. Exclude generation/revision, not installation identity; do not substitute deterministic protobuf bytes or older DOCX hashing rules. - Cache only validated declarations under installation/SFP version/schema/revision. Reuse an unchanged declaration without merging unvalidated fields, but always check current generation/session. A digest is a change detector, not authentication. - Invalid/incompatible manifest blocks operational use independently of healthy transport. Replace valid changed declarations atomically and invalidate dependent local decisions; stale responses cannot activate a superseded session. - Transport/session connection state is not full operational availability. Compose with the upcoming A2 health gate rather than treating bootstrap success alone as sufficient. Preserve existing connection replacement behavior.  ## Acceptance evidence  Test a real manifest peer, conformance hash, unchanged cache reuse, changed/new-installation revision, complete-response validation, bad header/digest/schema/reference, offered-version mismatch, limits/secrets, stale generation, transport retry and invalid-manifest gating. Ensure no extra channel or vendor-specific interpretation.  ## Non-goals  No modification of locked P1/R1, new schema-1 fields, health implementation, capability/admission dispatch, mandatory inventory redesign, SF-AOP or Control Plane reporting.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `P1`, `R1` | `COMPLETED` | [Issue #8](https://github.com/stateforge-org/stateforge-agent/issues/8) · [Pull Request #9](https://github.com/stateforge-org/stateforge-agent/pull/9) |
| `A2` | `agent` | **[TASK][MVP] Integrate Provider Health and Availability Monitoring**<br>## Outcome and ownership  Watch standard `grpc.health.v1` on the current Agent-established Provider channel and maintain coherent local operational eligibility with A1's manifest acceptance.  ## Required behavior  - Watch the proper versioned operational service on the existing channel; Check is diagnostic. Initial/unknown/NOT_SERVING states block new operation admission. - Availability requires current transport, validated handshake/session/generation, compatible valid manifest, and SERVING health. Keep connection state and eligibility distinguishable using existing state boundaries, not parallel unsynchronized ledgers. - On Watch end/failure, mark health unknown/unavailable and stop new admission while reconnect/Watch retry is bounded. Resume only after current-session prerequisites are valid again. - Fence stale Watch updates after generation replacement, manifest rejection or shutdown. Changes affect new-work eligibility, not the truth of already admitted operations or their terminal results. - Expose local status/reasons for diagnostics and later internal consumers without inventing Control Plane reporting. Do not embed vendor-specific health probes.  - Extend the reusable A13 installed-Agent scenario catalogue with health and eligibility coverage using the exact Agent RPM, Protocol wheel, and Provider wheel in separate real processes over the Unix socket.  ## Acceptance evidence  CI/CD evidence must include focused health/eligibility scenarios in pull requests and the unchanged full installed-Agent matrix.  Exercise initial replay, SERVING/NOT_SERVING, unknown service, Watch loss/recovery, invalid manifest despite SERVING, generation replacement/stale update, concurrent channel streams, and shutdown. Verify readiness transitions are coherent and admitted work is not automatically cancelled by health loss.  ## Non-goals  No custom health protobuf, second channel, remote Control Plane status, business-operation retry/cancellation, or wholesale replacement of landed session-management APIs.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `A1`, `A13`, `P6`, `R2` | `COMPLETED` | [Issue #16](https://github.com/stateforge-org/stateforge-agent/issues/16) · [Pull Request #20](https://github.com/stateforge-org/stateforge-agent/pull/20) |
| `A3` | `agent` | **[TASK][MVP] Integrate Provider Capability Assessment**<br>## Outcome and ownership  Consume locked P2/R3 capability assessment using only normalized SFP data, A1 declarations and A2 current eligibility. Preserve P2's issued contract/requirements.  ## Required behavior  - Validate current session/generation, declared versioned operation/target kind and bounded request/context before a finite read-only RPC. Reject unsupported declarations locally without assuming vendor knowledge. - Normalize/correlate the contract's per-operation support, requirements, reasons and assessment identity. Preserve SUPPORTED_WITH_REQUIREMENTS, UNSUPPORTED and INDETERMINATE distinctions; negative support is a domain finding, not successful eligibility. - A manifest advertises potential support, not current target compatibility or satisfied runtime prerequisites. Unknown requirements remain unresolved; do not infer Backup/DR compliance from operation names, capability findings, or operation-specific result shapes. - Any reusable assessment is bound to the relevant target/context and active declaration/session; invalidate stale decisions when identity/generation/manifest changes. Read-only retry may inspect a newer state and does not authorize business execution. - Surface temporary unavailability, malformed responses, deadline/transport errors and sanitized reasons distinctly. Keep a clean internal boundary for later authorized dispatch, not a policy interpreter.  - Extend the reusable A13 installed-Agent scenario catalogue with capability-assessment coverage using the exact Agent RPM, Protocol wheel, and Provider wheel in separate real processes over the Unix socket.  ## Acceptance evidence  CI/CD evidence must include focused capability normalization, rejection, timeout, stale-session, malformed-response, and limit scenarios plus the unchanged full installed-Agent matrix.  Cover generic non-backup and profile-related assessment, all support findings, unmet/unknown prerequisites, invalid/undeclared IDs/kinds, malformed/correlation-mismatched reply, readiness gate, stale cache/context, changed generation/manifest and read-only retry. Verify no target mutation or Provider/vendor imports.  ## Non-goals  No P2 redesign, operation dispatch, StateForge component assignment, policy selection, Control Plane connection or universal vendor requirement evaluator.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `A1`, `A13`, `A2`, `P2`, `R3` | `BLOCKED` | — |
| `A4` | `agent` | **[TASK][MVP] Integrate Trigger Publication and Acknowledgement**<br>## Outcome and ownership  Receive P3/R4 Provider triggers, durably accept delivery responsibility, deduplicate, and acknowledge on the existing SFP stream. Keep an internal forwarding boundary for the later SF-AOP phase.  ## Required behavior  - Validate the authenticated Provider/session/generation, declared versioned trigger, schema-bound payload, stable publication ID, canonical content equality, and limits. SFP has no generic target/source/resource identity; any trigger-specific resource/source identity remains payload data and is not interpreted as a StateForge project/component assignment. - Commit an accepted event and Agent-owned responsibility state durably before ACCEPTED_NEW. A matching replay returns ACCEPTED_DUPLICATE without duplicate logical delivery; same ID/different semantic content rejects as a conflict. - Acknowledgement loss and Agent restart must recover the accepted event/responsibility without forcing a new ID or dropping it silently. A local durable acceptance is not proof that the Control Plane processed it, and downstream handoff is not part of the P3 wire acknowledgement. - Retain a bounded, recoverable pending-forward boundary with explicit queue-full/backpressure, rejection/retryability and retention behavior. Until SF-AOP exists, retain accepted events rather than pretending remote forwarding succeeded. - Fence stale streams/acks and handle reconnect/shutdown without acknowledging uncommitted work. Keep persistence implementation aligned with the current Agent; no prescribed database engine or new transport architecture. - This Provider-originated SFP route remains distinct from any legacy application/developer local-trigger interface; avoid conflating their identifiers or permissions.  - Extend the reusable A13 installed-Agent scenario catalogue with trigger-publication coverage using the exact Agent RPM, Protocol wheel, and Provider wheel in separate real processes over the Unix socket.  ## Acceptance evidence  CI/CD evidence must include focused responsibility-transfer, acknowledgement-loss, replay, duplicate, conflict, backpressure, and reconnect scenarios plus the unchanged full installed-Agent matrix.  Test valid/invalid publication, commit-before-ack, crash before commit/after commit-before-ack, lost acknowledgement, durable restart, matching duplicate, conflicting content, queue pressure, reconnect, stale generation, absent downstream transport, and the absence of generic source/target handling. Prove one retained logical event and honest forwarding status.  ## Non-goals  No generic target/source/resource abstraction, SF-AOP wire protocol, Control Plane policy evaluation/component mapping, legacy Local API redesign, or exactly-once policy execution claim.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `A1`, `A13`, `A2`, `P3`, `R4` | `BLOCKED` | — |
| `A5` | `agent` | **[TASK][MVP] Integrate Operation Admission and Idempotency**<br>## Outcome and ownership  Submit immutable P4/R5 generic operations behind the Agent's local coordination boundary using active declarations, A2 readiness and A3 findings. Do not select policy business actions here.  ## Required behavior  - Allocate an operation ID before contact; keep the versioned identifier, target, schema-valid payload, deadline and authorized execution context immutable for that attempt. Track attempted/accepted/rejected/unresolved state using current Agent persistence patterns where recovery requires it. - Validate manifest declaration and relevant requirements/explicit profiles, current session/generation and readiness before submission. An arbitrary operation remains usable without Backup/DR compliance; an operation identifier is not an arbitrary shell command. - Handle ACCEPTED_NEW and RESOLVED_EXISTING, terminal resolution and structured rejection exactly as P4. Rejection does not create a successful execution; busy retry guidance does not authorize changing the request under the same ID. - A lost response uses the same semantic request/ID to resolve retained Provider state. Do not create a fresh ID because transport failed; retain uncertainty when admission/external effects cannot be established. - Keep delivery deduplication separate from vendor-action idempotency. Document retention/expiry and safe-retry boundaries; unresolved admitted work cannot be automatically repeated after Provider state loss. - Fence stale replies/session replacement and prevent concurrent local submissions from becoming duplicate attempts. Keep an internal authority/context boundary ready for future SF-AOP commands without designing that protocol.  - Extend the reusable A13 installed-Agent scenario catalogue with operation-admission coverage using the exact Agent RPM, Protocol wheel, and Provider wheel in separate real processes over the Unix socket.  ## Acceptance evidence  CI/CD evidence must include focused admission, idempotency, concurrency, conflict, deadline, schema, and limit scenarios plus the unchanged full installed-Agent matrix.  Test a generic non-backup invocation, invalid/undeclared input, readiness/requirement rejection, successful new/replayed/terminal admission, changed-request conflict, lost-response resolution, concurrent submission, deadline-before-admission, stale generation and retention/state-loss uncertainty. Prove no new execution identity is silently substituted.  ## Non-goals  No policy engine, vendor code, automatic remediation/new attempt, SF-AOP schema, full lifecycle Watch implementation or BackupEngine invocation.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `A13`, `A2`, `A3`, `P4`, `R5` | `BLOCKED` | — |
| `A6` | `agent` | **[TASK][MVP] Integrate Operation Progress Results and Cancellation**<br>## Outcome and ownership  Observe P5/R6 admitted operations, normalize progress/results, and request race-safe operation-scoped cancellation without redispatch.  ## Required behavior  - Attach Watch only to known admitted identities; consume current-state/latest-progress replay, monotonic sequences and contract cursor/gap rules. Bound local buffering and fence stale responses from replaced sessions. - Validate typed terminal results against pinned declaration/profile context and accept one immutable terminal outcome. Preserve structured failure/partial-side-effect/cleanup evidence and sanitized diagnostics. - Request cancellation using the contract, distinguishing accepted/requested, unsupported and already-terminal. Record CANCELLED only after confirmed execution stopped; a successful request or RPC deadline is not confirmation. - Completion/cancellation races resolve to the first valid terminal outcome. Cancelling an observer, disconnecting, health loss or timeout does not fabricate FAILED/CANCELLED or stop unrelated work on the channel. - Persist/retain the evidence needed to reconcile outstanding attempts using current Agent facilities. Resume observation after interruption without resubmitting business work; P8/A11 provide complete state-loss reconciliation later. - Expose normalized local operation status through a clean coordination boundary, not direct vendor hooks or invented Control Plane reporting.  - Extend the reusable A13 installed-Agent scenario catalogue with operation-lifecycle coverage using the exact Agent RPM, Protocol wheel, and Provider wheel in separate real processes over the Unix socket.  ## Acceptance evidence  CI/CD evidence must include focused progress, replay, cancellation, terminal-race, interruption, restart-of-observation, and no-redispatch scenarios plus the unchanged full installed-Agent matrix.  Test initial/late/terminal replay, progress coalescing/gaps, slow observer, invalid result/correlation, terminal immutability, cancellation races, unsupported/already-terminal cases, interrupted Watch, stale session, partial effects and Agent restart of observation. Prove Watch and cancellation never cause a second dispatch.  ## Non-goals  No unlimited event-history system, process-wide cancellation, guessed rollback, generic auto-retry of side effects, policy executor or SF-AOP transport.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `A13`, `A5`, `P5`, `R6` | `BLOCKED` | — |
| `A7` | `agent` | **[TASK][MVP] Implement Agent-Managed Backup Workspaces**<br>## Outcome and ownership  Implement protected Agent-owned workspaces used as BackupEngine sources and restore destinations. Workspaces are Agent tooling, not SFP resources or Provider-owned storage.  ## Required behavior  - Allocate scoped source/restore workspace identities and paths with safe permissions, quotas, lifetime, ownership, and crash-recovery cleanup state. Reject traversal, unsafe symlink escape, and access outside authorized roots. - Let an Agent workflow expose an authorized workspace path to an ordinary Provider operation only through that operation's declared payload when configured. SFP treats the payload as operation data and assigns no backup meaning to it. - Support engine-only workflows where the managed entity needs no Provider preparation or native backup/restore API. A Provider preparation or post-restore operation is optional workflow behavior, not a prerequisite for using a BackupEngine. - Keep workspaces alive while an operation or BackupEngine still owns them. Cleanup may remove only Agent-owned workspace resources after all consumers release them. - Record enough local provenance and lifecycle state to associate later engine results with the selected source/destination without turning an ordinary Provider response into standardized backup evidence. - Keep repository credentials and BackupEngine configuration out of Provider payloads, SFP metadata, and workspace-visible files unless an engine-specific secure mechanism explicitly requires them.  - Extend the reusable A13 installed-Agent scenario catalogue with workspace security and lifecycle coverage against the exact installed Agent RPM, including deterministic filesystem faults and bounded retained evidence.  ## Acceptance evidence  CI/CD evidence must cover isolation, traversal and symlink escape, permissions, quotas, concurrency, interruption, ownership transfer, retention, and cleanup.  Test allocation, isolation, paths with spaces, traversal/symlink escape, permissions, quotas, concurrent workspaces, lifecycle handoff, cancellation, Agent interruption/recovery, in-use retention, and safe cleanup. Demonstrate both an engine-only workspace and a workspace path passed through an ordinary test operation payload.  ## Non-goals  No Protocol backup/DR contract, predefined operation identifier/schema/role, BackupEngine implementation, Restic adapter, Control Plane Snapshot, policy scheduling, or arbitrary filesystem deletion.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose. Choose compatible implementation details from the current codebase and document tradeoffs for human review. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. | `A13`, `A6` | `BLOCKED` | — |
| `A8` | `agent` | **[TASK][MVP] Implement the BackupEngine Extension Layer**<br>## Outcome and ownership  Implement a typed, stable in-process Agent BackupEngine extension layer over A7 workspaces. Engines are Agent tools/plugins, never Providers, operations, or SFP peers.  ## Required behavior  - Discover engines through documented Python entry points and validate plugin identity, version, capabilities, and configuration. Keep plugin packaging independent from the Agent distribution and runtime construction explicit. - Define normalized create, restore, verify, inspect, and remove behavior with typed handles/results, finite deadlines, cooperative cancellation, bounded progress, errors, and cleanup ownership. Choose exact Python signatures from current Agent patterns and document them. - Create backups only from authorized Agent-selected sources/workspaces and restore only into authorized destinations/workspaces. The engine must not require the managed entity or its Provider to expose a native backup/restore operation. - Keep repository credentials/configuration inside the Agent/engine boundary and redact them from SFP, Provider operation payloads/results, CLI output, logs, and public diagnostics. - Make unsupported operation, capability, version, and configuration failures explicit before unsafe work. Isolate plugin failure without corrupting workspace ownership or durable backup evidence. - Distinguish a successful physical engine backup from any optional Provider preparation operation and from a future coordinated Control Plane Snapshot.  - Extend the reusable A13 installed-Agent scenario catalogue with an independently packaged test BackupEngine, exercising installed-plugin discovery and deterministic lifecycle, compatibility, cancellation, failure, and credential-redaction cases.  ## Acceptance evidence  CI/CD evidence must prove the exact Agent RPM discovers and isolates the packaged engine while preserving workspace ownership and the existing installed-Agent matrix.  Use an independently packaged test engine to exercise discovery, capabilities, create/restore/verify/inspect/remove, invalid/missing/duplicate plugin, incompatible version/configuration, errors, deadlines, cancellation, scoped paths/handles, credential redaction, concurrent isolation, and an entity with no native backup API. Verify installed-package discovery and configured gates.  ## Non-goals  No BackupEngine RPC, Provider-side storage code, Protocol backup schema, concrete Restic adapter, vendor Provider, Control Plane retention scheduler, or mandatory native-language migration.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Choose compatible implementation details from the current codebase and document tradeoffs for human review. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. | `A13`, `A7` | `BLOCKED` | — |
| `A13` | `agent` | **[TASK][MVP] Build Reusable Agent RPM CI/CD Pipelines**<br>## Outcome and ownership  Create reusable GitHub Actions building blocks for the StateForge Agent RPM. Build and test logic is written once and reused by pull-request, pre-publication, and future publishing workflows. The implementation may combine YAML with Bash or Python where each is appropriate; it must not introduce a separate scenario framework or duplicate the Agent runtime.  ## Required behavior  - Keep RPM construction in one documented, locally runnable command that uses the canonical RPM spec and produces the binary RPM, source RPM, checksums, and machine-readable build metadata. - Expose that command through a repository-local composite action with typed inputs and outputs, including version, artifact paths, and binary RPM SHA-256. - Provide a reusable `workflow_call` build workflow that builds once and uploads the immutable RPM artifact. Downstream testing and future publication must consume those exact bytes rather than rebuild. - Provide a reusable installed-RPM test action and workflow that download the artifact, verify checksums, install the binary RPM in clean supported Linux, verify package identity, files, ownership, import location, packaged service/configuration surface, and removal, and upload bounded evidence even on failure. - Provide a reusable gate that composes build then installed-package verification, plus thin pull-request/integration and manual release-candidate callers containing no copied setup or build commands. - Keep external actions pinned to immutable commit SHAs, permissions read-only, credentials out of build/test jobs, jobs bounded, and artifact retention explicit. - Keep shell commands independently runnable for local parity and document how later runtime tests and publishers consume the tested RPM artifact. - Be explicit about current packaging boundaries: until runtime dependencies are distributed as system packages, the packaging gate may verify artifact-owned surfaces without claiming the full daemon can start.  ## Acceptance evidence  Run workflow/action validation; build the binary and source RPM on Linux; verify checksums and metadata; install the exact binary RPM in a clean Fedora environment; prove executable, Python package, systemd unit, configuration, sysusers, and tmpfiles content are owned by the RPM and not a checkout; remove the RPM; and retain evidence. Pass shell syntax checks, focused automation contract tests, Ruff, strict mypy, the existing Linux test suite, and strict documentation build.  ## Non-goals  No custom system-test framework, scenario DSL, dummy Provider suite, full runtime/service integration matrix, package signing/publication, organization-wide workflow repository, cloud infrastructure, or new Agent/SFP behavior.  ## Compatibility, discretion, and delivery  Preserve landed Agent behavior, existing repository checks, RPM layout, and human Issue/PR/review/merge authority. Prefer reusable workflows for job topology, composite actions for repeated runner steps, and small shell/Python commands for portable implementation details. | `A1` | `COMPLETED` | [Issue #10](https://github.com/stateforge-org/stateforge-agent/issues/10) · [Pull Request #11](https://github.com/stateforge-org/stateforge-agent/pull/11) |
| `A9` | `agent` | **[TASK][MVP] Implement ResticBackupEngine**<br>## Outcome and ownership  Implement `ResticBackupEngine` through A8's Agent-only extension contract. It provides physical backup and restoration for Agent-authorized data independently of Provider vendor behavior or native backup support.  ## Required behavior  - Resolve an explicit trusted executable and validate the supported Restic version/capabilities. Build argument arrays without a shell; validate configuration and prevent executable/argument injection. - Keep repository credentials in controlled environment/files/input according to supported Restic interfaces, never command-line arguments, SFP, Provider payloads/results, or logs. Bound output, redact diagnostics, parse machine-readable output, and validate normalized handles/results. - Implement create from an authorized A7 source, restore into an authorized A7 destination, inspect, verify, and removal of an explicitly authorized engine-owned snapshot. - Preserve durable backup identity, provenance, and integrity evidence only after storage success. Never convert partial/nonzero-exit work into successful backup evidence. - Honor finite deadlines and cooperative/process-scoped cancellation with bounded subprocess termination/reaping and honest partial-effect reporting. Never terminate the Agent or unrelated engine work. - Support clean plugin packaging/configuration and diagnose a missing binary or incompatible version safely.  - Extend the reusable A13 installed-Agent scenario catalogue with bounded real-Restic tests against the exact Agent RPM and packaged engine, using disposable repositories and deterministic failure injection.  ## Acceptance evidence  CI/CD evidence must include create, inspect, verify, restore, remove, corruption, interruption, concurrency, credential-redaction, and cleanup cases.  Automated fixture/subprocess tests plus a bounded real-Restic local-repository create/inspect/verify/restore/remove round trip. Cover paths with spaces, no-shell execution, malformed output/nonzero exit, credential/log redaction, corrupt/missing backup, unauthorized handle/path, timeout/cancellation, concurrency, and an engine-only backup with no Provider operation.  ## Non-goals  No Restic service/RPC, Provider operation or vendor consistency logic, automatic retention/prune scheduler, unconstrained repository deletion, cloud credential provisioning, or platform-wide Snapshot coordination.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Choose compatible implementation details from the current codebase and document tradeoffs for human review. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. | `A13`, `A8` | `BLOCKED` | — |
| `A10` | `agent` | **[TASK][MVP] Integrate Agent Backup and Restore Orchestration**<br>## Outcome and ownership  Compose Agent-owned BackupEngine work with optional ordinary Provider operations. The Agent performs physical backup/restore; Providers only execute explicitly configured generic operations through SFP.  ## Required behavior  - Implement a local orchestration boundary that can create an engine backup from an authorized source and restore it to an authorized destination without requiring any Provider-native backup or restore feature. - Allow workflow configuration to invoke an ordinary declared Provider operation before backup, after backup, before restore, or after restore when the managed system needs quiesce, export, resume, import, reload, reconstruction, or verification behavior. - Send those calls through normal P4/P5 operation admission/lifecycle using each operation's own identifier and typed payload/result schema. The Agent and SFP must not recognize a predefined backup/DR role, operation name, payload, or result. - When configured, allocate an A7 workspace and place its authorized path and operation-specific data in the ordinary operation payload. The Agent already owns the path; it does not discover a standardized backup source from the Provider response. - Keep BackupEngine handles, repository credentials, physical storage results, and integrity checks inside the Agent. Validate restored data before any configured Provider post-restore operation and retain staging until all consumers release it. - Preserve immutable invocation identity, cancellation, deadlines, partial effects, and indeterminate outcomes. Do not automatically repeat a Provider operation or engine action after an ambiguous result.  - Extend the reusable A13 installed-Agent scenario catalogue with backup-orchestration scenarios using the exact Agent RPM and packaged engine; flows involving Provider operations must use the exact Provider and Protocol wheels in a separate real process over the Unix socket.  ## Acceptance evidence  CI/CD evidence must cover engine-only, prepare-then-create, restore-then-consume, failure, cancellation, ambiguous outcomes, workspace lifetime, credential isolation, and no duplicated side effects.  Test an engine-only create/restore flow for an entity with no native backup API; a prepare-operation-to-engine-create flow; and an engine-restore-to-ordinary-Provider-operation flow. Cover corrupt data, operation rejection/failure, engine failure, cancellation, lost results, workspace lifetime, cleanup, credential isolation, and no duplicated side effects.  ## Non-goals  No Protocol backup/DR contract, Provider compliance layer, hard-coded operation catalogue, vendor-specific Agent code, Control Plane policy selection/Snapshot coordinator, or automatic retry after uncertainty.  ## Compatibility, discretion, and delivery  Preserve landed generic SFP contracts and repository boundaries. Choose orchestration interfaces from current Agent patterns so later SF-AOP/Control Plane plans can authorize the same local actions without redefining SFP. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. | `A13`, `A6`, `A9`, `R6` | `BLOCKED` | — |
| `A11` | `agent` | **[TASK][MVP] Complete SFP Disconnection and Recovery**<br>## Outcome and ownership  Complete Agent P8/R9 recovery by composing session replacement, manifest validation, health eligibility, durable triggers and admitted-operation evidence.  ## Required behavior  - Distinguish transport interruption, same-installation new generation/process, and replacement installation. Rediscovers/re-handshakes use current identity/generation; retrieve or validate manifest and establish health before new admission. - Reconcile prior operations with original IDs through existing query/Watch semantics; replay retained progress/terminal evidence without redispatch. Retry pending trigger delivery/ack responsibility with original publication IDs and content. - Agent restart recovers its required journals/evidence and resumes responsibility; stable Provider installation identity alone is not proof the Provider retained execution state. - Missing/expired previously admitted records become explicit indeterminate outcomes. Never mark them failed/cancelled/succeeded by inference, manufacture a new ID, or automatically repeat an action with possibly completed side effects. - Replacement instances cannot inherit earlier executions. Fence stale session responses, old health/watch streams, changed manifest decisions and cursor gaps; preserve bounded backoff/backpressure and shutdown behavior. - Surface pending/indeterminate/cleanup evidence for later authority or human resolution through an internal boundary. Choose durable implementation from current Agent patterns; do not invent SF-AOP remediation messages.  - Extend the reusable A13 installed-Agent scenario catalogue with deterministic disconnection and recovery coverage using exact artifacts and separate real Agent and Provider processes over the Unix socket.  ## Acceptance evidence  CI/CD evidence must cover channel loss, lost replies and acknowledgements, generation replacement, Agent and Provider restart, retained and lost state, stale responses, expiry, and indeterminate outcomes without redispatch.  Automated scenarios cover channel loss with continuing work, lost admission reply/result/trigger ack, generation replacement, Agent restart, Provider restart with/without supported retained state, new installation, stale responses, expiry and workspace ownership. Prove each accepted execution/event is reconciled, not blindly repeated or dropped.  ## Non-goals  No compulsory Provider persistence, automatic business retry/remediation, Control Plane operator workflow, new SF-AOP contract or unrelated connection-manager redesign.  ## Compatibility, discretion, and delivery  Preserve landed contracts, public APIs, and repository boundaries. Current code wins existing disagreements with prose; SFP defines intended behavior not yet implemented. In particular, preserve P1 manifest schema 1, versioned string identifiers, explicit `implements` roles, and its revision rules. New incompatible semantics require explicit versioning, not a silent v1 rewrite.  Choose internal storage, scheduling, helper APIs, and compatible implementation details from the current codebase; document tradeoffs for human review. Loose specifications are guidance, not permission for unrelated redesign. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. SF-AOP and Control Plane are required later MVP phases, not work to invent here. | `A13`, `A4`, `A6`, `P8`, `R9` | `BLOCKED` | — |
| `A12` | `agent` | **[TASK][MVP] Verify the Complete Local Agent and Provider Runtime**<br>## Outcome and ownership  Verify the complete local Agent/Provider foundation using separate real processes plus an installed BackupEngine/Restic plugin. Prove generic SFP and Agent-owned backup tooling compose without adding backup semantics to the Protocol or Provider runtime.  ## Required behavior  - Exercise discovery/identity/handshake, manifest validation/revision caching, standard health, capability assessment, durable triggers, arbitrary typed operation admission, progress/results/cancellation, and reconnect over one multiplexed channel per active endpoint. - Demonstrate multiple unrelated Provider operations whose payload/result schemas are opaque to SFP. No test may require a predefined backup/DR operation identifier, compliance role, Protocol backup schema, or Provider knowledge of BackupEngine. - Exercise an engine-only physical backup/restore for an entity with no native backup API. Also exercise an optional ordinary Provider preparation operation before engine create and an optional ordinary Provider consume/reload operation after engine restore. - Cover concurrency and failure/crash boundaries: duplicate/conflicting IDs, lost replies/acknowledgements, invalid schemas/results, readiness changes, stale generations, cancellation races, corrupt storage, process restarts, indeterminate state, and scoped cleanup. Do not automatically repeat unresolved effects. - Verify local backup identity/provenance, engine integrity evidence, operation evidence, and workspace ownership remain distinct and available through clean internal coordination boundaries. Do not claim local physical backups are already coordinated Control Plane Snapshots. - Build and clean-install involved distributions, verify packaged contracts/typing/plugin resources/public docs, and pass all applicable gates on the supported runtime/platform matrix.  - Maintain a machine-checked coverage inventory mapping every planned SFP and Agent-owned backup capability to focused scenarios and the full installed-artifact matrix; missing coverage is a release-blocking failure.  ## Acceptance evidence  CI/CD evidence must prove the exact Protocol wheel, Provider wheel, Agent RPM, test BackupEngine package, and Restic integration pass the complete supported Linux runtime matrix.  A repeatable automated real-process matrix proves generic SFP interoperability, engine-only backup/restore, optional Provider-operation choreography, credential isolation, and honest recovery from uncertainty. Record the local phase exit evidence and open questions for the later required SF-AOP and Control Plane phases.  ## Non-goals  No SF-AOP/Control Plane implementation, Protocol backup/DR profile, fabricated global consistency guarantee, vendor-specific Agent code, production policy engine, or broad architecture migration.  ## Compatibility, discretion, and delivery  Preserve landed generic contracts and repository boundaries. Current code wins existing disagreements with prose. Implement only the assigned Issue. Add behavioral tests and applicable repository checks/docs. Scoped local commits are allowed; a human pushes, opens the PR, reviews, and merges. Only matching merged GitHub evidence reconciled by DPT completes this step. | `A10`, `A11`, `A13`, `A2`, `A3`, `A4`, `A5`, `A6`, `A7`, `A8`, `A9`, `P9`, `R10` | `BLOCKED` | — |
| `P11` | `protocol` | **[TASK][MVP] Add Versioned Provider Views to Manifest-Declared Operations and Triggers**<br>Extend the existing Provider Manifest Exchange contract so manifest-declared operations and triggers can carry safe declarative presentation metadata and reference bounded, content-addressed Provider-owned assets. Keep presentation revisioning separate from operational contract revisioning so visual-only changes do not alter execution semantics, invalidate operation admission, or disrupt trigger streams. Operation Admission and Trigger Publication continue to use their existing endpoints and identifiers, resolve views through the accepted declaration snapshot, and gain documentation and conformance coverage without new RPC services. Define strict formats, limits, digest validation, reference integrity, and safe fallback behavior; prohibit executable frontend code and unrestricted remote resources. | `P1`, `P10`, `P3`, `P4` | `READY` | — |
| `R12` | `provider` | **[TASK][MVP] Add Declarative Operation and Trigger Views to the Provider Python DSL**<br>Provide typed Python authoring constructs that let Provider developers attach declarative views directly to operation and trigger declarations. The DSL must produce the Protocol-owned presentation model without requiring authors to construct protobuf messages, preserve static typing and inherited declaration behavior, validate references deterministically, and expose no arbitrary HTML, CSS, JavaScript, or executable frontend extension point. | `P11`, `R1`, `R11`, `R4`, `R5` | `BLOCKED` | — |
| `R13` | `provider` | **[TASK][MVP] Package Provider-Owned Icons, Images, and Presentation Assets**<br>Allow Provider packages to ship the icons, logos, illustrations, diagrams, images, SVG resources, and other bounded static visual assets referenced by their declarative operation and trigger views. Discover and package assets reproducibly, calculate content digests, validate media types, dimensions and size limits, reject traversal, symlink, malformed, executable, and remote-resource hazards, and deduplicate identical content without exposing arbitrary Provider filesystem paths. | `P11`, `R11`, `R12` | `BLOCKED` | — |
| `R14` | `provider` | **[TASK][MVP] Publish Versioned Provider Views through Manifest Exchange**<br>Integrate Provider-authored operation views, trigger views, and validated asset references into the existing manifest construction and GetManifest response. Produce deterministic presentation revisions and canonical output while preserving the independent operational manifest revision and all existing session, schema-negotiation, size, and stale-response fences. Presentation-only changes must be observable without changing operation or trigger execution contracts and must not require another SFP endpoint. | `P11`, `R1`, `R11`, `R12`, `R13` | `BLOCKED` | — |
| `R15` | `provider` | **[TASK][MVP] Verify Provider View Declarations, Assets, and Revision Semantics**<br>Add conformance and installed-package coverage for operation and trigger view authoring, safe fallback declarations, asset packaging and rejection, deterministic content digests, canonical presentation revisions, and manifest publication. Prove that a presentation-only edit changes the presentation revision without changing the operational manifest revision or affecting existing operation-admission and trigger-publication behavior, and preserve evidence through the reusable Provider CI/CD framework. | `P11`, `R11`, `R12`, `R13`, `R14` | `BLOCKED` | — |

## Milestone context contracts

### `P0` — [TASK][MVP] Define SFP Handshake and Version Negotiation

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `agent/tests` | `must_understand` | `canonical` | Yes | Read all tests |

#### Verification contract

- **test** · `agent` · `test` — test

### `P1` — [TASK][MVP] Define Provider Manifest Exchange Contract

_No implementation context has been declared yet._

#### Verification contract

- **test** · `agent` · `ls -al` — Listing of files

### `P2` — [TASK][MVP] Define Capability Assessment Contract

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `P3` — [TASK][MVP] Define Trigger Publication and Acknowledgement Contract

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `P4` — [TASK][MVP] Define Operation Admission and Idempotency Contract

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `P5` — [TASK][MVP] Define Operation Progress Results and Cancellation Contract

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `P6` — [TASK][MVP] Define Provider Health and Operational Eligibility Contract

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `protocol/.agents/skills` | `must_understand` | `canonical` | Yes | DPT milestone workflow and agent handoff requirements. |
| `protocol/.claude/skills` | `must_understand` | `canonical` | Yes | Protocol, Python, and PR-review engineering instructions. |
| `protocol/docs/procedures/health.md` | `expected_to_change` | `canonical` | Yes | Existing health overview that must become the normative client-facing procedure. |
| `protocol/docs/assets/diagrams/health-and-availability-monitoring.png` | `expected_to_change` | `canonical` | Yes | Existing cross-runtime sequence diagram that must match the completed contract. |
| `protocol/docs/procedures/provider-manifest.md` | `must_understand` | `canonical` | Yes | Accepted manifest semantics that combine with service health to determine Agent eligibility. |
| `protocol/AGENTS.md` | `must_preserve` | `canonical` | Yes | Repository-wide protocol development and delivery rules. |

#### Verification contract

- **lint** · `protocol` · `buf lint` — Keep the complete Protocol source tree valid even though this contract adds no custom health protobuf.
- **test** · `protocol` · `.venv/bin/ruff check . && .venv/bin/mypy && .venv/bin/pytest` — Preserve all configured Python, typing, and behavioral gates.
- **command** · `protocol` · `.venv/bin/mkdocs build --strict` — Prove the normative procedure and diagram render without documentation errors.
- **command** · `protocol` · `.venv/bin/python -m build` — Verify the distributable Protocol package remains buildable and unchanged health semantics introduce no packaging regression.
- **human** · `protocol` · `GitHub Review` — A human verifies ownership boundaries, standard gRPC Health usage, lifecycle semantics, and cross-runtime clarity before merge.

### `P10` — [TASK][MVP] Build Reusable Protocol Package and Contract CI/CD Pipelines

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `protocol/AGENTS.md` | `must_preserve` | `canonical` | Yes | Preserve the Protocol repository boundary, generated-plan discipline, and human delivery authority. |
| `protocol/pyproject.toml` | `must_understand` | `canonical` | Yes | Defines the package, supported Python versions, dependencies, and quality gates. |
| `protocol/buf.yaml` | `must_verify` | `canonical` | Yes | Canonical protobuf lint and module configuration must drive CI validation. |
| `protocol/buf.gen.yaml` | `must_verify` | `canonical` | Yes | Canonical generation configuration must remain the source of generated bindings. |
| `protocol/scripts/check_generated.py` | `expected_to_change` | `canonical` | Yes | Reuse or minimally adapt the generated-source drift check for local and CI parity. |
| `protocol/proto` | `must_preserve` | `canonical` | Yes | Validate canonical contract sources without changing protocol semantics. |
| `protocol/tests` | `must_verify` | `canonical` | Yes | Existing contract tests and fixtures define the behavior the pipelines must prove. |
| `protocol/docs` | `must_preserve` | `canonical` | Yes | Strict documentation validation remains part of the gate. |
| `protocol/README.md` | `expected_to_change` | `canonical` | Yes | Document local parity, workflow entry points, and tested-artifact consumption. |

#### Verification contract

- **lint** · `protocol` · `.github/actions and .github/workflows` — Validate metadata, reusable-workflow syntax, immutable pins, permissions, and shell syntax.
- **command** · `protocol` · `buf lint && buf generate && python scripts/check_generated.py` — Prove sources lint, generate deterministically, and match committed bindings.
- **command** · `protocol` · `python -m build` — Build wheel and sdist once and record hashes/provenance.
- **test** · `protocol` · `clean installed-artifact matrix` — Install exact wheel outside checkout and verify metadata, imports, modules, typed marker, schemas, and fixtures.
- **test** · `protocol` · `pytest` — Run the complete Protocol contract suite.
- **command** · `protocol` · `ruff check, ruff format --check, mypy, mkdocs build --strict` — Preserve repository quality and docs gates.
- **human** · `protocol` · `GitHub pull request review` — Human confirms reuse of immutable artifacts and no SFP semantic changes.

### `P8` — [TASK][MVP] Define SFP Disconnection Recovery Contracts

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `protocol/.agents/skills/stateforge-dpt-milestone` | `must_understand` | `canonical` | Yes | Milestone workflow, cross-repository blast-radius audit, and ownership closure gate. |
| `protocol/.claude/skills/stateforge-protocol-development` | `must_understand` | `canonical` | Yes | Canonical SFP ownership, compatibility, and contract-development rules. |
| `protocol/docs/assets/diagrams/disconnection-and-recovery.png` | `must_understand` | `canonical` | Yes | Recovery sequence that the completed contract and scenarios must preserve. |
| `protocol/docs/procedures/disconnection-recovery.md` | `expected_to_change` | `canonical` | Yes | Client-facing recovery procedure and normative behavior. |
| `protocol/AGENTS.md` | `must_preserve` | `canonical` | Yes | Repository-wide Protocol implementation and delivery rules. |
| `protocol/docs/reference/responsibility-boundaries.md` | `must_preserve` | `canonical` | Yes | Single-owner boundary between versioned Protocol rules and runtime-local policy. |
| `protocol/src/stateforge_protocol/sfp` | `must_verify` | `canonical` | Yes | Every packaged SFP contract, validator, shared scalar, descriptor rule, and aggregate endpoint limit affected by recovery. |
| `agent/src/stateforge_agent/_sfp` | `must_verify` | `reference` | Yes | Agent consumer surface inspected for compatibility and duplicated normative rules; this context does not authorize Agent edits. |
| `provider/src/stateforge_provider` | `must_verify` | `reference` | Yes | Provider consumer surface inspected for compatibility and duplicated normative rules; this context does not authorize Provider edits. |

#### Verification contract

- **test** · `protocol` · `python -m pytest -q` — All Protocol tests, including recovery semantics and contract ownership, pass.
- **generated** · `protocol` · `python scripts/check_generated.py` — Generated bindings and packaged contract artifacts match their authoritative sources.
- **lint** · `protocol` · `buf lint` — Versioned protobuf sources pass the repository's Buf rules.
- **integration** · `protocol` · `Execute the recovery conformance scenarios from the exact built wheel and sdist through the standard P10 workflows.` — Recovery coverage proves the shipped artifacts, not only the source checkout.
- **human** · `project` · `Review the final SFP responsibility matrix against Protocol, Agent, and Provider and account for every registered procedure and recovery boundary.` — No copied service identity, limit, scalar parser, descriptor rule, or context-independent validator remains unclassified or consumer-owned.

### `P9` — [TASK][MVP] Verify the Complete SFP Contract Surface

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `protocol/.agents/skills/stateforge-dpt-milestone` | `must_understand` | `canonical` | Yes | Cross-repository audit and completion-claim requirements. |
| `protocol/.claude/skills/stateforge-protocol-development` | `must_understand` | `canonical` | Yes | Canonical SFP ownership and contract verification rules. |
| `protocol/docs/reference/responsibility-boundaries.md` | `must_verify` | `canonical` | Yes | Release-wide responsibility matrix that must match all three implementations. |
| `protocol/proto/stateforge_protocol/sfp` | `must_verify` | `canonical` | Yes | Complete authoritative SFP wire-shape surface. |
| `protocol/src/stateforge_protocol/sfp` | `must_verify` | `canonical` | Yes | Complete packaged identities, limits, scalars, descriptor semantics, validators, and shared endpoint inventory. |
| `agent/src/stateforge_agent/_sfp` | `must_verify` | `compatibility` | Yes | Complete Agent SFP consumer audited for imports, contextual policy, and duplicate normative rules. |
| `provider/src/stateforge_provider` | `must_verify` | `compatibility` | Yes | Complete Provider SFP consumer audited for imports, contextual policy, and duplicate normative rules. |

#### Verification contract

- **test** · `protocol` · `python -m pytest -q` — The complete Protocol contract and conformance suite passes.
- **lint** · `protocol` · `buf lint && buf generate && python scripts/check_generated.py` — Schemas lint and generated artifacts are reproducible and current.
- **integration** · `protocol` · `Build wheel and sdist, inspect their contents, and run the full installed-package conformance matrix.` — Every procedure's authoritative contract and fixtures ship and execute from exact artifacts.
- **integration** · `project` · `Run Agent and Provider consumer suites against the exact built Protocol wheel.` — Both consumers reach the same wire decisions by importing Protocol, not by reimplementing it.
- **human** · `project` · `Approve a complete responsibility matrix for every SFP procedure and shared endpoint resource across Protocol, Agent, and Provider.` — The release gate fails if any service identity, RPC path, limit, scalar rule, descriptor semantic, context-independent validator, or transport ceiling lacks exactly one authoritative owner.

### `R0` — [TASK][MVP] Implement Provider Discovery and Handshake Foundation

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `R1` — [TASK][MVP] Implement Provider Manifest Exchange

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `provider/docs` | `expected_to_change` | `canonical` | Yes | Update docs respectfully to the change. |
| `provider/pyproject.toml` | `expected_to_change` | `canonical` | Yes | Dependencies probably. |
| `provider/src/stateforge_provider` | `expected_to_change` | `canonical` | Yes | Where implementation would live. |
| `protocol/proto/stateforge_protocol/sfp/manifest` | `must_understand` | `canonical` | Yes | Manifest exchange protocol buffers. |
| `protocol/docs/assets/diagrams/provider-manifest-exchange.png` | `must_understand` | `canonical` | Yes | Manifest change diagram. |
| `protocol/src/stateforge_protocol/sfp/manifest` | `must_understand` | `canonical` | Yes | Generate protobuf python binding. |
| `protocol/docs/procedures/provider-manifest.md` | `must_understand` | `canonical` | Yes | Manifest exchange docs. |

#### Verification contract

- **human** · `provider` · `Review passed?` — Human In The loop involved.

### `R2` — [TASK][MVP] Implement Provider Health and Availability Reporting

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `protocol/docs/assets/diagrams/health-and-availability-monitoring.png` | `must_understand` | `canonical` | Yes | Health procedure diagram. |
| `protocol/docs/procedures/health.md` | `must_understand` | `canonical` | Yes | Initial description of the health and availability monitoring procedures. |
| `protocol/.claude/skills` | `must_understand` | `canonical` | Yes | Skills needed to modify this project. |
| `protocol/.agents/skills/stateforge-dpt-milestone` | `must_understand` | `canonical` | Yes | Skill that explains DPT. |
| `protocol/AGENTS.md` | `must_understand` | `canonical` | Yes | Explanation toward agents before editing this repository. |

#### Verification contract

- **human** · `protocol` · `GitHub review` — Human In The Loop.

### `R3` — [TASK][MVP] Implement Provider Capability Assessment

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `R4` — [TASK][MVP] Implement Trigger Publication and Acknowledgement

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `R5` — [TASK][MVP] Implement Operation Admission and Idempotency

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `R6` — [TASK][MVP] Implement Operation Progress Results and Cancellation

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `R11` — [TASK][MVP] Build Reusable Provider Package and Runtime CI/CD Pipelines

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `provider/AGENTS.md` | `must_preserve` | `canonical` | Yes | Preserve the authoring vision, runtime abstraction, and human delivery authority. |
| `provider/pyproject.toml` | `must_understand` | `canonical` | Yes | Defines the package, Python support, dependencies, coverage, and gates. |
| `provider/src/stateforge_provider/provider.py` | `must_preserve` | `canonical` | Yes | Fixtures and scenarios must use the public authoring/lifecycle surface. |
| `provider/src/stateforge_provider/_runtime` | `must_verify` | `canonical` | Yes | Exercise endpoint ownership, startup, sessions, shutdown, and cleanup without duplicating runtime logic. |
| `provider/src/stateforge_provider/_services` | `must_verify` | `canonical` | Yes | Verify implemented Bootstrap and Manifest services through public wire behavior. |
| `provider/tests` | `must_preserve` | `canonical` | Yes | Existing tests remain authoritative and stay in the aggregate gate. |
| `provider/docs` | `must_preserve` | `canonical` | Yes | Architecture and authoring docs define boundaries the fixtures must respect. |
| `provider/README.md` | `expected_to_change` | `canonical` | Yes | Document local parity, inputs, scenario composition, and artifact reuse. |

#### Verification contract

- **lint** · `provider` · `.github/actions and .github/workflows` — Validate metadata, workflow syntax, immutable pins, permissions, and shell syntax.
- **command** · `provider` · `python -m build` — Build wheel and sdist once and record artifact/dependency provenance.
- **test** · `provider` · `clean installed-artifact matrix` — Install exact Provider/Protocol artifacts outside checkouts and verify metadata, import origin, public API, uninstall, and reinstall.
- **test** · `provider` · `composable installed-runtime scenarios` — Exercise startup, Bootstrap, Manifest, multi-Provider, replacement, invalid peer, crash, restart, shutdown, cleanup, and evidence.
- **test** · `provider` · `pytest with configured coverage threshold` — Run the complete Provider suite with its coverage contract.
- **command** · `provider` · `ruff check, ruff format --check, mypy, mkdocs build --strict` — Preserve repository quality and docs gates.
- **human** · `provider` · `GitHub pull request review` — Human confirms public APIs, exact artifact reuse, and no duplicated runtime.

### `R9` — [TASK][MVP] Complete Provider Disconnection and Recovery

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `R10` — [TASK][MVP] Verify the Complete Provider Runtime

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `provider/.agents/skills/stateforge-dpt-milestone` | `must_understand` | `canonical` | Yes | Cross-repository audit and completion-claim requirements. |
| `provider/.claude/skills/stateforge-protocol-development` | `must_understand` | `canonical` | Yes | Provider consumer ownership and runtime boundary rules. |
| `provider/.claude/PROVIDER_AUTHORING_VISION.md` | `must_preserve` | `canonical` | Yes | Public Provider framework contract that internal SFP plumbing must preserve. |
| `protocol/docs/reference/responsibility-boundaries.md` | `must_verify` | `canonical` | Yes | Canonical split between Protocol rules and Provider-local policy. |
| `protocol/src/stateforge_protocol/sfp` | `must_verify` | `compatibility` | Yes | Every authoritative SFP contract the Provider must consume. |
| `provider/src/stateforge_provider` | `must_verify` | `canonical` | Yes | Complete Provider runtime and author-facing surface. |
| `agent/src/stateforge_agent/_sfp` | `must_verify` | `reference` | Yes | Independent Agent peer surface used to confirm interoperability and ownership. |
| `provider/tests` | `must_verify` | `canonical` | Yes | Focused, ownership, package, lifecycle, and real-process evidence. |

#### Verification contract

- **test** · `provider` · `python -m pytest -q` — The complete Provider suite passes.
- **command** · `provider` · `python -m ruff format --check . && python -m ruff check . && python -m mypy src && python -m mkdocs build --strict` — Formatting, linting, typing, and strict documentation pass.
- **integration** · `provider` · `Build and clean-install the Provider wheel and sdist, then execute the full R11 installed-runtime matrix with the exact Protocol wheel and Agent RPM.` — The shipped Provider behaves correctly with real independent artifacts.
- **test** · `provider` · `Run Provider ownership/delegation tests for every registered SFP procedure.` — Context-independent validation delegates to Protocol while only runtime-state policy remains in Provider.
- **human** · `project` · `Review the Provider row of the complete SFP responsibility matrix against Protocol and Agent.` — No copied normative contract or unclassified Provider rule remains before runtime completion is claimed.

### `A0` — [TASK][MVP] Implement SFP Discovery and Handshake Foundation

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `A1` — [TASK][MVP] Integrate Provider Manifest Exchange

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `protocol/proto/stateforge_protocol/sfp/manifest/v1/manifest.proto` | `must_understand` | `canonical` | Yes | Protocol description |
| `provider/src/stateforge_provider/_services/manifest` | `must_understand` | `canonical` | Yes | Provider implementation  |
| `agent/.claude` | `must_understand` | `canonical` | Yes | Skills to edit this repo |
| `agent/.agents` | `must_understand` | `canonical` | Yes | Skills to edit this repo |
| `agent/AGENTS.md` | `must_understand` | `canonical` | Yes | Agent instructions. |
| `protocol/docs/procedures/provider-manifest.md` | `must_understand` | `canonical` | Yes | Manifest exchange protocol description |
| `protocol/docs/assets/diagrams/provider-manifest-exchange.png` | `must_understand` | `canonical` | Yes | Manifest exchange diagram |

#### Verification contract

- **human** · `agent` · `GitHub Review` — Human In The Loop

### `A2` — [TASK][MVP] Integrate Provider Health and Availability Monitoring

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `agent/.agents/skills/stateforge-dpt-milestone` | `must_understand` | `canonical` | Yes | Milestone workflow, cross-repository blast-radius audit, and ownership closure gate. |
| `agent/.claude/skills/stateforge-protocol-development` | `must_understand` | `canonical` | Yes | SFP consumer ownership and runtime integration rules. |
| `protocol/docs/procedures/health.md` | `must_understand` | `canonical` | Yes | Canonical standard Health and Agent eligibility semantics. |
| `protocol/docs/reference/responsibility-boundaries.md` | `must_preserve` | `canonical` | Yes | Single-owner boundary between versioned Protocol rules and Agent-local state or policy. |
| `protocol/src/stateforge_protocol/sfp/health_contract.py` | `must_understand` | `canonical` | Yes | Canonical service identity, monitored key, bounds, and status vocabulary consumed by the Agent. |
| `provider/src/stateforge_provider/_services/health` | `must_understand` | `reference` | Yes | Provider-side standard Health behavior used by the real integration peer; this context does not authorize Provider edits. |
| `agent/src/stateforge_agent/_sfp` | `expected_to_change` | `canonical` | Yes | Agent SFP client, session fencing, and availability coordination surface. |
| `agent/tests` | `expected_to_change` | `canonical` | Yes | Behavioral, ownership, and real-process integration evidence. |

#### Verification contract

- **test** · `agent` · `python -m pytest -q` — Agent health, eligibility, session-fencing, recovery, and ownership tests pass.
- **typecheck** · `agent` · `python -m mypy src` — The Agent integration remains strictly typed.
- **lint** · `agent` · `python -m ruff format --check . && python -m ruff check .` — The Agent source and tests pass formatting and lint gates.
- **integration** · `agent` · `Run the A13 installed-Agent Standard Health scenarios with the exact Agent RPM, Protocol wheel, and Provider wheel in separate processes over the Unix socket.` — Evidence covers startup, Watch, health loss and recovery, stale-session fencing, invalid manifest, shutdown, and admitted-work preservation.
- **human** · `project` · `Review the Health responsibility matrix and consumer imports across Protocol, Agent, and Provider.` — Agent contains no copied canonical service names, wire limits, status vocabulary, scalar rules, or context-independent validators; only availability and retry policy remain local.

### `A3` — [TASK][MVP] Integrate Provider Capability Assessment

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `A4` — [TASK][MVP] Integrate Trigger Publication and Acknowledgement

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `A5` — [TASK][MVP] Integrate Operation Admission and Idempotency

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `A6` — [TASK][MVP] Integrate Operation Progress Results and Cancellation

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `A7` — [TASK][MVP] Implement Agent-Managed Backup Workspaces

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `A8` — [TASK][MVP] Implement the BackupEngine Extension Layer

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `A13` — [TASK][MVP] Build Reusable Agent RPM CI/CD Pipelines

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `agent/AGENTS.md` | `must_preserve` | `canonical` | Yes | Repository-wide implementation and human delivery rules. |
| `agent/packaging/rpm` | `expected_to_change` | `canonical` | Yes | Canonical RPM spec and service packaging consumed by reusable automation. |
| `agent/pyproject.toml` | `must_verify` | `canonical` | Yes | Package version, build backend, Python support, and runtime dependency metadata. |
| `agent/tools/linux-test` | `must_preserve` | `canonical` | Yes | Existing Linux validation remains separate and must not be replaced by the packaging gate. |
| `agent/tests` | `must_preserve` | `canonical` | Yes | Existing behavioral gates remain authoritative while automation contract tests are added. |
| `agent/README.md` | `expected_to_change` | `canonical` | Yes | Document the reusable local RPM build and installed-package verification commands. |

#### Verification contract

- **lint** · `agent` · `actionlint .github/workflows/*.yml and composite-action metadata validation` — Validate reusable workflow syntax and interfaces.
- **lint** · `agent` · `bash -n packaging/rpm/*.sh` — Validate the reusable local command layer.
- **test** · `agent` · `.venv/bin/pytest -q -o addopts='' tests/test_rpm_automation.py` — Enforce centralized build logic, exact-artifact handoff, thin callers, and immutable action pinning.
- **command** · `agent` · `packaging/rpm/build-rpm.sh` — Build the canonical binary RPM, source RPM, checksums, and metadata.
- **test** · `agent` · `packaging/rpm/test-installed-rpm.sh --rpm <built-binary-rpm>` — Install, verify, evidence, and remove the exact RPM in clean Fedora.
- **test** · `agent` · `ruff format --check . && ruff check . && mypy src && pytest && mkdocs build --strict` — Preserve project quality, behavior, typing, and documentation.
- **human** · `agent` · `GitHub Review` — Review artifact provenance, permissions, pinning, packaging boundaries, and reuse.

### `A9` — [TASK][MVP] Implement ResticBackupEngine

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `A10` — [TASK][MVP] Integrate Agent Backup and Restore Orchestration

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `A11` — [TASK][MVP] Complete SFP Disconnection and Recovery

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `A12` — [TASK][MVP] Verify the Complete Local Agent and Provider Runtime

#### Required context and protected behavior

| Repository path | Role | Authority | Required | Why |
| --- | --- | --- | --- | --- |
| `agent/.agents/skills/stateforge-dpt-milestone` | `must_understand` | `canonical` | Yes | Cross-repository audit and completion-claim requirements. |
| `agent/.claude/skills/stateforge-protocol-development` | `must_understand` | `canonical` | Yes | Agent consumer ownership and complete SFP verification rules. |
| `protocol/docs/reference/responsibility-boundaries.md` | `must_verify` | `canonical` | Yes | Release-wide boundary matrix reconciled against the final installed system. |
| `protocol/src/stateforge_protocol/sfp` | `must_verify` | `compatibility` | Yes | All authoritative SFP contracts used by the complete runtime. |
| `provider/src/stateforge_provider` | `must_verify` | `compatibility` | Yes | Complete Provider runtime and author-facing integration surface. |
| `agent/src/stateforge_agent/_sfp` | `must_verify` | `canonical` | Yes | Complete Agent SFP consumer, availability, recovery, and session surface. |
| `agent/.github/actions` | `must_verify` | `canonical` | Yes | Reusable installed-artifact test framework and complete scenario catalogue. |
| `provider/.github/actions` | `must_verify` | `compatibility` | Yes | Reusable Provider fixture and runtime scenario actions used by the system matrix. |

#### Verification contract

- **test** · `agent` · `python -m pytest -q` — The complete Agent suite passes.
- **command** · `agent` · `python -m ruff format --check . && python -m ruff check . && python -m mypy src && python -m mkdocs build --strict` — Formatting, linting, typing, and strict documentation pass.
- **integration** · `agent` · `Run the complete installed-artifact matrix with the exact Protocol wheel, Provider wheel, Agent RPM, BackupEngine fixture, and Restic integration in separate processes.` — The shipped system exercises every planned SFP procedure, backup capability, failure boundary, and supported Linux runtime.
- **integration** · `project` · `Run Protocol contract tests and Agent/Provider ownership-delegation suites against the exact artifacts used by the system matrix.` — Equivalent behavior comes from one canonical contract rather than duplicated implementations.
- **human** · `project` · `Approve the final responsibility and coverage inventories for every SFP procedure and shared endpoint resource.` — No unaudited repository, unclassified rule, missing scenario, or duplicate normative implementation remains when local runtime completion is claimed.

### `P11` — [TASK][MVP] Add Versioned Provider Views to Manifest-Declared Operations and Triggers

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `R12` — [TASK][MVP] Add Declarative Operation and Trigger Views to the Provider Python DSL

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `R13` — [TASK][MVP] Package Provider-Owned Icons, Images, and Presentation Assets

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `R14` — [TASK][MVP] Publish Versioned Provider Views through Manifest Exchange

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._

### `R15` — [TASK][MVP] Verify Provider View Declarations, Assets, and Revision Semantics

_No implementation context has been declared yet._

#### Verification contract

_No verification evidence has been declared yet._


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
