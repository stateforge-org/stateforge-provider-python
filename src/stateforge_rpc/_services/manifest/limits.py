"""Expose versioned Manifest Exchange resource limits locally."""

from stateforge_protocol.sfp.manifest.v1 import contract

MAX_CANONICAL_REVISION_PREIMAGE_BYTES = (
    contract.MAX_CANONICAL_REVISION_PREIMAGE_BYTES
)
MAX_EMBEDDED_JSON_DEPTH = contract.MAX_EMBEDDED_JSON_DEPTH
MAX_REQUEST_BYTES = contract.MAX_REQUEST_BYTES
MAX_RESPONSE_BYTES = contract.MAX_RESPONSE_BYTES
