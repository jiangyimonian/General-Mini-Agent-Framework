from pathlib import Path


def test_pyproject_declares_core_runtime_and_dev_extra() -> None:
    content = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "general-mini-agent-framework"' in content
    assert '"httpx>=0.27.0"' in content
    assert "dev = [" in content
    assert '"pytest>=8.0.0"' in content
    assert '"ruff>=' in content


def test_pyproject_declares_version_1_2_1() -> None:
    content = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'version = "1.2.1"' in content


def test_ci_verifies_installed_wheel_against_project_version() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'EXPECTED_VERSION="$(python -c' in workflow
    assert 'cd "$RUNNER_TEMP"' in workflow
    assert 'installed_version = version("general-mini-agent-framework")' in workflow
    assert 'assert installed_version == os.environ["EXPECTED_VERSION"]' in workflow
    assert (
        "Path(general_mini_agent.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())"
        in workflow
    )


def test_ci_actions_use_node24_releases() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v5" in workflow
    assert "actions/setup-python@v6" in workflow
