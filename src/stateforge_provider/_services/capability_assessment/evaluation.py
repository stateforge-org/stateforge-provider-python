"""Evaluate Provider-owned runtime requirements through one shared path."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from stateforge_provider._services.capability_assessment.declaration import (
    BoundRequirementRegistry,
    RequirementDeclaration,
)
from stateforge_provider.requirements import RequirementCheckResult

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EvaluatedRequirement:
    """Pair validated declaration metadata with one author result."""

    declaration: RequirementDeclaration
    result: RequirementCheckResult


class RequirementEvaluationError(RuntimeError):
    """Hide author check failures from remote protocol boundaries."""


def required_checks(
    requirements: BoundRequirementRegistry,
    operation_identifiers: tuple[str, ...],
) -> tuple[str, ...]:
    """Collect unique checks in stable first-reference order."""
    identifiers: list[str] = []
    seen: set[str] = set()
    for operation in operation_identifiers:
        for identifier in requirements.operation_requirements[operation]:
            if identifier not in seen:
                seen.add(identifier)
                identifiers.append(identifier)
    return tuple(identifiers)


async def evaluate_requirements(
    requirements: BoundRequirementRegistry,
    identifiers: tuple[str, ...],
) -> dict[str, EvaluatedRequirement]:
    """Run each distinct author check once and cancel peers on failure."""
    tasks = {
        identifier: asyncio.create_task(
            _invoke_check(requirements, identifier),
            name=f"stateforge-requirement-{identifier}",
        )
        for identifier in identifiers
    }
    try:
        values = await asyncio.gather(*tasks.values())
    except BaseException:
        for task in tasks.values():
            task.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        raise
    return dict(zip(tasks, values, strict=True))


async def _invoke_check(
    requirements: BoundRequirementRegistry,
    identifier: str,
) -> EvaluatedRequirement:
    """Normalize one author check without leaking its failure remotely."""
    check = requirements.checks[identifier]
    try:
        result: object = await check()
    except asyncio.CancelledError:
        raise
    except Exception:
        _LOGGER.exception(
            "Provider requirement check failed",
            extra={"requirement_id": identifier},
        )
        raise RequirementEvaluationError from None
    if not isinstance(result, RequirementCheckResult):
        _LOGGER.error(
            "Provider requirement check returned an invalid result",
            extra={"requirement_id": identifier},
        )
        raise RequirementEvaluationError
    return EvaluatedRequirement(
        requirements.declarations[identifier],
        result,
    )
