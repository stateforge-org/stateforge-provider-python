---
name: stateforge-python-development
description: Apply StateForge Python engineering standards when creating, reviewing, refactoring, testing, packaging, or documenting Python code. Use for Python modules, tests, pyproject.toml, package layouts, command-line entry points, type annotations, docstrings, MkDocs sites, Material for MkDocs configuration, and mkdocstrings API documentation.
---

# StateForge Python Development

Produce maintainable, typed, distributable Python that follows the Python
Packaging User Guide, PEP 8, PEP 257, PEP 484, and the Python Guide. Build
project documentation with MkDocs, Material for MkDocs, and mkdocstrings.

## Apply the standards in this order

1. Follow explicit user requirements and documented project decisions.
2. Preserve compatible conventions already enforced by the repository.
3. Apply this skill and the linked upstream standards.
4. When requirements conflict, identify the conflict instead of silently
   choosing one.

Do not reformat or restructure unrelated code. Prefer the smallest coherent
change that leaves the project in a verified state.

## Enforce production-code structure

- Give each module one cohesive responsibility and keep its dependencies
  explicit. Do not structure a file as though it must be self-contained.
- Introduce a helper, class, or module only when it improves reuse, clarity, or
  separation of concerns. Do not add wrappers that merely rename one call.
- Keep related mutable state in one typed object. Do not maintain parallel
  dictionaries or collections whose keys and lifecycles must remain aligned.
- Prefer direct control flow over abstraction layers that force readers to jump
  between many small functions to understand one operation.
- Keep security and protocol validation linear when a single review surface is
  clearer. Make any complexity suppression narrow and document the reason.
- Avoid hidden coupling, catch-all utility modules, circular imports, mutable
  global state, and abstractions created only to satisfy a metric.
- Use a private third-party interface only when the dependency documents that
  interface and the reason is visible at the integration boundary.
- Apply these rules automatically whenever production code is created or
  changed. The user must not need to request a separate structural review.

## Preserve lifecycle and resource ownership

- Make ownership explicit for event loops, signals, tasks, locks, files,
  sockets, and mutable process state. APIs running inside caller-owned runtimes
  must not silently install or retain global handlers.
- Model startup, admission, draining, author cleanup, transport shutdown, and
  final cleanup as explicit phases when their ordering affects correctness.
  Use `finally` or an equivalent structured boundary so cancellation and
  intermediate failures cannot skip required cleanup.
- Attempt independent cleanup steps even after one fails. Distinguish expected
  absence or ownership mismatch from operational failure, preserve the primary
  exception during rollback, and make incomplete cleanup observable.
- At filesystem trust boundaries, prefer bounded descriptor-based access with
  no-follow, `fstat`, ownership, mode, and regular-file checks. Verify the
  filesystem identity of an entry before removing it after a long-lived
  operation.
- Normalize third-party exceptions at the owning abstraction boundary. Keep
  diagnostics useful locally and sanitized across public or remote boundaries.
- Keep tunable capacities and timeouts in typed configuration when appropriate;
  fixed protocol and identity invariants remain owned by their contract.

## Follow this workflow

1. Inspect `pyproject.toml`, the source layout, tests, documentation, and CI
   configuration before editing.
2. Identify the public API, compatibility requirements, and affected tests and
   documentation.
3. Implement the change using the rules below.
4. Add or update tests for externally observable behavior.
5. Update docstrings and user documentation in the same change when behavior
   or public APIs change.
6. Run the repository's configured checks. Do not substitute a different tool
   merely because it is familiar.
7. Report the checks run, their results, and any checks that could not run.

## Write clear Python

- Target the Python version declared by `requires-python`.
- Follow PEP 8 and use a preferred maximum line length of 79 characters unless
  the repository explicitly configures another value.
- Use four spaces for indentation and never use tabs for indentation.
- Group imports as standard library, third-party, and local imports. Prefer
  absolute imports; use explicit relative imports only within a package when
  they make the dependency clearer.
- Use descriptive names. Avoid unexplained abbreviations, single-letter names
  outside small mathematical scopes, and redundant type words in names.
- Keep functions focused and modules cohesive. Extract an abstraction only
  when it clarifies an actual boundary or removes meaningful repetition.
- Prefer standard-library facilities when they solve the problem cleanly.
- Avoid mutable default arguments, wildcard imports, import-time side effects,
  hidden global state, and broad exception handling.
- Catch the narrowest useful exception. Preserve the original cause with
  `raise ... from error` when translating exceptions.
- Use `logging` for runtime diagnostics. Reserve `print` for intentional CLI
  output.
- Keep private implementation details private with a leading underscore. Do
  not expose them from package `__init__.py` files accidentally.
- Write comments that explain constraints or reasoning, not a restatement of
  the code.

## Type all supported interfaces

- Follow PEP 484 and annotate public functions, methods, class attributes, and
  meaningful internal boundaries.
- Type both parameters and return values, including explicit `-> None`.
- Use modern syntax supported by the minimum Python version, such as
  `str | None`, `list[str]`, and `dict[str, int]` on Python 3.10 and later.
- Prefer precise domain types, enums, dataclasses, `TypedDict`, and `Protocol`
  over unstructured dictionaries or nominal base classes created only for
  typing.
- Use `Any` only at an unavoidable dynamic boundary. Narrow or validate it as
  soon as it enters typed code.
- Do not use `cast()` or `# type: ignore` to conceal a design error. A required
  suppression must be narrow, include the error code, and explain why it is
  safe when the reason is not obvious.
- Treat annotations as a static contract, not runtime validation. Validate
  untrusted input explicitly.
- Keep the package compatible with strict static checking where the repository
  enables it.
- Include `py.typed` in distributed typed packages and verify it is present in
  the built wheel.

## Write PEP 257 docstrings

- Document public modules, classes, functions, methods, and extension points.
- Start with a concise imperative summary ending in a period.
- Keep one-line docstrings on one line when they remain readable.
- For multi-line docstrings, place a blank line after the summary and put the
  closing quotes on their own line.
- Use Google-style sections compatible with mkdocstrings: `Args`, `Returns`,
  `Yields`, `Raises`, `Attributes`, and `Examples` as applicable.
- Describe behavior, invariants, side effects, units, exceptions, and ownership
  rules that cannot be inferred from the signature.
- Do not duplicate type annotations in docstring prose.
- Document private code only when its contract or reasoning is non-obvious.
- Keep docstrings synchronized with implementation changes.

Configure Ruff's pydocstyle rules with:

```toml
[tool.ruff.lint.pydocstyle]
convention = "google"
```

Google-style structure and PEP 257 are complementary: Google style supplies
section syntax while PEP 257 supplies the underlying docstring conventions.

## Package projects using modern standards

- Use `pyproject.toml` as the source of build-system and project metadata.
- Prefer a `src/` layout for distributable packages to prevent accidental
  imports from the working tree.
- Keep the distribution name separate from the import-package name when
  normalization requires it, for example `stateforge-agent` and
  `stateforge_agent`.
- Declare runtime dependencies in `[project].dependencies`. Keep test,
  documentation, lint, and build tools out of runtime dependencies.
- Declare executable commands in `[project.scripts]` and point them at a small,
  typed callable.
- Keep package imports free of installation, network, filesystem, and process
  startup side effects.
- Build both a wheel and source distribution with a standards-compliant build
  frontend. Test the installed artifact, not only the source tree.
- Inspect artifacts to ensure required licenses, type markers, and package data
  are included and development files are excluded.
- Do not add `setup.py` or `setup.cfg` when `pyproject.toml` fully supports the
  project.
- Use normalized versions and valid core metadata. Do not invent packaging
  fields outside their specified tables.

Use this baseline layout unless the repository has a justified alternative:

```text
project/
├── LICENSE
├── README.md
├── pyproject.toml
├── mkdocs.yml
├── docs/
├── src/
│   └── package_name/
│       ├── __init__.py
│       └── py.typed
└── tests/
```

## Build documentation as part of the product

- Use MkDocs with the Material for MkDocs theme.
- Generate API documentation from docstrings with mkdocstrings and its Python
  handler.
- Keep conceptual guides in `docs/`; keep API facts in code docstrings. Avoid
  maintaining the same authoritative information in both places.
- Document public APIs and supported extension points. Do not expose private
  modules merely because mkdocstrings can discover them.
- Give pages descriptive titles, a logical navigation hierarchy, and working
  relative links.
- Include runnable examples for public workflows and keep secrets, private
  endpoints, and machine-specific paths out of examples.
- Treat warnings from `mkdocs build --strict` as failures.
- Update documentation dependencies through the project's established
  dependency mechanism. The required packages are `mkdocs`,
  `mkdocs-material`, and `mkdocstrings[python]`.

Use this as a minimal `mkdocs.yml` foundation, adapted to the project:

```yaml
site_name: StateForge

theme:
  name: material

plugins:
  - search
  - mkdocstrings:
      default_handler: python
      handlers:
        python:
          options:
            docstring_style: google
            members_order: source
            show_source: true
```

Reference public objects with their fully qualified import paths:

```markdown
::: package_name.public_module.PublicClass
```

## Test behavior and distributions

- Treat automated tests as behavioral gates. Do not substitute ad hoc manual
  tests, and do not manually review test structure unless the user requests it.
- Mirror important source areas under `tests/` without coupling tests to every
  private implementation detail.
- Test public behavior, failure modes, lifecycle boundaries, and regressions.
- Use fixtures for reusable setup and mocks only at true external boundaries.
- Prefer deterministic tests without real network access, wall-clock timing,
  or shared global state.
- Add integration tests where module boundaries, subprocesses, persistence, or
  protocols are part of the behavior.
- Verify that the wheel installs in a clean environment, imports correctly,
  includes `py.typed`, and exposes its console scripts.

## Validate before completion

Use the commands configured by the repository. A typical StateForge Python
validation sequence is:

```bash
ruff format --check .
ruff check .
mypy src
pytest
python -m build
mkdocs build --strict
```

Run only applicable checks, but do not claim completion without saying which
ones ran. If a required dependency is unavailable, report that limitation and
leave the exact command the maintainer should run.

## Consult the authoritative references

Use current upstream documentation when a rule or tool behavior is uncertain:

- [The Hitchhiker's Guide to Python](https://github.com/realpython/python-guide)
- [Python Packaging User Guide](https://packaging.python.org/)
- [PEP 8](https://peps.python.org/pep-0008/)
- [PEP 257](https://peps.python.org/pep-0257/)
- [PEP 484](https://peps.python.org/pep-0484/)
- [MkDocs](https://www.mkdocs.org/)
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)
- [mkdocstrings](https://mkdocstrings.github.io/)

Do not rely on the Python Guide when it conflicts with an accepted modern
packaging specification or a supported project's explicit configuration.
