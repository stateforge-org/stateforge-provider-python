"""Validate durable Trigger Publication evidence in an installed Agent."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from uuid import UUID

from stateforge_protocol.sfp.trigger_publication.v1 import (
    trigger_publication_pb2,
    validation,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--provider-instance-id", type=UUID, required=True)
    parser.add_argument("--expected-trigger", action="append", required=True)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    return parser.parse_args()


def _rows(
    database: Path,
    provider_instance_id: UUID,
) -> list[sqlite3.Row]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        return list(
            connection.execute(
                """
                SELECT publication_id, content_fingerprint, publication,
                       trigger_identifier, observed_at, endpoint_generation,
                       session_id, manifest_revision, accepted_at,
                       forwarding_state
                FROM trigger_publications
                WHERE provider_instance_id = ?
                ORDER BY accepted_at, publication_id
                """,
                (str(provider_instance_id),),
            )
        )
    finally:
        connection.close()


def _validated_evidence(
    rows: list[sqlite3.Row],
    expected_triggers: list[str],
) -> dict[str, object]:
    actual = [str(row["trigger_identifier"]) for row in rows]
    if sorted(actual) != sorted(expected_triggers):
        raise ValueError(
            "Durable publications do not match the expected trigger set"
        )

    publications: list[dict[str, object]] = []
    for row in rows:
        publication = trigger_publication_pb2.TriggerPublication.FromString(
            row["publication"]
        )
        validation.validate_trigger_publication(publication)
        fingerprint = validation.compute_publication_content_fingerprint(
            publication
        )
        if publication.publication_id != row["publication_id"]:
            raise ValueError("Stored publication identity is inconsistent")
        if publication.trigger_identifier != row["trigger_identifier"]:
            raise ValueError("Stored trigger identifier is inconsistent")
        if fingerprint != row["content_fingerprint"]:
            raise ValueError("Stored publication fingerprint is inconsistent")
        if row["forwarding_state"] != "pending":
            raise ValueError(
                "Accepted publication lost pending responsibility"
            )
        publications.append(
            {
                "accepted_at": row["accepted_at"],
                "content_fingerprint": fingerprint,
                "endpoint_generation": row["endpoint_generation"],
                "forwarding_state": row["forwarding_state"],
                "manifest_revision": row["manifest_revision"],
                "observed_at": row["observed_at"],
                "publication_id": publication.publication_id,
                "session_id_sha256": hashlib.sha256(
                    row["session_id"].encode()
                ).hexdigest(),
                "trigger_identifier": publication.trigger_identifier,
            }
        )
    return {
        "publication_count": len(publications),
        "publications": publications,
    }


def main() -> None:
    """Wait for, validate, and emit the expected durable evidence."""
    arguments = _arguments()
    if arguments.timeout_seconds <= 0:
        raise ValueError("timeout-seconds must be positive")
    deadline = time.monotonic() + arguments.timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            evidence = _validated_evidence(
                _rows(arguments.database, arguments.provider_instance_id),
                arguments.expected_trigger,
            )
        except (OSError, sqlite3.Error, ValueError) as error:
            last_error = error
            time.sleep(0.25)
            continue
        sys.stdout.write(json.dumps(evidence, indent=2, sort_keys=True))
        sys.stdout.write("\n")
        return
    raise RuntimeError(
        "Installed Agent did not retain the expected trigger publications"
    ) from last_error


if __name__ == "__main__":
    main()
