from pathlib import Path


def test_pyproject_declares_core_runtime_and_dev_extra() -> None:
    content = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'name = "general-mini-agent-framework"' in content
    assert '"httpx>=0.27.0"' in content
    assert "dev = [" in content
    assert '"pytest>=8.0.0"' in content
    assert '"ruff>=' in content


def test_pyproject_declares_version_0_5_0() -> None:
    content = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'version = "0.5.0"' in content
