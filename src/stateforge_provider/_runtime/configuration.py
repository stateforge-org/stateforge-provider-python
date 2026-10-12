"""Define immutable operational configuration for the Provider runtime."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProviderRuntimeLimits:
    """Bound Provider-owned in-memory and validation resources."""

    max_sessions: int = 1_024
    max_json_nodes: int = 65_536
    max_schema_nodes: int = 4_096
    max_health_watchers: int = 128
    health_watch_queue_capacity: int = 16

    def __post_init__(self) -> None:
        """Reject unusable operational limits."""
        for name in (
            "max_sessions",
            "max_json_nodes",
            "max_schema_nodes",
            "max_health_watchers",
            "health_watch_queue_capacity",
        ):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 1
            ):
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_RUNTIME_LIMITS = ProviderRuntimeLimits()


@dataclass(frozen=True, slots=True)
class ProviderRuntimeConfiguration:
    """Configure one Provider process without changing SFP contracts."""

    state_directory: Path
    discovery_directory: Path
    shutdown_timeout_seconds: float = 5.0
    health_watch_delivery_timeout_seconds: float = 1.0
    limits: ProviderRuntimeLimits = field(
        default_factory=ProviderRuntimeLimits
    )

    @classmethod
    def for_provider(
        cls,
        identity: str,
        *,
        discovery_directory: Path | None = None,
        state_directory: Path | None = None,
    ) -> ProviderRuntimeConfiguration:
        """Create the reference runtime configuration for one Provider."""
        return cls(
            state_directory=(
                state_directory
                if state_directory is not None
                else Path("/var/lib/stateforge-providers") / identity
            ),
            discovery_directory=(
                discovery_directory
                if discovery_directory is not None
                else Path("/run/stateforge-agent/providers")
            ),
        )

    def __post_init__(self) -> None:
        """Validate paths and operational policy before startup."""
        for name in ("state_directory", "discovery_directory"):
            value = getattr(self, name)
            if not isinstance(value, Path) or not value.is_absolute():
                raise ValueError(f"{name} must be absolute")
        for name in (
            "shutdown_timeout_seconds",
            "health_watch_delivery_timeout_seconds",
        ):
            timeout = getattr(self, name)
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or timeout <= 0
            ):
                raise ValueError(f"{name} must be positive")
        if not isinstance(self.limits, ProviderRuntimeLimits):
            raise ValueError("limits must be ProviderRuntimeLimits")
