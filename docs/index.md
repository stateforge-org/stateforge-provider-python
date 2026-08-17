# StateForge Provider Implementation

This project is the reference starting point for a standalone StateForge
Provider process. A Provider owns all third-party-specific behavior and
communicates with the StateForge Agent exclusively through StateForge Protocol
(SFP).

The Developer RPC Library handles the generic SFP runtime. Provider authors
implement component-specific behavior without placing vendor logic inside the
Agent.

## Process boundary

A Provider is not loaded into the Agent process. It starts its own gRPC server,
publishes its local endpoint, and accepts a connection from the Agent. The
third-party framework or component normally remains unchanged by StateForge.
