"""Register bounded SFP procedures on one shared gRPC endpoint."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import grpc


@dataclass(frozen=True, slots=True)
class ProcedureRegistration:
    """Describe one procedure's installer and serialized message limits."""

    name: str
    max_request_bytes: int
    max_response_bytes: int
    install: Callable[[grpc.aio.Server], None]

    def __post_init__(self) -> None:
        """Reject incomplete or unsafe registration metadata."""
        if not self.name:
            raise ValueError("procedure registration name must not be empty")
        for field_name in ("max_request_bytes", "max_response_bytes"):
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                raise ValueError(f"{field_name} must be a positive integer")


def endpoint_message_limits(
    registrations: Sequence[ProcedureRegistration],
) -> tuple[int, int]:
    """Return shared transport ceilings for the registered procedures."""
    if not registrations:
        raise ValueError("at least one SFP procedure must be registered")
    return (
        max(item.max_request_bytes for item in registrations),
        max(item.max_response_bytes for item in registrations),
    )


def create_server(
    registrations: Sequence[ProcedureRegistration],
) -> grpc.aio.Server:
    """Create one endpoint and install every bounded procedure."""
    max_receive_bytes, max_send_bytes = endpoint_message_limits(registrations)
    server = grpc.aio.server(
        options=(
            ("grpc.max_receive_message_length", max_receive_bytes),
            ("grpc.max_send_message_length", max_send_bytes),
        )
    )
    for registration in registrations:
        registration.install(server)
    return server
