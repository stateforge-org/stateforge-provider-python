"""Contract tests for reusable Provider package and runtime automation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ACTIONS = ROOT / ".github" / "actions"
SHA_LENGTH = 40
SUPPORTED_PYTHON_COUNT = 3
SCENARIO_COUNT = 7
DOWNSTREAM_BUNDLE_CONSUMER_COUNT = 3
DEPENDENCY_CHECKOUT_COUNT = 2


def read(path: Path) -> str:
    """Read one automation file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def test_action_library_has_focused_domain_boundaries() -> None:
    """Keep repeated operations and scenarios independently reusable."""
    expected = {
        "agent/assert-invalid-descriptor",
        "agent/assert-session",
        "agent/install",
        "agent/start",
        "environment/install",
        "evidence/collect",
        "package/build",
        "package/verify-installed",
        "provider/assert-health",
        "provider/crash",
        "provider/create-fixture",
        "provider/start",
        "provider/stop",
        "scenarios/adversarial/invalid-peer",
        "scenarios/destructive/uninstall-reinstall",
        "scenarios/health/standard-health",
        "scenarios/lifecycle/concurrent-providers",
        "scenarios/lifecycle/same-instance-replacement",
        "scenarios/resilience/crash-restart",
        "scenarios/smoke/normal-lifecycle",
    }
    observed = {
        str(path.parent.relative_to(ACTIONS))
        for path in ACTIONS.rglob("action.yml")
    }
    assert observed == expected


def test_build_is_single_and_provenance_bound() -> None:
    """Use each repository's builder once and pass one bundle downstream."""
    build = read(WORKFLOWS / "provider-build.yml")
    aggregate = read(WORKFLOWS / "provider-build-and-verify.yml")
    provider = read(ACTIONS / "package" / "build" / "action.yml")

    assert "python -m build" in provider
    assert build.count("./.github/actions/package/build") == 1
    assert (
        build.count("./.stateforge-ci/protocol/.github/actions/python/build")
        == 1
    )
    assert build.count("./.stateforge-ci/agent/.github/actions/rpm/build") == 1
    assert ".stateforge-ci/agent/packaging/rpm/Dockerfile.test" in build
    assert "dist/agent/test-image" in build
    assert "dist/BUNDLE_PROVENANCE" in build
    assert "protocol-resolved-commit=" in build
    assert "agent-resolved-commit=" in build
    assert "dist/agent" in build
    assert "needs: build" in aggregate
    assert (
        aggregate.count("needs.build.outputs.artifact-name")
        == DOWNSTREAM_BUNDLE_CONSUMER_COUNT
    )


def test_provider_builder_is_location_independent() -> None:
    """Allow other repositories to invoke the canonical Provider builder."""
    action = read(ACTIONS / "package" / "build" / "action.yml")

    assert "ACTION_PATH: ${{ github.action_path }}" in action
    assert "${ACTION_PATH}/../../../.." in action
    assert 'git -C "${source_directory}" rev-parse --verify HEAD' in action
    assert '"${source_directory}"' in action
    assert "${GITHUB_SHA" not in action


def test_protocol_ref_is_configurable_and_resolved() -> None:
    """Support convenient refs while recording an immutable Protocol commit."""
    build = read(WORKFLOWS / "provider-build.yml")
    aggregate = read(WORKFLOWS / "provider-build-and-verify.yml")
    release = read(WORKFLOWS / "provider-release-candidate.yml")

    for content in (build, aggregate, release):
        assert "protocol-ref:" in content
        assert "default: mvp/implementation" in content
    assert "repository: stateforge-org/stateforge-protocol" in build
    assert "git -C .stateforge-ci/protocol rev-parse --verify HEAD" in build
    assert "protocol-requested-ref=${PROTOCOL_REF}" in build


def test_agent_ref_is_configurable_and_resolved() -> None:
    """Build the exact selected Agent through its portable RPM action."""
    build = read(WORKFLOWS / "provider-build.yml")
    aggregate = read(WORKFLOWS / "provider-build-and-verify.yml")
    release = read(WORKFLOWS / "provider-release-candidate.yml")

    for content in (build, aggregate, release):
        assert "agent-ref:" in content
        assert "default: mvp/implementation" in content
    assert "repository: stateforge-org/stateforge-agent" in build
    assert "git -C .stateforge-ci/agent rev-parse --verify HEAD" in build
    assert "agent-requested-ref=${AGENT_REF}" in build
    assert "agent-rpm-sha256=${AGENT_RPM_SHA256}" in build


def test_private_dependency_checkouts_use_read_only_app_token() -> None:
    """Authenticate sibling checkouts without widening workflow permissions."""
    build = read(WORKFLOWS / "provider-build.yml")
    aggregate = read(WORKFLOWS / "provider-build-and-verify.yml")

    assert "source_app_id:" in build
    assert "source_private_key:" in build
    assert build.count("actions/create-github-app-token@") == 1
    assert "owner: stateforge-org" in build
    assert "stateforge-agent" in build
    assert "stateforge-protocol" in build
    assert "permission-contents: read" in build
    assert (
        build.count("token: ${{ steps.source-token.outputs.token }}")
        == DEPENDENCY_CHECKOUT_COUNT
    )
    assert "source_app_id: ${{ secrets.source_app_id }}" in aggregate
    assert "source_private_key: ${{ secrets.source_private_key }}" in aggregate

    for filename in (
        "provider-ci.yml",
        "provider-integration.yml",
        "provider-release-candidate.yml",
    ):
        workflow = read(WORKFLOWS / filename)
        assert "source_app_id: ${{ secrets.STATEFORGE_CI_APP_ID }}" in workflow
        assert (
            "source_private_key: "
            "${{ secrets.STATEFORGE_CI_PRIVATE_KEY }}" in workflow
        )


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


def test_source_verification_uses_the_immutable_bundle() -> None:
    """Do not resolve the unpublished Protocol dependency from PyPI."""
    source = read(WORKFLOWS / "provider-source-verify.yml")
    aggregate = read(WORKFLOWS / "provider-build-and-verify.yml")

    assert "artifact-name:" in source
    assert "actions/download-artifact@" in source
    assert "stateforge_protocol-*.whl" in source
    assert "stateforge_provider-*.whl" in source
    assert "sha256sum --check SHA256SUMS" in source
    assert "--group dev" in source
    assert "--group docs" in source
    assert "    .\n" not in source
    assert (
        "source:\n    name: Verify source and automation\n    needs: build"
        in aggregate
    )


def test_fixture_uses_only_the_public_provider_api() -> None:
    """Do not reproduce or reach into private runtime implementation."""
    fixture = read(ACTIONS / "provider" / "create-fixture" / "fixture.py")

    assert "from stateforge_provider import (" in fixture
    assert "stateforge_provider._" not in fixture
    assert "Provider(" in fixture
    assert "@operation(" in fixture
    assert "on_startup" in fixture
    assert "on_shutdown" in fixture


def test_provider_start_uses_installed_runtime_in_agent_system() -> None:
    """Run public fixtures beside the RPM-installed Agent."""
    action = read(ACTIONS / "provider" / "start" / "action.yml")

    assert 'docker exec "${CONTAINER_NAME}" systemd-run' in action
    assert "/usr/bin/python3" in action
    assert "/run/stateforge-agent/providers" in action
    assert "import stateforge_provider" not in action
    assert "previous_generation=0" in action
    assert "generation > previous_generation" in action
    assert (
        'log_directory="/var/log/stateforge-provider-tests/${INSTANCE_NAME}"'
        in action
    )


def test_each_runtime_scenario_is_an_independent_action() -> None:
    """Keep scenario behavior visible and composed from shared actions."""
    scenario_root = ACTIONS / "scenarios"
    scenarios = sorted(scenario_root.rglob("action.yml"))
    assert len(scenarios) == SCENARIO_COUNT
    for scenario in scenarios:
        content = read(scenario)
        assert "./.github/actions/agent/install" in content
        assert "./.github/actions/agent/start" in content
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
        "standard-health",
    }
    for scenario in scenarios:
        assert scenario in workflow
    assert "if: ${{ inputs.scenario-tier == 'full' }}" in workflow
    assert "runtime-directory: ${{ runner.temp }}/sfp" in workflow
    assert "stateforge-provider-${{ matrix.scenario }}" not in workflow
    assert "runs-on: ubuntu-24.04" in workflow
    assert "repository: stateforge-org/stateforge-agent" not in workflow
    assert "agent-commit:" not in workflow
    assert "agent-test-image-directory:" in workflow
    assert "/agent/test-image" in workflow


def test_health_scenario_uses_standard_wire_service_and_public_hook() -> None:
    """Keep R2 coverage on the real endpoint and installed runtime bundle."""
    scenario = read(
        ACTIONS / "scenarios" / "health" / "standard-health" / "action.yml"
    )
    action = read(ACTIONS / "provider" / "assert-health" / "action.yml")
    verifier = read(
        ACTIONS / "provider" / "assert-health" / "assert_health.py"
    )
    fixture = read(ACTIONS / "provider" / "create-fixture" / "fixture.py")
    workflow = read(WORKFLOWS / "provider-runtime-scenarios.yml")

    assert "./.github/actions/agent/install" in scenario
    assert "./.github/actions/agent/start" in scenario
    assert "./.github/actions/agent/assert-session" in scenario
    assert "./.github/actions/provider/assert-health" in scenario
    assert "grpc_health.v1" in verifier
    assert "HealthStub" in verifier
    assert "SERVICE_UNKNOWN" in verifier
    assert "SIGUSR1" in verifier
    assert "HealthStatus" in fixture
    assert "refresh_health" in fixture
    assert "docker exec" in action
    assert "health:" in workflow


def test_runtime_uses_real_agent_instead_of_synthetic_sfp_client() -> None:
    """Exercise Provider behavior through the installed Agent daemon."""
    install = read(ACTIONS / "agent" / "install" / "action.yml")
    start = read(ACTIONS / "agent" / "start" / "action.yml")
    session = read(ACTIONS / "agent" / "assert-session" / "action.yml")

    assert not (ACTIONS / "sfp" / "probe.py").exists()
    assert "rpm -Uvh --nodeps" in install
    assert "agent-test-image-checksums.txt" in install
    assert "stateforge-agent.service" in start
    assert "SFP session established:" in session
    assert "Rejecting Provider manifest:" in session


def test_provider_reinstall_expands_the_wheel_inside_fedora() -> None:
    """Do not leave a container-local wheel glob for the host shell."""
    action = read(
        ACTIONS
        / "scenarios"
        / "destructive"
        / "uninstall-reinstall"
        / "action.yml"
    )

    assert 'docker exec "${CONTAINER_NAME}" bash -lc' in action
    assert "/artifacts/provider/stateforge_provider-*.whl'" in action


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
    assert "agent-journal.txt" in collector
    assert "provider-journal.txt" in collector
    assert "rpm -e stateforge-agent" in collector
