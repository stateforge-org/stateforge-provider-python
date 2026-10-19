"""Verify installed StateForge distributions without importing source trees."""

from __future__ import annotations

import argparse
import json
from importlib.metadata import distribution
from pathlib import Path

import stateforge_protocol

import stateforge_provider


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _outside(path: Path, workspace: Path) -> bool:
    try:
        path.relative_to(workspace)
    except ValueError:
        return True
    return False


def main() -> None:
    """Assert package identity, import origin, and the public API."""
    arguments = _arguments()
    workspace = arguments.workspace.resolve()
    provider_file = Path(stateforge_provider.__file__).resolve()
    protocol_file = Path(stateforge_protocol.__file__).resolve()
    if not _outside(provider_file, workspace):
        raise SystemExit("stateforge_provider was imported from the checkout")
    if not _outside(protocol_file, workspace):
        raise SystemExit("stateforge_protocol was imported from the checkout")

    provider = distribution("stateforge-provider")
    protocol = distribution("stateforge-protocol")
    if provider.metadata["Name"] != "stateforge-provider":
        raise SystemExit("Installed Provider distribution name is incorrect")
    if provider.version != arguments.expected_version:
        raise SystemExit("Installed Provider version is incorrect")

    required_api = {
        "HealthStatus",
        "ManifestError",
        "Platform",
        "ProtocolVersion",
        "Provider",
        "ProviderModel",
        "ProviderServerError",
        "RequirementCheckOutcome",
        "RequirementCheckResult",
        "RuntimeRequirement",
        "Trigger",
        "operation",
        "requirement_check",
    }
    missing = sorted(required_api.difference(stateforge_provider.__all__))
    if missing:
        raise SystemExit(f"Public Provider API is incomplete: {missing}")

    evidence = {
        "provider": {
            "file": str(provider_file),
            "name": provider.metadata["Name"],
            "version": provider.version,
        },
        "protocol": {
            "file": str(protocol_file),
            "name": protocol.metadata["Name"],
            "version": protocol.version,
        },
        "public_api": sorted(required_api),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
