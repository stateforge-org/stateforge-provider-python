"""Tests for durable Provider identity and endpoint generations."""

import json
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from stateforge_provider._runtime import identity as identity_module
from stateforge_provider._runtime.identity import (
    ProviderIdentityError,
    ProviderIdentityStore,
)

_MAXIMUM_ENDPOINT_GENERATION = (2**63) - 1
_SECOND_ENDPOINT_GENERATION = 2
_STATE_FILE_MODE = 0o600


def test_allocates_stable_identity_and_monotonic_generations(
    tmp_path: Path,
) -> None:
    store = ProviderIdentityStore(tmp_path / "state")

    first = store.allocate_endpoint()
    second = ProviderIdentityStore(tmp_path / "state").allocate_endpoint()
    document = json.loads(store.state_path.read_text(encoding="utf-8"))

    assert second.provider_instance_id == first.provider_instance_id
    assert first.endpoint_generation == 1
    assert second.endpoint_generation == _SECOND_ENDPOINT_GENERATION
    assert document["provider_instance_id"] == str(first.provider_instance_id)
    assert document["last_endpoint_generation"] == _SECOND_ENDPOINT_GENERATION
    assert stat.S_IMODE(store.state_path.stat().st_mode) == _STATE_FILE_MODE


def test_serializes_concurrent_generation_allocations(tmp_path: Path) -> None:
    state_directory = tmp_path / "state"

    def allocate_generation() -> int:
        return (
            ProviderIdentityStore(state_directory)
            .allocate_endpoint()
            .endpoint_generation
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        generations = tuple(
            executor.map(lambda _: allocate_generation(), range(8))
        )

    assert sorted(generations) == list(range(1, 9))


@pytest.mark.parametrize(
    "document",
    [
        {},
        {
            "schema_version": "2",
            "provider_instance_id": "7f7db7d8-68b4-4f71-9769-065b5c4f941c",
            "last_endpoint_generation": 1,
        },
        {
            "schema_version": "1",
            "provider_instance_id": "not-a-uuid",
            "last_endpoint_generation": 1,
        },
        {
            "schema_version": "1",
            "provider_instance_id": "7f7db7d8-68b4-4f71-9769-065b5c4f941c",
            "last_endpoint_generation": True,
        },
    ],
)
def test_rejects_invalid_identity_documents(
    tmp_path: Path,
    document: dict[str, object],
) -> None:
    store = ProviderIdentityStore(tmp_path / "state")
    store.prepare()
    store.state_path.write_text(json.dumps(document), encoding="utf-8")
    store.state_path.chmod(0o600)

    with pytest.raises(ProviderIdentityError):
        store.allocate_endpoint()


def test_rejects_insecure_identity_file_mode(tmp_path: Path) -> None:
    store = ProviderIdentityStore(tmp_path / "state")
    store.allocate_endpoint()
    store.state_path.chmod(0o644)

    with pytest.raises(ProviderIdentityError, match="mode must be 0o600"):
        store.allocate_endpoint()


def test_rejects_exhausted_endpoint_generations(tmp_path: Path) -> None:
    store = ProviderIdentityStore(tmp_path / "state")
    identity = store.allocate_endpoint()
    store.state_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "provider_instance_id": str(identity.provider_instance_id),
                "last_endpoint_generation": _MAXIMUM_ENDPOINT_GENERATION,
            }
        ),
        encoding="utf-8",
    )
    store.state_path.chmod(0o600)

    with pytest.raises(ProviderIdentityError, match="space is exhausted"):
        store.allocate_endpoint()


def test_rejects_symbolic_link_state_directory(tmp_path: Path) -> None:
    real_directory = tmp_path / "real"
    real_directory.mkdir()
    linked_directory = tmp_path / "linked"
    linked_directory.symlink_to(real_directory, target_is_directory=True)

    with pytest.raises(ProviderIdentityError, match="symbolic link"):
        ProviderIdentityStore(linked_directory).allocate_endpoint()


def test_importable_package_reports_unavailable_posix_locking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep public imports portable while rejecting unsupported runtime use."""

    def unavailable(_name: str) -> None:
        raise ModuleNotFoundError("No module named 'fcntl'")

    monkeypatch.setattr(
        identity_module.importlib, "import_module", unavailable
    )
    store = ProviderIdentityStore(tmp_path / "state")

    with pytest.raises(
        ProviderIdentityError,
        match="requires POSIX advisory file locking",
    ):
        store.allocate_endpoint()

    assert not store.lock_path.exists()
