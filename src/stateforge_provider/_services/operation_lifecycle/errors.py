"""Translate lifecycle lookup decisions into canonical rich gRPC status."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import grpc
from google.protobuf.any_pb2 import Any
from google.rpc import status_pb2  # type: ignore[import-untyped]
from grpc_status import rpc_status
from stateforge_protocol.sfp.operation_lifecycle.v1 import (
    operation_lifecycle_pb2,
    validation,
)

_UUID_VERSION = 4


@dataclass(frozen=True, slots=True)
class LifecycleFailureError(Exception):
    """Carry one sanitized typed Operation Lifecycle rejection."""

    code: grpc.StatusCode
    reason: operation_lifecycle_pb2.LifecycleErrorReason.ValueType
    explanation: str
    operation_id: str = ""

    def status(self) -> grpc.Status:
        """Build a validated rich status with one versioned detail."""
        detail = operation_lifecycle_pb2.OperationLifecycleErrorDetail(
            operation_id=_valid_operation_id(self.operation_id),
            reason=self.reason,
            explanation=self.explanation,
        )
        validation.validate_lifecycle_error_detail(detail)
        packed = Any()
        packed.Pack(detail)
        status = status_pb2.Status(
            code=self.code.value[0],
            message=self.explanation,
            details=(packed,),
        )
        return rpc_status.to_status(status)


def _valid_operation_id(value: str) -> str:
    """Return only a canonical UUIDv4 suitable for an error detail."""
    try:
        identifier = UUID(value)
    except (ValueError, AttributeError):
        return ""
    if identifier.version != _UUID_VERSION or str(identifier) != value:
        return ""
    return value
