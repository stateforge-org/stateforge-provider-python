"""Represent StateForge Protocol wire versions supported by a Provider."""

from dataclasses import dataclass

_MAXIMUM_PROTOBUF_UINT32 = (2**32) - 1


@dataclass(frozen=True, order=True, slots=True)
class ProtocolVersion:
    """One supported SFP wire version."""

    major: int
    minor: int

    def __post_init__(self) -> None:
        """Reject values that cannot be represented by the wire schema."""
        if not 1 <= self.major <= _MAXIMUM_PROTOBUF_UINT32:
            raise ValueError(
                "Protocol major version must be a positive uint32"
            )
        if not 0 <= self.minor <= _MAXIMUM_PROTOBUF_UINT32:
            raise ValueError("Protocol minor version must be a uint32")

    def __str__(self) -> str:
        """Return the canonical MAJOR.MINOR representation."""
        return f"{self.major}.{self.minor}"


SUPPORTED_SFP_VERSIONS: tuple[ProtocolVersion, ...] = (
    ProtocolVersion(major=1, minor=0),
    ProtocolVersion(major=1, minor=1),
)
"""SFP wire versions this Developer RPC Library release negotiates."""
