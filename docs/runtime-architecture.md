# Runtime package ownership

Provider authors use the public `stateforge_provider` API. The private package
layout keeps endpoint infrastructure separate from the implementation of each
SFP procedure:

```text
stateforge_provider/
  _runtime/             # shared endpoint and process infrastructure
  _services/
    bootstrap/           # Handshake implementation and local message limits
    health/              # Standard gRPC Health adaptation and bounded Watch
    manifest/            # Manifest declaration, validation, and RPC service
```

## Shared runtime

`_runtime` owns process-wide infrastructure shared by all procedures:

- Provider configuration and operational capacity;
- stable installation identity and endpoint generations;
- protected filesystem I/O, sockets, and descriptor publication;
- negotiated-session storage;
- endpoint startup, shutdown, and cleanup; and
- bounded gRPC registration.

The gRPC endpoint receives a collection of procedure registrations. Each
registration supplies its exact request and response limits. The endpoint uses
the largest registered values only as transport safety ceilings; it does not
import one procedure's limits or preconfigure limits for unimplemented
procedures.

## Procedure services

Each `_services/<procedure>` package owns that procedure's implementation,
including its servicer, validation, declarations where applicable, and
serialized-message limits. A handler still enforces its own exact limit even
when the shared endpoint ceiling is larger because another procedure is
registered.

Versioned protobuf messages, generated bindings, and contract constants remain
in `stateforge_protocol.sfp.<procedure>.v1`. The Provider library imports those
contracts; it does not copy or regenerate them.

Health is the intentional exception to that generated-module path: it uses the
official `grpc.health.v1` bindings from `grpcio-health-checking`, registers the
actual hosted SFP service names, and adds no StateForge health protobuf.

To add a future procedure:

1. create one `_services/<procedure>` package;
2. implement and test its versioned request and response boundaries;
3. expose one `ProcedureRegistration`; and
4. include that registration when composing the Provider generation.

Adding a procedure must not require changing Manifest declaration, schema, or
service modules. This private organization does not change the public
Provider-authoring API.
