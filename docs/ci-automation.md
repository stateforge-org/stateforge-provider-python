# Package and runtime CI/CD

The Provider repository validates the distributable package and the runtime
that package actually installs. CI does not import `stateforge_provider` from
the source checkout and does not maintain a second implementation of endpoint,
Bootstrap, or Manifest behavior.

## Architecture

The automation has three layers:

1. Focused composite actions in `.github/actions/` own one repeated operation:
   package construction, isolated installation, Agent service lifecycle,
   Provider fixture lifecycle, Agent-observed assertions, or evidence
   collection.
2. Each directory under `.github/actions/scenarios/` is one independently
   selectable runtime scenario. A scenario composes the focused actions and
   always collects evidence and removes its temporary state.
3. Reusable `workflow_call` workflows own job topology, matrices, immutable
   artifact transfer, and retention. The pull-request, integration, and
   release-candidate workflows are thin callers.

The build job checks out the selected Protocol and Agent revisions, invokes
each repository's canonical portable builder, and produces one bundle
containing:

- the Provider wheel and source distribution;
- the Protocol wheel and source distribution built from `protocol-ref`;
- the Agent binary and source RPMs built from `agent-ref`;
- the exact Agent-owned Fedora runtime-test image definition;
- each component's SHA-256 checksum and provenance files;
- the requested Agent and Protocol refs and their resolved commits; and
- the combined Provider, Protocol, Agent, Python, runner, and source
  provenance.

Every source-verification, installed-package, and runtime job downloads that
same bundle. The source gate installs its exact Provider and Protocol wheels
before running tests, then validates the working-tree source with Ruff, mypy,
pytest, and MkDocs. No verification job rebuilds a distribution or RPM or
resolves an unpublished StateForge package from PyPI.

The runtime jobs build their isolated Fedora system from the Agent test-image
definition carried in that bundle. They do not perform a second private Agent
checkout, so the RPM and its test environment stay bound to the same resolved
Agent commit and dependency credentials remain confined to the build job.

Because the Agent and Protocol repositories are private, entry-point workflows
pass `STATEFORGE_CI_APP_ID` and `STATEFORGE_CI_PRIVATE_KEY` into the reusable
build workflow. That workflow mints one short-lived installation token scoped
to read-only contents access for only `stateforge-agent` and
`stateforge-protocol`. The token authenticates those two source checkouts and
is not forwarded to verification jobs, runtime containers, or Provider
processes. The StateForge CI GitHub App must be installed on both dependency
repositories.

## Local parity

Run the repository gates with the package metadata as their source of truth:

```sh
python -m pip install -e . --group dev --group docs
python -m ruff format --check .
python -m ruff check .
python -m mypy src
python -m pytest
python -m mkdocs build --strict
```

Build the Provider artifacts with the same canonical command used by the build
action:

```sh
python -m build --sdist --wheel --outdir dist/provider
```

The Provider-owned build action is location-independent. Another StateForge
repository can check out an exact Provider revision below its own workspace
and invoke the action from that checkout:

```yaml
- uses: actions/checkout@<immutable-sha>
  with:
    repository: stateforge-org/stateforge-provider-python
    ref: <provider-ref-or-commit>
    path: .stateforge-ci/provider
    persist-credentials: false

- uses: ./.stateforge-ci/provider/.github/actions/package/build
  with:
    output-directory: dist/provider
    evidence-directory: evidence/provider-build
```

The action locates and builds the repository snapshot that contains it. It
does not assume that the caller's workspace root is Provider source.

To reproduce an installed-package check, create a clean environment outside the
repository and install an explicitly selected Protocol wheel together with the
built Provider wheel:

```sh
python -m venv /tmp/stateforge-provider-installed
/tmp/stateforge-provider-installed/bin/python -m pip install \
  /absolute/path/to/stateforge_protocol-*.whl \
  /absolute/path/to/stateforge_provider-*.whl
cd /tmp
unset PYTHONPATH PYTHONHOME
/tmp/stateforge-provider-installed/bin/python -I -c \
  'import stateforge_provider; print(stateforge_provider.__file__)'
```

The printed module path must belong to the isolated environment, not this
checkout.

## Workflow inputs

`provider-build-and-verify.yml` is the aggregate reusable gate. Its significant
inputs are:

| Input | Default | Meaning |
| --- | --- | --- |
| `agent-ref` | `mvp/implementation` | Agent branch, tag, or commit to resolve and package as an RPM |
| `protocol-ref` | `mvp/implementation` | Protocol branch, tag, or commit to resolve and package |
| `scenario-tier` | `full` | `smoke` runs the normal installed-service lifecycle; `full` adds the complete catalog |
| `retention-days` | `14` | Retention for distributions and bounded evidence |

Release-candidate runs may use the convenient default branch during
development, but should pass immutable Agent and Protocol commit SHAs when
selecting a candidate.

## Runtime scenarios

The runtime suite currently covers:

- normal startup, Agent-observed Bootstrap and Manifest acceptance, graceful
  shutdown, and cleanup;
- standard Health Check and Watch on the same Provider socket, including
  initial replay, maintenance, recovery, unknown service, and hook failure;
- Capability Assessment through the installed Agent client and real Provider,
  including every support state, unmet and unknown requirements, exact-scope
  evidence reuse, request-preserving retry, stale session/generation/manifest
  rejection, readiness loss and recovery, environment-driven reassessment,
  cooperative cancellation, canonical request and response limits,
  malformed-response rejection, and reassessment after Provider restart;
- two distinct Provider installations running concurrently;
- same-installation replacement with a stable identity and newer generation;
- rejection of malformed Provider discovery data followed by valid recovery;
- abrupt process failure followed by a valid newer generation;
- uninstall and reinstall of the exact Provider wheel;
- installed-wheel Trigger Publication through an independent Protocol peer,
  including callback and decorated sources, a bounded receive window,
  retryable rejection with immutable replay, accepted duplicate disposition,
  terminal rejection, stale-fence rejection, stream loss, and replay under a
  fresh fenced session;
- installed-wheel Operation Admission through an independent Protocol peer,
  including exact fences, role and requirement rejection, 20 concurrent
  identical requests converging on one dispatch, typed idempotency conflict,
  immutable author context, lost-response replay, deadline and schema
  rejection, record expiry, restart, secret-safe evidence, and clean endpoint
  removal;
- end-to-end Operation Admission through the exact installed Agent RPM and
  exact Provider and Protocol wheels, including Agent-normalized admission,
  identical concurrent requests, a discarded post-admission response and
  immutable retry, changed-content conflict, replacement-generation fencing,
  exactly-once dispatch, and bounded evidence;
- installed-wheel Operation Lifecycle through an independent Protocol peer,
  including determinate progress, typed terminal results, coalesced state,
  immutable terminal replay, requested and repeated cancellation, confirmed
  cancellation effects, unsupported cancellation, invalid-progress
  normalization, stale-session rejection, canonical request limits, and clean
  endpoint removal;
- end-to-end Operation Lifecycle through the exact installed Agent RPM and
  exact Provider and Protocol wheels, including Agent-observed progress,
  terminal replay, cursor-gap indication, Watch retry after a deterministic
  transport interruption without redispatch, typed failure and invalid-result
  normalization, cooperative cancellation and a completion/cancellation
  race, durable terminal state across a separate installed-Agent requester
  process, and rejection of its superseded session; and
- end-to-end Trigger Publication through the exact installed Agent RPM and
  exact Provider and Protocol wheels, including durable `accepted_new`, a lost
  acknowledgement, Agent crash and restart, immutable replay with
  `accepted_duplicate`, callback publication, retry across journal write
  failure with an explicitly correlated retryable rejection,
  conflicting-content rejection, a newer Provider endpoint generation,
  rejection of publication from the superseded session, and clean shutdown.

Runtime fixtures exercise Provider behavior through the public
`stateforge_provider` API. The R18 fixture uses narrowly scoped private hooks
only to discard one acknowledgement and assign one deterministic publication
ID for fault injection; its publications still originate from the public
decorator and callback APIs. R19 similarly discards one Operation Admission
response only after the real Provider has admitted it. Installed-Agent
scenarios install the exact Agent RPM into an isolated Fedora system, start
the packaged `stateforge-agent.service`, install the exact Provider and
Protocol wheels beside it, and observe acceptance or rejection through the
real Agent journal. Runtime scenarios run on Linux because the current endpoint
contract uses Unix-domain sockets and the Agent is packaged as a Linux service.
Package identity and import checks remain independent and run on Linux, macOS,
and Windows for Python 3.11, 3.12, and 3.13.

R17 Capability Assessment verification installs the exact Agent RPM, Provider
wheel, and Protocol wheel from the immutable build bundle. The Provider and
Agent run as separate systemd-managed processes and communicate over the real
generation-specific Unix socket. The scenario uses the installed Agent's A3
client and session manager; it does not substitute a Provider-side probe.

The fixture declares four operations through the public Provider author API.
Together they produce `supported`, `supported_with_requirements`,
`unsupported`, and `indeterminate` evidence. CI also removes access to a
separate target file and proves that fresh assessment reflects the changed
environment without changing process-wide Health. Target hashes and fixture
events prove assessment is read-only and never dispatches an operation.

Transient retry is injected at the Agent requester boundary before the second
attempt reaches the real Provider. The retained evidence proves both attempts
carry identical serialized requests. A narrowly isolated malformed-response
peer verifies the installed Agent rejects invalid wire data; all successful,
readiness, fence, environment, and restart paths continue to use the real
Provider process.

The boundary fixture also exposes one cancellable public requirement check.
The installed Agent cancels the active RPC, the Provider observes cancellation
without completing the check, no partial evidence enters the Agent cache, and
the same session completes a later assessment. Message-size coverage imports
the canonical Protocol limits: the real Provider accepts an exact-limit
request, rejects an oversized request before author code, and rejects a valid
assessment whose repeated findings would exceed the response limit. A normal
assessment must still succeed after both limit failures.

R18 Trigger Publication verification keeps two intentionally different
boundaries. The focused Protocol peer injects exact wire decisions and checks
Provider-owned retry, flow control, terminal rejection, stale fencing, and
shutdown without replacing any Agent behavior. The installed-runtime scenario
runs the packaged Agent and Provider as separate systemd-managed processes over
the real generation-specific Unix socket. It validates the Agent's durable
journal with canonical Protocol parsing and content fingerprints.

The installed scenario deliberately loses the first terminal acknowledgement
after the Agent has committed the publication, crashes and restarts the Agent,
and proves the Provider replays the same publication identity and content. The
Agent returns `accepted_duplicate`, after which callback publication continues.
The same scenario makes the Agent journal temporarily unwritable and proves the
Provider retains and retries the publication until responsibility can be
accepted. Finally, the Provider is restarted with the same installation
identity and publication ID but different content; the Agent returns the
terminal idempotency-conflict decision without creating another durable row.
The focused peer also fixes the receive window at one, queues two publications,
and proves the second remains blocked until the first terminal acknowledgement
releases capacity. The installed Agent scenario keeps the first Provider alive
while accepting a newer endpoint generation, then proves a publication queued
by the superseded Provider is never acknowledged or added to durable Agent
state.

R19 keeps the independent Protocol peer for deterministic Provider registry
checks and adds a separate installed-Agent scenario. The latter imports the
requester from the installed RPM in a standalone verifier process, uses the real
systemd-managed Provider on its Unix socket, and correlates Agent dispositions
with operation-ID-specific Provider dispatch events and serialized-request
digests. It also checks generation, session, and manifest fences independently
and resolves an uncertain admission from a new requester process using the same
durable Agent journal. The Agent daemon runs and monitors the Provider, but it
does not originate these admission calls: it has no operation-submission ingress
yet. This is installed Agent requester-code integration, not daemon-level
admission. A response-loss marker is confined to the CI fixture; no production
author API or wire contract changes for this test.
The retained evidence includes exact artifact checksums, Agent and Provider
process identities, endpoint generations, journal excerpts, dispositions,
dispatch counts, and final cleanup state.

R20 adds an installed-Agent Operation Lifecycle scenario beside the direct
Protocol-peer scenario. It runs the Agent RPM's session manager, admission and
lifecycle coordinators, journal, and lifecycle client in a standalone
requester process against the real Provider's generation-specific Unix socket.
The systemd Agent service is installed and started, but it is not an operation
ingress path; this verifies installed requester-to-Provider behavior, not
daemon-level submission. A second installed-RPM requester process reopens the
same isolated journal after a systemd-managed Provider restart, establishes a
fresh session on the incremented endpoint generation, confirms retained
terminal state, and proves a Watch using the superseded session and generation
is rejected. Slow-observer and observer-capacity behavior remains covered by
the independent Protocol-peer scenario.

## Evidence and security

Build provenance and checksums are retained with the immutable artifact bundle.
Each scenario retains bounded RPM and wheel installation logs, Agent and
Provider journals, descriptors, lifecycle events, runtime inventory, and
failure diagnostics. It stops transient services, verifies and removes the
Agent RPM, destroys the Fedora system, and deletes temporary runtime state even
when an assertion fails.

External actions are pinned to complete commit SHAs. Workflows have read-only
repository permissions, do not persist checkout credentials, use bounded job
timeouts, and do not pass credentials to Provider processes. `actionlint`,
Zizmor, Ruff, mypy, pytest with coverage, and strict MkDocs are part of the
aggregate gate.

The installed-package matrix verifies that the distribution, metadata, and
public API can be imported on Linux, macOS, and Windows. Starting a Provider
runtime still requires POSIX advisory locking and Unix-domain sockets; an
unsupported platform receives an explicit runtime error when startup begins.
