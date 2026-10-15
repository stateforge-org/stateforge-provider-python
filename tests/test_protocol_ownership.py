"""Prevent normative SFP validation from drifting back into the Provider."""

from uuid import UUID, uuid4

import grpc
import pytest
from stateforge_protocol.sfp.bootstrap.v1 import bootstrap_pb2

from stateforge_provider._runtime.identity import ProviderEndpointIdentity
from stateforge_provider._runtime.sessions import SessionRegistry
from stateforge_provider._services.bootstrap import (
    service as bootstrap_service,
)
from stateforge_provider.version import ProtocolVersion


class _AbortError(RuntimeError):
    """Capture one fake server-context abort."""

    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        super().__init__(details)
        self.code = code


class _Context:
    """Expose the abort behavior used by the Bootstrap service."""

    async def abort(self, code: grpc.StatusCode, details: str) -> None:
        raise _AbortError(code, details)


@pytest.mark.asyncio
async def test_bootstrap_requests_cross_protocol_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    endpoint = ProviderEndpointIdentity(
        provider_instance_id=UUID("7f7db7d8-68b4-4f71-9769-065b5c4f941c"),
        endpoint_generation=1,
    )
    service = bootstrap_service.BootstrapService(
        endpoint_identity=endpoint,
        provider_runtime_id=uuid4(),
        sessions=SessionRegistry(endpoint),
    )

    def reject(_request) -> None:
        raise bootstrap_service.validation.BootstrapValidationError(
            "canonical rejection"
        )

    monkeypatch.setattr(
        bootstrap_service.validation,
        "validate_handshake_request",
        reject,
    )
    request = bootstrap_pb2.HandshakeRequest(
        agent_runtime=bootstrap_pb2.AgentRuntime(
            runtime_id=str(uuid4()),
            software_version="0.1.0",
        ),
        expected_provider_instance_id=str(endpoint.provider_instance_id),
        expected_endpoint_generation=1,
        supported_sfp_versions=[
            bootstrap_pb2.ProtocolVersion(major=1, minor=0)
        ],
    )

    with pytest.raises(_AbortError) as error:
        await service.Handshake(request, _Context())  # type: ignore[arg-type]
    assert error.value.code is grpc.StatusCode.INVALID_ARGUMENT
    assert str(error.value) == "canonical rejection"


def test_provider_version_delegates_to_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject(_major: object, _minor: object) -> None:
        raise bootstrap_service.validation.BootstrapValidationError(
            "canonical rejection"
        )

    monkeypatch.setattr(
        "stateforge_provider.version.validation.validate_protocol_version",
        reject,
    )

    with pytest.raises(ValueError, match="canonical rejection"):
        ProtocolVersion(major=1, minor=0)
