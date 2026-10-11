"""Contract tests for reusable Provider package and runtime automation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTIONS = ROOT / ".github" / "actions"
SHA_LENGTH = 40
SUPPORTED_PYTHON_COUNT = 3
SCENARIO_COUNT = 6
DOWNSTREAM_BUNDLE_CONSUMER_COUNT = 2


def read(path: Path) -> str:
    """Read one automation file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_action_library_has_focused_domain_boundaries() -> None:
    """Keep repeated operations and scenarios independently reusable."""
    expected = {
        "environment/install",
        "evidence/collect",
        "package/build",
        "package/verify-installed",
        "protocol/build",
        "provider/crash",
        "provider/create-fixture",
        "provider/start",
        "provider/stop",
        "scenarios/adversarial/invalid-peer",
        "scenarios/destructive/uninstall-reinstall",
        "scenarios/lifecycle/concurrent-providers",
        "scenarios/lifecycle/same-instance-replacement",
        "scenarios/resilience/crash-restart",
        "scenarios/smoke/normal-lifecycle",
        "sfp/assert-bootstrap",
        "sfp/assert-invalid-peer",
        "sfp/assert-manifest",
    }
    observed = {
        str(path.parent.relative_to(ACTIONS))
        for path in ACTIONS.rglob("action.yml")
    }
    assert observed == expected


def test_build_is_single_and_provenance_bound() -> None:
    """Build each package once and pass one immutable bundle downstream."""
    build = read(WORKFLOWS / "provider-build.yml")
    aggregate = read(WORKFLOWS / "provider-build-and-verify.yml")
    provider = read(ACTIONS / "package" / "build" / "action.yml")
    protocol = read(ACTIONS / "protocol" / "build" / "action.yml")

    assert "python -m build" in provider
    assert "python -m build" in protocol
    assert build.count("./.github/actions/package/build") == 1
    assert build.count("./.github/actions/protocol/build") == 1
    assert "dist/BUNDLE_PROVENANCE" in build
    assert "protocol-resolved-commit=" in build
    assert "needs: build" in aggregate
    assert (
        aggregate.count("needs.build.outputs.artifact-name")
        == DOWNSTREAM_BUNDLE_CONSUMER_COUNT
    )


def test_protocol_ref_is_configurable_and_resolved() -> None:
    """Support convenient refs while recording an immutable Protocol commit."""
    build = read(WORKFLOWS / "provider-build.yml")
    aggregate = read(WORKFLOWS / "provider-build-and-verify.yml")
    release = read(WORKFLOWS / "provider-release-candidate.yml")
    action = read(ACTIONS / "protocol" / "build" / "action.yml")

    for content in (build, aggregate, release):
        assert "protocol-ref:" in content
        assert "default: mvp/implementation" in content
    assert 'git -C "${PROTOCOL_SOURCE}" rev-parse --verify HEAD' in action
    assert "requested-ref=${PROTOCOL_REF}" in action
    assert "resolved-commit=${resolved_commit}" in action
    assert "PROTOCOL_SHA256SUMS" in action


def test_installed_checks_cannot_use_source_imports() -> None:
    """Install exact wheels outside checkouts with Python isolation enabled."""
    install = read(ACTIONS / "environment" / "install" / "action.yml")
    verify = read(ACTIONS / "package" / "verify-installed" / "action.yml")
    verifier = read(ACTIONS / "package" / "verify-installed" / "verify.py")

    assert '"${protocol_wheel}" "${provider_wheel}"' in install
    assert "python -m venv" in install
    assert "unset PYTHONPATH PYTHONHOME" in verify
    assert '"${ISOLATED_PYTHON}" -I' in verify
    assert "was imported from the checkout" in verifier
    assert 'distribution("stateforge-provider")' in verifier
    assert "stateforge_provider.__all__" in verifier


def test_fixture_uses_only_the_public_provider_api() -> None:
    """Do not reproduce or reach into private runtime implementation."""
    fixture = read(ACTIONS / "provider" / "create-fixture" / "fixture.py")

    assert "from stateforge_provider import (" in fixture
    assert "stateforge_provider._" not in fixture
    assert "Provider(" in fixture
    assert "@operation(" in fixture
    assert "on_startup" in fixture
    assert "on_shutdown" in fixture


def test_provider_start_waits_for_a_new_generation() -> None:
    """Do not confuse an existing stable descriptor with new publication."""
    action = read(ACTIONS / "provider" / "start" / "action.yml")

    assert "previous_generation=0" in action
    assert ".last_endpoint_generation // 0" in action
    assert "generation > previous_generation" in action


def test_each_runtime_scenario_is_an_independent_action() -> None:
    """Keep scenario behavior visible and composed from shared actions."""
    scenario_root = ACTIONS / "scenarios"
    scenarios = sorted(scenario_root.rglob("action.yml"))
    assert len(scenarios) == SCENARIO_COUNT
    for scenario in scenarios:
        content = read(scenario)
        assert "./.github/actions/environment/install" in content
        assert "./.github/actions/provider/create-fixture" in content
        assert "./.github/actions/evidence/collect" in content
        assert "if: ${{ always() }}" in content


def test_runtime_catalog_covers_required_behavior() -> None:
    """Keep all approved installed-runtime cases in the workflow matrix."""
    workflow = read(WORKFLOWS / "provider-runtime-scenarios.yml")
    scenarios = {
        "normal-lifecycle",
        "concurrent-providers",
        "same-instance-replacement",
        "invalid-peer",
        "crash-restart",
        "uninstall-reinstall",
    }
    for scenario in scenarios:
        assert scenario in workflow
    assert 'python: "3.11"' in workflow
    assert 'python: "3.12"' in workflow
    assert 'python-version: "3.13"' in workflow
    assert "if: ${{ inputs.scenario-tier == 'full' }}" in workflow
    assert "runtime-directory: ${{ runner.temp }}/sfp" in workflow
    assert "stateforge-provider-${{ matrix.scenario }}" not in workflow
    assert "runs-on: ubuntu-24.04" in workflow


def test_package_matrix_is_separate_from_unix_runtime() -> None:
    """Do not imply Windows support for the Unix-socket runtime."""
    installed = read(WORKFLOWS / "provider-installed-test.yml")
    runtime = read(WORKFLOWS / "provider-runtime-scenarios.yml")

    assert "windows-2022" in installed
    assert "macos-14" in installed
    assert installed.count('          - "3.1') == SUPPORTED_PYTHON_COUNT
    assert "windows-" not in runtime
    assert "macos-" not in runtime


def test_triggered_workflows_are_thin_callers() -> None:
    """Keep pull-request, integration, and release entry points declarative."""
    for filename in (
        "provider-ci.yml",
        "provider-integration.yml",
        "provider-release-candidate.yml",
    ):
        workflow = read(WORKFLOWS / filename)
        assert (
            "uses: ./.github/workflows/provider-build-and-verify.yml"
            in workflow
        )
        assert "run:" not in workflow


def test_external_actions_are_immutable() -> None:
    """Reject executable GitHub Actions referenced by mutable tags."""
    automation_files = [
        *WORKFLOWS.glob("*.yml"),
        *ACTIONS.rglob("action.yml"),
    ]
    for path in automation_files:
        for line in read(path).splitlines():
            stripped = line.strip()
            if not stripped.startswith("uses: ") or stripped.startswith(
                "uses: ./"
            ):
                continue
            reference = stripped.split("@", maxsplit=1)[1].split()[0]
            assert len(reference) == SHA_LENGTH, path
            assert all(
                character in "0123456789abcdef" for character in reference
            ), path


def test_workflow_security_and_bounds_are_explicit() -> None:
    """Preserve least privilege, bounded jobs, and credential hygiene."""
    workflows = list(WORKFLOWS.glob("*.yml"))
    combined = "\n".join(read(path) for path in workflows)

    assert "pull_request_target:" not in combined
    for path in workflows:
        content = read(path)
        assert "permissions:\n  contents: read" in content
    executable = [path for path in workflows if "runs-on:" in read(path)]
    for path in executable:
        content = read(path)
        assert "timeout-minutes:" in content
        assert "persist-credentials: false" in content
    assert "retention-days:" in combined


def test_failure_evidence_and_cleanup_are_bounded() -> None:
    """Always retain useful logs without preserving unlimited runner state."""
    collector = read(ACTIONS / "evidence" / "collect" / "action.yml")

    assert "MAX_FILE_BYTES" in collector
    assert "runner-context.txt" in collector
    assert "runtime-inventory.txt" in collector
    assert 'rm -rf -- "${RUNTIME_DIRECTORY}"' in collector
    assert "provider.pid" in collector
