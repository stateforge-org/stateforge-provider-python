# StateForge Provider Implementation

Reference skeleton for building a standalone StateForge Provider process.

Provider implementations use the generated contracts from
`stateforge-protocol`, expose SFP through the Developer RPC runtime, and keep
all third-party-specific behavior outside the StateForge Agent.

Subclass `Provider`, declare identity/version and platform pairs, and use typed
`ProviderModel` classes with `@operation` for operation metadata.
The runtime validates an immutable schema-1 manifest and serves it after
handshake on the existing endpoint. See the
[authoring guide](docs/manifest-authoring.md) and
[complete example](examples/reference_provider.py).

Install the project and its development tools from its package metadata:

```sh
python -m pip install -e . --group dev --group docs
```

Validate with Ruff, strict mypy, pytest, `python -m build`, and
`mkdocs build --strict`. The R1 declarations do not dispatch operations or
publish triggers; those runtime milestones follow separately.
