"""Represent StateForge Protocol wire versions supported by a Provider."""

from dataclasses import dataclass

from stateforge_protocol.sfp.bootstrap.v1 import validation


@dataclass(frozen=True, order=True, slots=True)
class ProtocolVersion:
    """One supported SFP wire version."""

    major: int
    minor: int

    def __post_init__(self) -> None:
        """Reject values that cannot be represented by the wire schema."""
        try:
            validation.validate_protocol_version(self.major, self.minor)
        except validation.BootstrapValidationError as error:
            raise ValueError(str(error)) from error

    def __str__(self) -> str:
        """Return the canonical MAJOR.MINOR representation."""
        return f"{self.major}.{self.minor}"


SUPPORTED_SFP_VERSIONS: tuple[ProtocolVersion, ...] = (
    ProtocolVersion(major=1, minor=0),
)
"""SFP wire versions this Developer RPC Library release negotiates."""
