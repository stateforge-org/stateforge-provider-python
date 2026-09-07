---
name: stateforge-pr-review
description: Prepare or review one StateForge pull request against its MVP plan item, architecture boundary, Python and protocol standards, tests, documentation, and packaging. Use when drafting a PR, reviewing a branch or diff, addressing review comments, or deciding whether a StateForge change is ready for human review.
---

# StateForge Pull Request Review

Review one explicitly selected MVP plan item. Do not broaden the review into
the next procedure or redesign unrelated code.

## Establish the review basis

Read `CLAUDE.md`, `.claude/MVP_PLAN.md`, applicable repository skills, and
the active issue or requested outcome. Determine the intended base and inspect
the actual diff. If the base is ambiguous, report the assumption rather than
silently reviewing an arbitrary comparison.

The user owns GitHub state. Do not create issues, open pull requests, push,
merge, or change remote state unless explicitly instructed.

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

Update the local MVP ledger when implementation evidence changes, but do not
claim that a GitHub PR was opened or merged. Stop for human review before
starting another plan item.
