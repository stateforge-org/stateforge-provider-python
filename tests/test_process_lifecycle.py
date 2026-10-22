"""Verify process outcomes through the standard Provider entry point."""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

_FIXTURE = Path(__file__).parent / "fixtures" / "process" / "provider.py"
_SOURCE_DIRECTORY = Path(__file__).parents[1] / "src"
_TIMEOUT_SECONDS = 10


@pytest.fixture
def runtime_directory() -> Iterator[Path]:
    """Provide a short path suitable for Unix-domain sockets."""
    directory = Path(tempfile.mkdtemp(prefix="sfp-process-", dir="/tmp"))
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _command(mode: str, runtime_directory: Path) -> list[str]:
    return [sys.executable, str(_FIXTURE), mode, str(runtime_directory)]


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH")
    source_path = str(_SOURCE_DIRECTORY)
    environment["PYTHONPATH"] = (
        os.pathsep.join((source_path, existing_path))
        if existing_path
        else source_path
    )
    return environment


def _run(
    mode: str,
    runtime_directory: Path,
) -> subprocess.CompletedProcess[str]:
    # The executable and fixture path are controlled by this test suite.
    return subprocess.run(  # noqa: S603
        _command(mode, runtime_directory),
        check=False,
        capture_output=True,
        env=_environment(),
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )


def _events(runtime_directory: Path) -> list[str]:
    return (runtime_directory / "events.txt").read_text().splitlines()


def _assert_endpoint_removed(runtime_directory: Path) -> None:
    discovery_directory = runtime_directory / "discovery"
    assert not tuple(discovery_directory.glob("*.sfp.json"))
    assert not tuple(discovery_directory.glob("*.sock"))


def _wait_until_discoverable(
    process: subprocess.Popen[str],
    runtime_directory: Path,
) -> None:
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    discovery_directory = runtime_directory / "discovery"
    while time.monotonic() < deadline:
        if tuple(discovery_directory.glob("*.sfp.json")):
            return
        return_code = process.poll()
        if return_code is not None:
            stdout, stderr = process.communicate()
            pytest.fail(
                "Provider exited before publishing its endpoint: "
                f"status={return_code}, stdout={stdout!r}, stderr={stderr!r}"
            )
        time.sleep(0.01)
    pytest.fail("Provider did not publish its endpoint before the timeout")


def test_normal_completion_returns_success(
    runtime_directory: Path,
) -> None:
    completed = _run("normal", runtime_directory)

    assert completed.returncode == 0, completed.stderr
    assert _events(runtime_directory) == ["startup", "shutdown"]
    _assert_endpoint_removed(runtime_directory)


@pytest.mark.skipif(
    os.name != "posix",
    reason="The Provider runtime uses Unix-domain sockets and POSIX signals",
)
@pytest.mark.parametrize(
    "signal_number",
    [signal.SIGINT, signal.SIGTERM],
    ids=["SIGINT", "SIGTERM"],
)
def test_supported_signals_request_graceful_shutdown(
    runtime_directory: Path,
    signal_number: signal.Signals,
) -> None:
    # The executable and fixture path are controlled by this test suite.
    process = subprocess.Popen(  # noqa: S603
        _command("signal", runtime_directory),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_environment(),
        text=True,
    )
    try:
        _wait_until_discoverable(process, runtime_directory)
        process.send_signal(signal_number)
        stdout, stderr = process.communicate(timeout=_TIMEOUT_SECONDS)
    except BaseException:
        process.kill()
        process.communicate()
        raise

    assert process.returncode == 0, (stdout, stderr)
    assert _events(runtime_directory) == ["startup", "shutdown"]
    _assert_endpoint_removed(runtime_directory)


@pytest.mark.parametrize(
    ("mode", "diagnostic"),
    [
        ("startup-failure", "simulated Provider startup failure"),
        ("shutdown-failure", "simulated Provider shutdown failure"),
    ],
)
def test_fatal_lifecycle_failure_uses_python_failure_status(
    runtime_directory: Path,
    mode: str,
    diagnostic: str,
) -> None:
    completed = _run(mode, runtime_directory)

    assert completed.returncode == 1
    assert diagnostic in completed.stderr
    assert _events(runtime_directory) == ["startup", "shutdown"]
    _assert_endpoint_removed(runtime_directory)


def test_health_failure_is_not_a_process_failure(
    runtime_directory: Path,
) -> None:
    completed = _run("health-failure", runtime_directory)

    assert completed.returncode == 0, completed.stderr
    assert "Provider health hook failed; reporting NOT_SERVING" in (
        completed.stderr
    )
    assert "simulated Provider health failure" in completed.stderr
    assert _events(runtime_directory) == ["startup", "shutdown"]
    _assert_endpoint_removed(runtime_directory)
