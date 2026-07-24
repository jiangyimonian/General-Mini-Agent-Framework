"""Documentation contract tests for the published 0.1.0 scope."""

from pathlib import Path


def test_readme_describes_only_the_stable_core_as_current_capability() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "单 Agent 同步工具调用" in readme
    assert "OpenAI 兼容" in readme
    assert "实验性" in readme
    assert "流式、多 Agent、记忆和 HTML 轨迹导出不属于 0.1.0 稳定 API" in readme
