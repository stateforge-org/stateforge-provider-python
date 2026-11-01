"""Translate Operation Admission decisions into canonical gRPC status."""

from __future__ import annotations

from dataclasses import dataclass

import grpc
from google.protobuf.any_pb2 import Any
from google.rpc import status_pb2  # type: ignore[import-untyped]
from grpc_status import rpc_status
from stateforge_protocol.sfp import primitives
from stateforge_protocol.sfp.operation_admission.v1 import (
    operation_admission_pb2,
    validation,
)


@dataclass(frozen=True, slots=True)
class AdmissionFailureError(Exception):
    """Carry one sanitized typed Operation Admission rejection."""

    code: grpc.StatusCode
    reason: operation_admission_pb2.AdmissionErrorReason.ValueType
    explanation: str
    operation_id: str = ""
    retryable: bool = False

    def status(self) -> grpc.Status:
        """Build a validated rich status with one versioned detail."""
        detail = operation_admission_pb2.OperationAdmissionErrorDetail(
            operation_id=_valid_operation_id(self.operation_id),
            reason=self.reason,
            retryable=self.retryable,
            explanation=self.explanation,
        )
        validation.validate_admission_error_detail(detail)
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
    return value if primitives.is_canonical_uuid4(value) else ""
