"""Validate bounded Manifest JSON and embedded schemas without retrieval."""

from __future__ import annotations

import io
import json
from collections import deque
from functools import lru_cache
from importlib.resources import files
from typing import Any

import rfc8785
from jsonschema import Draft202012Validator
from referencing import Registry
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from stateforge_rpc._runtime.configuration import (
    DEFAULT_RUNTIME_LIMITS,
    ProviderRuntimeLimits,
)
from stateforge_rpc._services.manifest.limits import (
    MAX_CANONICAL_REVISION_PREIMAGE_BYTES,
    MAX_EMBEDDED_JSON_DEPTH,
)

JSON_SCHEMA_DRAFT_2020_12_URI = str(Draft202012Validator.META_SCHEMA["$id"])
_SCHEMA_MAPS = (
    "$defs",
    "definitions",
    "properties",
    "patternProperties",
    "dependentSchemas",
)
_SCHEMA_LISTS = ("allOf", "anyOf", "oneOf", "prefixItems")
_SCHEMA_SINGLE = (
    "additionalProperties",
    "unevaluatedProperties",
    "propertyNames",
    "items",
    "unevaluatedItems",
    "contains",
    "not",
    "if",
    "then",
    "else",
    "contentSchema",
)
_SAME_INSTANCE = {
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "if",
    "then",
    "else",
    "dependentSchemas",
}
_VALUES = {"default", "examples", "const", "enum"}


class ManifestError(ValueError):
    """Report an invalid declaration without including its values."""


# Keep size, type, and depth checks in one bounded traversal.
def bounded_json(  # noqa: PLR0912
    value: object,
    path: str,
    *,
    depth_limit: int = MAX_EMBEDDED_JSON_DEPTH,
    limits: ProviderRuntimeLimits = DEFAULT_RUNTIME_LIMITS,
) -> None:
    """Reject excessive/non-JSON content before schema or protobuf work."""
    pending = [(value, 0)]
    nodes = 0
    size = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if (
            nodes > limits.max_json_nodes
            or size > MAX_CANONICAL_REVISION_PREIMAGE_BYTES
        ):
            raise ManifestError(f"{path}: JSON resource limit exceeded")
        if isinstance(item, (dict, list)):
            depth += 1
            if depth > depth_limit:
                raise ManifestError(f"{path}: JSON nesting limit exceeded")
            if len(item) > limits.max_json_nodes:
                raise ManifestError(f"{path}: JSON resource limit exceeded")
            size += len(item) + 2
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise ManifestError(
                            f"{path}: JSON keys must be strings"
                        )
                    pending.append((key, depth))
                    pending.append((child, depth))
            else:
                pending.extend((child, depth) for child in item)
        elif isinstance(item, str):
            if len(item) > MAX_CANONICAL_REVISION_PREIMAGE_BYTES:
                raise ManifestError(f"{path}: JSON resource limit exceeded")
            try:
                size += len(item.encode("utf-8")) + 2
            except UnicodeError:
                raise ManifestError(f"{path}: invalid Unicode") from None
        elif item is None or isinstance(item, (bool, int, float)):
            size += 1
        else:
            raise ManifestError(f"{path}: non-JSON value")
    if size > MAX_CANONICAL_REVISION_PREIMAGE_BYTES:
        raise ManifestError(f"{path}: JSON resource limit exceeded")


class _BoundedBuffer(io.BytesIO):
    def write(self, data: bytes, /) -> int:  # type: ignore[override]
        # RFC 8785 writes bytes; enforce the limit while canonicalizing.
        if self.tell() + len(data) > MAX_CANONICAL_REVISION_PREIMAGE_BYTES:
            raise ManifestError("manifest: canonical preimage limit exceeded")
        return super().write(data)


def canonical_bytes(value: dict[str, Any]) -> bytes:
    """Produce RFC 8785 bytes with a bounded output buffer."""
    stream = _BoundedBuffer()
    try:
        rfc8785.dump(value, stream)
    except rfc8785.CanonicalizationError:
        raise ManifestError("manifest: non-interoperable JSON value") from None
    return stream.getvalue()


@lru_cache(maxsize=16)
def contract_validator(definition: str) -> Draft202012Validator:
    """Load a validation projection from the installed Protocol package."""
    document = json.loads(
        files("stateforge_protocol.sfp.manifest.v1")
        .joinpath("manifest.schema.json")
        .read_text()
    )
    return Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": document["$defs"]},
    )


def validate_structure(value: object, definition: str, path: str) -> None:
    """Validate the packaged P1 shape without echoing values or schema keys."""
    error = next(contract_validator(definition).iter_errors(value), None)
    if error is not None:
        # Schema paths are runtime-owned; instance keys can contain secrets.
        rule = error.validator
        raise ManifestError(f"{path}: violates P1 {rule} constraint")


# Review reference and secret rules together; all graph walks are bounded.
def validate_schema(  # noqa: PLR0912, PLR0915
    document: dict[str, Any],
    path: str,
    *,
    limits: ProviderRuntimeLimits = DEFAULT_RUNTIME_LIMITS,
) -> None:
    """Resolve local schema references and reject indirect secret values.

    A graph separates schemas applied to the same instance (composition and
    references) from child schemas. Secret annotations propagate across the
    former; values on a secret, below it, or on its ancestors are forbidden.
    Cycles are handled with finite graph traversals, without fetching URLs.
    """
    bounded_json(document, path, limits=limits)
    canonical_bytes(document)
    validate_structure(document, "schemaDocument", path)
    nodes: dict[int, dict[str, Any]] = {}
    children: dict[int, set[int]] = {}
    same: dict[int, set[int]] = {}
    pending = [document]
    while pending:
        node = pending.pop()
        key = id(node)
        if key in nodes:
            continue
        if (
            node.get("$schema", JSON_SCHEMA_DRAFT_2020_12_URI)
            != JSON_SCHEMA_DRAFT_2020_12_URI
        ):
            raise ManifestError(f"{path}: unsupported nested schema dialect")
        nodes[key] = node
        if len(nodes) > limits.max_schema_nodes:
            raise ManifestError(f"{path}: schema node limit exceeded")
        children.setdefault(key, set())
        same.setdefault(key, set())
        for keyword, value in node.items():
            candidates = []
            if keyword in _SCHEMA_MAPS and isinstance(value, dict):
                candidates = list(value.values())
            elif keyword in _SCHEMA_LISTS and isinstance(value, list):
                candidates = value
            elif keyword in _SCHEMA_SINGLE:
                candidates = [value]
            for child in candidates:
                if isinstance(child, dict):
                    pending.append(child)
                    # Definitions do not apply until referenced.
                    if keyword not in {"$defs", "definitions"}:
                        children[key].add(id(child))
                    if keyword in _SAME_INSTANCE:
                        same[key].add(id(child))
                        same.setdefault(id(child), set()).add(key)

    resource = DRAFT202012.create_resource(document)
    registry: Registry[Any] = Registry().with_resource("", resource)
    resolver = registry.resolver("")
    for key, node in nodes.items():
        for keyword in ("$ref", "$dynamicRef"):
            if keyword not in node:
                continue
            try:
                target = resolver.lookup(node[keyword]).contents
            except Unresolvable:
                raise ManifestError(
                    f"{path}: unresolved local reference"
                ) from None
            if isinstance(target, bool):
                continue
            if not isinstance(target, dict) or id(target) not in nodes:
                raise ManifestError(
                    f"{path}: reference does not name a schema"
                )
            children[key].add(id(target))
            same[key].add(id(target))
            same[id(target)].add(key)

    secrets = {
        key for key, node in nodes.items() if node.get("writeOnly") is True
    }
    effective = _reachable(secrets, same)
    below = _reachable(effective, children)
    parents: dict[int, set[int]] = {key: set() for key in nodes}
    for key, links in children.items():
        for child in links:
            parents[child].add(key)
    protected = below | _reachable(effective, parents)
    for key in protected:
        if _VALUES.intersection(nodes[key]):
            raise ManifestError(
                f"{path}: secret schema contains value annotations"
            )


def _reachable(roots: set[int], edges: dict[int, set[int]]) -> set[int]:
    visited = set(roots)
    pending = deque(roots)
    while pending:
        for child in edges[pending.popleft()]:
            if child not in visited:
                visited.add(child)
                pending.append(child)
    return visited
