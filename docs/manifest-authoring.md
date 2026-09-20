# Manifest declarations

Provider authors declare Python metadata. The runtime validates it, creates
the P1 schema-1 manifest, calculates its revision, and serves it alongside
bootstrap on the same Unix socket. No protobuf imports, gRPC configuration,
installation identifiers, revision calculation, or session headers are part
of the declaration API.

## Minimal Provider

```python
from stateforge_rpc import Platform, Provider


class ExampleProvider(Provider):
    identity = "example.service"
    display_name = "Example Service"
    version = "1.0.0"
    target_kinds = ("example.service/resource@1",)
    platforms = (Platform("linux", "x86_64"),)


if __name__ == "__main__":
    ExampleProvider().run()
```

These five declarations are required. `identity` names the Provider **type**;
the runtime separately persists a UUIDv4 identifying this installation.
`version` is the implementation's SemVer, independent of SFP and manifest
schema versions. Target kinds are third-party resource types, never actual
customer resources or StateForge component bindings. Platforms are explicit
pairs, without wildcards or an implied Cartesian product.

The defaults declare no operations, triggers, or runtime requirements, and an
empty configuration object that rejects extra fields. Earlier bootstrap-only
Providers must add the required declarations before they can serve R1.

## Typed operations, triggers, and configuration

```python
from pydantic import SecretStr
from stateforge_rpc import (
    Platform,
    Provider,
    ProviderModel,
    RuntimeRequirement,
    Trigger,
    operation,
)


class Configuration(ProviderModel):
    endpoint: str
    token: SecretStr


class NormalizeInput(ProviderModel):
    reference: str


class NormalizeResult(ProviderModel):
    reference: str


class ReferenceProvider(Provider):
    identity = "example.reference"
    display_name = "Reference Provider"
    version = "1.0.0"
    target_kinds = ("example.reference/repository@1",)
    platforms = (Platform("linux", "x86_64"),)
    configuration_model = Configuration
    runtime_requirements = (
        RuntimeRequirement("runtime.python", "Python interpreter", ">=3.11"),
    )
    triggers = (Trigger("example.reference/changed@1", NormalizeResult),)

    @operation("example.reference/normalize@1")
    async def normalize(self, request: NormalizeInput) -> NormalizeResult:
        return NormalizeResult(reference=request.reference.strip())
```

The repository's `examples/reference_provider.py` contains a runnable example.
Use `await ReferenceProvider().serve()` in an existing event loop. Production
defaults require the provisioned state and discovery directories; tests and
local development may override `state_directory` and `discovery_directory`
with absolute, writable paths.

`ProviderModel` extends Pydantic's `BaseModel` and rejects extra fields by
default. Fields, constraints, aliases, nested models, and safe schema metadata
use Pydantic's normal APIs. Input/configuration schemas use its validation
projection; result/trigger schemas use its serialization projection. The
runtime adds the explicit Draft 2020-12 dialect and validates the object
schema. It never serializes a configured model instance into the manifest.

Decorated methods are async and currently have `(self, request)` plus typed
input and return annotations. Metadata discovery does not call them. Methods
are inherited using Python's MRO; overriding a declared method requires a new
`@operation` declaration. Duplicate operation IDs or stacked decorators are
errors. Unresolvable annotations fail startup; keep model classes importable
at module scope or declared on the Provider class.

Operation, target, and trigger identifiers use `namespace/name@major`, with at
least two lowercase dotted namespace segments and a positive major version.
An incompatible input/result contract requires a new identifier version.
Use tuples for target kinds, platforms, requirements, triggers, and roles.
Requirements are descriptive only; the runtime does not run probes or
interpret their version constraints. An empty constraint means no declared
version restriction.

## Compliance claims

Supply roles explicitly on the decorated operation:

```python
@operation(
    "example.reference/prepare@1",
    implements=("stateforge.backup.v1.prepare",),
)
async def prepare(self, request: PrepareInput) -> PrepareResult: ...
```

This illustrates claim syntax: `PrepareInput` and `PrepareResult` must come
from the exact versioned profile when that profile lands. P1 transports and
structurally validates role claims; it does not define the later P6/P7 profile
schemas. R1 consequently cannot certify backup or DR compliance. Unknown
dotted roles are transported as claims too. A consumer must validate known
roles against the matching profile before using them as compliance evidence.

Names, method bodies, docstrings, and schema payloads never imply compliance.
Every operation has only input schema, result schema, and `implements` roles.
There is no separate backup source mode, BackupEngine configuration, or
storage routing declaration.

## Schema safety and limits

Declare secret-bearing fields with `SecretStr`/`SecretBytes` or Pydantic
`Field(json_schema_extra={"writeOnly": True})`. Secret fields must be required
without defaults, including `None` defaults. Defaults, examples, constants,
and enums on secret-bearing fields are rejected, including indirect values
through local references, composition, enclosing objects, and child schemas.
The analysis is deliberately conservative: sharing a schema with a secret
field also disallows value annotations at other uses of that same schema.
Schema checking cannot identify arbitrary credentials in descriptions;
authors remain responsible for publishing only safe static metadata.

All references must be resolvable fragments within their own schema document.
`$id`, remote retrieval, and nested dialect changes are forbidden. Boolean
subschemas and recursive local references are supported. Schema-shaped data
inside an `enum` or `const` remains literal data. Invalid Unicode, non-finite
numbers, and integers outside RFC 8785's exact integer range fail validation.

P1 limits are 8 KiB per wire request, 2 MiB per wire response, 1 MiB per
canonical revision preimage, 1,024 entries per operation/trigger/requirement
map, 1,024 target kinds, 256 platform pairs, 64 roles per operation, and 64
containers of embedded nesting. This runtime additionally caps JSON at 65,536
nodes per checked document, embedded schemas at 4,096 schema nodes each, and
combined generated schema bytes at 1 MiB. It applies these bounds before
expensive validation/serialization and checks actual encoded sizes before
publication. The response budget reserves room for the largest legal session
header. Errors identify declaration sections/indexes without echoing values.

## Snapshot, sessions, and revisions

Static class declarations are inspected and frozen before `on_startup()`.
After identity allocation and successful startup, the complete response is
validated and serialized once, before descriptor publication. Mutating class
or instance metadata in or after startup cannot change that generation's
manifest. Changing declarations requires a new Provider generation.

The revision is SHA-256 of the RFC 8785 canonical P1 projection
`{manifest, manifestSchemaVersion, providerInstanceId}`, using ProtoJSON names
with defaults emitted. Set-like declarations are sorted without removing
duplicates; schema array order is preserved. Generation, session, and revision
headers are excluded. An unchanged installation and declaration retain their
revision across restarts and handshakes. The unmodified P1 golden vector is
included in this repository's tests.

Successful bootstrap stores a new opaque session in a registry owned by this
generation. Multiple handshakes may remain active on the same endpoint.
The registry retains at most 1,024 sessions, invalidating the oldest on
capacity pressure, and invalidates all of them at shutdown. Affected clients
must re-handshake. Sessions are negotiated context, not credentials or
authorization to execute an operation.

`GetManifest` checks bounded syntax, exact instance/generation/session
binding, then schema compatibility. It supports manifest schema 1 under SFP
1.0. Missing/default IDs and malformed offers yield `INVALID_ARGUMENT`;
unknown/inactive/mismatched sessions yield `FAILED_PRECONDITION`; no common
schema yields `UNIMPLEMENTED`; message limits yield `RESOURCE_EXHAUSTED`.
Snapshot failures yield sanitized `INTERNAL`. Reads never run author hooks or
operations. Transport cancellation/deadlines stop the read without changing
the declaration, and each successful call gets a complete independent reply.

Agents send `expected_session_id` from handshake in the protobuf request and
check the echoed response against both the request and their current session,
even when the revision is cached. After re-handshake, retry with the new
identifier. There is no mandatory session metadata header.

## Development dependency and scope

The Protocol prerequisite is merged PR #14 at commit
`437828a92bd30ff763ca6cc4cd1c93443985c113`. Its distribution version is still
`0.1.0`, so version resolution alone cannot distinguish earlier incomplete
artifacts. Until a release provides that distinction, install the source pin
before this package:

```sh
python -m pip install -r requirements/protocol.txt
python -m pip install -e . --group dev --group docs
```

GitHub access to the Protocol repository is required. The runtime fails closed
if the installed schema lacks the session-binding correction. This milestone
does not implement configuration loading, target assessment, dispatch,
OperationContext, trigger publication, Agent caching/routing, or vendor work.
Those remain their own milestones; these declarations are their shared input.
