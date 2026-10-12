"""Expose the typed Provider health states available to authors."""

from __future__ import annotations

from enum import StrEnum
from typing import Self


class HealthStatus(StrEnum):
    """Describe whether a Provider process can accept new SFP work.

    The Provider runtime maps every non-serving state to standard gRPC
    ``NOT_SERVING``. The additional states let author code communicate intent
    without exposing protobuf values or vendor diagnostics.
    """

    SERVING = "serving"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"
    NOT_SERVING = "not_serving"

    @property
    def is_serving(self) -> bool:
        """Return whether the status permits new SFP work."""
        return self is HealthStatus.SERVING

    @classmethod
    def healthy(cls) -> Self:
        """Return the normal ready-to-serve state."""
        return cls.SERVING

    @classmethod
    def degraded(cls) -> Self:
        """Return a fail-closed degraded state."""
        return cls.DEGRADED

    @classmethod
    def maintenance(cls) -> Self:
        """Return a fail-closed maintenance state."""
        return cls.MAINTENANCE

    @classmethod
    def not_serving(cls) -> Self:
        """Return the generic fail-closed state."""
        return cls.NOT_SERVING
