"""Expose typed author results for dynamic runtime requirement checks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RequirementCheckOutcome(StrEnum):
    """Describe one Provider-owned runtime prerequisite outcome."""

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    INCOMPATIBLE = "incompatible"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class RequirementCheckResult:
    """Return a requirement outcome without exposing SFP wire models.

    ``explanation`` is optional for satisfied and unsatisfied results. It is
    used as the sanitized reason for incompatible and unknown results. The
    runtime validates any emitted diagnostic against the Protocol contract.
    """

    outcome: RequirementCheckOutcome
    explanation: str = ""

    def __post_init__(self) -> None:
        """Reject values outside the author-facing result vocabulary."""
        if not isinstance(self.outcome, RequirementCheckOutcome):
            raise TypeError("outcome must be a RequirementCheckOutcome")
        if not isinstance(self.explanation, str):
            raise TypeError("explanation must be a string")

    @classmethod
    def satisfied(cls) -> RequirementCheckResult:
        """Report that the runtime prerequisite is currently met."""
        return cls(RequirementCheckOutcome.SATISFIED)

    @classmethod
    def unsatisfied(cls, explanation: str = "") -> RequirementCheckResult:
        """Report an unmet prerequisite that can be satisfied later."""
        return cls(RequirementCheckOutcome.UNSATISFIED, explanation)

    @classmethod
    def incompatible(cls, explanation: str = "") -> RequirementCheckResult:
        """Report evidence that proves the operation cannot be supported."""
        return cls(RequirementCheckOutcome.INCOMPATIBLE, explanation)

    @classmethod
    def unknown(cls, explanation: str = "") -> RequirementCheckResult:
        """Report that available evidence cannot establish satisfaction."""
        return cls(RequirementCheckOutcome.UNKNOWN, explanation)
