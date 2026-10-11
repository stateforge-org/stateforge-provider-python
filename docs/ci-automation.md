# Package and runtime CI/CD

The Provider repository validates the distributable package and the runtime
that package actually installs. CI does not import `stateforge_provider` from
the source checkout and does not maintain a second implementation of endpoint,
Bootstrap, or Manifest behavior.

## Architecture

The automation has three layers:

1. Focused composite actions in `.github/actions/` own one repeated operation:
   package construction, isolated installation, fixture staging, process
   lifecycle, SFP assertions, or evidence collection.
2. Each directory under `.github/actions/scenarios/` is one independently
   selectable runtime scenario. A scenario composes the focused actions and
   always collects evidence and removes its temporary state.
3. Reusable `workflow_call` workflows own job topology, matrices, immutable
   artifact transfer, and retention. The pull-request, integration, and
   release-candidate workflows are thin callers.

The build job produces one bundle containing:

- the Provider wheel and source distribution;
- the Protocol wheel and source distribution built from `protocol-ref`;
- SHA-256 checksum files;
- the requested Protocol ref and its resolved commit; and
- Provider, Protocol, Python, runner, and source provenance.

Every installed-package and runtime job downloads that same bundle. No test job
rebuilds either distribution.

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
| `protocol-ref` | `mvp/implementation` | Protocol branch, tag, or commit to resolve and package |
| `scenario-tier` | `full` | `smoke` runs normal lifecycle on every supported Python; `full` adds the complete catalog |
| `retention-days` | `14` | Retention for distributions and bounded evidence |

Release-candidate runs may use the convenient default branch during
development, but should pass an immutable Protocol commit SHA when selecting a
candidate.

## Runtime scenarios

The runtime suite currently covers:

- normal Bootstrap, Manifest, graceful shutdown, and cleanup;
- two distinct Provider installations running concurrently;
- same-installation replacement with a stable identity and newer generation;
- rejection of invalid Bootstrap identity and Manifest session data;
- abrupt process failure followed by a valid newer generation; and
- uninstall and reinstall of the exact Provider wheel.

The fixtures import only the public `stateforge_provider` API. Runtime scenarios
run on Linux because the current endpoint contract uses Unix-domain sockets.
Package identity and import checks run independently on Linux, macOS, and
Windows for Python 3.11, 3.12, and 3.13.

## Evidence and security

Build provenance and checksums are retained with the immutable artifact bundle.
Each scenario retains bounded package-install logs, descriptors, SFP responses,
lifecycle events, runtime inventory, and failure logs. Temporary runtime state
is removed even when an assertion fails.

External actions are pinned to complete commit SHAs. Workflows have read-only
repository permissions, do not persist checkout credentials, use bounded job
timeouts, and do not pass credentials to Provider processes. `actionlint`,
Zizmor, Ruff, mypy, pytest with coverage, and strict MkDocs are part of the
aggregate gate.
