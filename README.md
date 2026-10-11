# StateForge Provider

Python framework and runtime for building standalone StateForge Provider
processes.

Provider implementations use the generated contracts from
`stateforge-protocol`, expose SFP through the Developer RPC runtime, and keep
all third-party-specific behavior outside the StateForge Agent.

Subclass `Provider`, declare identity/version and platform pairs, and use typed
`ProviderModel` classes with `@operation` for operation metadata.
The runtime validates an immutable schema-1 manifest and serves it after
handshake on the existing endpoint. See the
[authoring guide](docs/manifest-authoring.md) and
[complete example](examples/reference_provider.py).

Install the Provider framework from PyPI:

```sh
python -m pip install stateforge-provider
```

Import the public authoring API from `stateforge_provider`:

```python
from stateforge_provider import Platform, Provider, ProviderModel, operation
```

For repository development, install the project and its development tools
from its package metadata:

```sh
python -m pip install -e . --group dev --group docs
```

Validate with Ruff, strict mypy, pytest, `python -m build`, and
`mkdocs build --strict`.

The repository also provides reusable package and installed-runtime pipelines.
They build the Provider and a selected Protocol revision once, install those
exact artifacts outside both checkouts, and exercise public-API Provider
fixtures over real Bootstrap and Manifest RPCs. See the
[CI/CD automation guide](docs/ci-automation.md) for the action catalog, local
parity commands, scenario tiers, inputs, and retained evidence.
