"""Bind accepted operation declarations to one Provider instance."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator

from stateforge_provider._services.manifest.declaration import (
    OperationDeclaration,
)
from stateforge_provider.declarations import ProviderModel

_BoundHandler = Callable[..., Awaitable[ProviderModel]]


@dataclass(frozen=True, slots=True)
class BoundOperation:
    """Pair one accepted declaration with its bound author handler."""

    declaration: OperationDeclaration
    handler: _BoundHandler
    input_validator: Draft202012Validator
    result_validator: Draft202012Validator


@dataclass(frozen=True, slots=True)
class BoundOperationRegistry:
    """Resolve exact manifest-declared operations for one Provider instance."""

    operations: dict[str, BoundOperation]

    @classmethod
    def bind(
        cls,
        provider: object,
        declarations: tuple[OperationDeclaration, ...],
        schemas: dict[str, tuple[dict[str, Any], dict[str, Any]]],
    ) -> BoundOperationRegistry:
        """Bind declarations to the methods used to create the manifest."""
        operations: dict[str, BoundOperation] = {}
        for declaration in declarations:
            handler = getattr(provider, declaration.method_name, None)
            if not callable(handler):
                raise TypeError(
                    "Accepted operation handler is unavailable: "
                    f"{declaration.identifier}"
                )
            input_schema, result_schema = schemas[declaration.identifier]
            operations[declaration.identifier] = BoundOperation(
                declaration=declaration,
                handler=handler,
                input_validator=Draft202012Validator(input_schema),
                result_validator=Draft202012Validator(result_schema),
            )
        return cls(operations)

    def get(self, identifier: str) -> BoundOperation | None:
        """Return one exact declared operation without normalization."""
        return self.operations.get(identifier)
