---
name: stateforge-pr-review
description: Prepare or review one StateForge pull request against its DPT milestone and GitHub Issue, architecture boundary, Python and protocol standards, tests, documentation, and packaging. Use when drafting a PR, reviewing a branch or diff, addressing review comments, or deciding whether a StateForge change is ready for human review.
---

# StateForge Pull Request Review

Assist with one explicitly selected DPT milestone and its GitHub Issue. Do
not broaden the review into the next procedure or redesign unrelated code.

## Establish the review basis

Read `CLAUDE.md`, root `STATEFORGE_DPT.md`, applicable repository skills,
`.claude/PROVIDER_AUTHORING_VISION.md`, and the active issue or requested
outcome. Determine the intended base and inspect the actual diff. If the base
is ambiguous, report the assumption rather than silently reviewing an
arbitrary comparison.

Follow `.agents/skills/stateforge-dpt-milestone/SKILL.md` for assignment
mapping and the human handoff. Local implementation commits are allowed.
Humans own GitHub mutations, PR creation, formal review/approval, and merging.
An agent's review findings are advisory and do not substitute for that human
review. Do not submit a formal GitHub review or approval as part of this skill.

## Review in priority order

1. Correctness, data loss, security, deadlocks, races, and recovery failures.
2. Violation of Agent, Provider, Protocol, BackupEngine, or process boundaries.
3. Wire/API compatibility, ownership, idempotency, replay, cancellation, and
   error semantics.
4. Missing observable behavior, failure coverage, documentation, packaging, or
   generated-artifact updates.
5. Python clarity, typing, docstrings, and unnecessary abstractions.

Apply the repository's StateForge Python-development skill to handwritten
Python. Apply the protocol-development skill to SFP changes. Prefer cohesive,
direct code; do not demand helpers, layers, or patterns unless they materially
improve reuse, clarity, or separation of concerns.

Tests are automated behavioral gates. Inspect them as evidence for changed
behavior, but do not conduct a separate stylistic review of test files unless
the user requests it.

## Review runtime boundaries explicitly

When a diff touches endpoint, lifecycle, session, discovery, persistence, or
RPC service code, trace more than the successful path:

- Identify who owns the event loop, signals, global state, files, locks, and
  each lifecycle transition. An embedded API must not silently take ownership
  from its caller.
- Trace startup, normal shutdown, rollback, cancellation, timeout, and partial
  failure. Confirm new admission closes before author resources are released,
  accepted work has a defined drain/cancel policy, independent cleanup still
  runs, and real cleanup failures remain observable.
- Review filesystem operations for bounded reads, no-follow behavior, file
  type/ownership/mode checks, replacement races, and identity-checked removal.
- Distinguish the multiplexed endpoint's transport safety ceiling from every
  RPC's exact request and response limits. Adding one procedure must not impose
  its limits on unrelated services.
- Distinguish fixed protocol invariants from configurable operational limits
  and verify that each value has one clear owner.
- Check dependency exception normalization and ensure remote diagnostics do not
  expose declarations, schemas, configured values, credentials, or tracebacks.
- Require behavioral evidence for the affected failure and cancellation paths;
  a happy-path test is not sufficient evidence for lifecycle or recovery code.

## Report actionable findings

Lead with concrete findings ordered by severity:

- `P0`: release-blocking or destructive;
- `P1`: correctness, security, or compatibility failure;
- `P2`: important maintainability or incomplete-contract problem;
- `P3`: small improvement that is worth fixing.

For each finding, identify the narrow file and line range, explain the actual
failure or risk, and state the expected behavior. Do not manufacture findings
to fill a category. If there are no findings, say so and identify any remaining
verification gap.

Keep review comments human and specific. Avoid generic praise, restating the
diff, or turning personal style preferences into blockers.

## Verify and hand off

Run the applicable configured quality gates. Distinguish a passing check from a
check that was not available. Do not mark a plan item implemented solely
because documentation exists or because the diff looks complete.

When asked to prepare a pull request, draft:

- the `[TASK][MVP] ...` title;
- a short explanation of why the change is needed;
- the behavior present after merge;
- verification performed;
- deliberate non-goals or follow-up dependencies.

Report implementation and verification evidence in the handoff, not by
editing `STATEFORGE_DPT.md` or SQLite or invoking DPT to change status.
A local implementation, commit, passing check, review, or PR draft does not
complete the DPT step. Humans open, review, and merge the correctly associated
PR; DPT reconciliation derives the delivered state from GitHub evidence.
Stop at the handoff without pushing or beginning another milestone.
