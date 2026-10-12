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
- two distinct Provider installations running concurrently;
- same-installation replacement with a stable identity and newer generation;
- rejection of malformed Provider discovery data followed by valid recovery;
- abrupt process failure followed by a valid newer generation; and
- uninstall and reinstall of the exact Provider wheel.

The fixtures import only the public `stateforge_provider` API. Each runtime
scenario installs the exact Agent RPM into an isolated Fedora system, starts
the packaged `stateforge-agent.service`, installs the exact Provider and
Protocol wheels beside it, and observes acceptance or rejection through the
real Agent journal. Runtime scenarios run on Linux because the current endpoint
contract uses Unix-domain sockets and the Agent is packaged as a Linux service.
Package identity and import checks remain independent and run on Linux, macOS,
and Windows for Python 3.11, 3.12, and 3.13.

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
