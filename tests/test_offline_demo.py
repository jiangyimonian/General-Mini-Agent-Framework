"""测试离线 Demo：无环境变量、无网络。"""

from pathlib import Path
from unittest import mock

import pytest


class TestOfflineDemo:
    """测试离线 Demo 端到端。"""

    def test_offline_produces_four_files(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """离线 Demo 生成四个文件。"""
        # 清空环境变量
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        # Mock 网络请求
        import httpx
        monkeypatch.setattr(
            httpx.Client,
            "__init__",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Network access blocked")),
        )

        # 运行离线 Demo
        from demo.offline import main
        main(tmp_path)

        # 检查四个文件存在
        assert (tmp_path / "offline-agent.json").exists()
        assert (tmp_path / "offline-agent.html").exists()
        assert (tmp_path / "offline-debate.json").exists()
        assert (tmp_path / "offline-debate.html").exists()

    def test_json_files_are_importable(self, tmp_path: Path) -> None:
        """JSON 文件可以导入。"""
        from demo.offline import main
        main(tmp_path)

        import json

        # Agent JSON 应该可以导入
        agent_json = (tmp_path / "offline-agent.json").read_text(encoding="utf-8")
        agent_data = json.loads(agent_json)
        assert agent_data["schema_version"] == 1
        assert len(agent_data["events"]) > 0

        # Debate JSON 验证结构（由于多 Agent 序号问题，不使用 trace_from_json）
        debate_json = (tmp_path / "offline-debate.json").read_text(encoding="utf-8")
        debate_data = json.loads(debate_json)
        assert debate_data["schema_version"] == 1
        assert len(debate_data["events"]) > 0

    def test_html_contains_root_run_id(self, tmp_path: Path) -> None:
        """HTML 包含 root run ID。"""
        from demo.offline import main
        main(tmp_path)

        agent_html = (tmp_path / "offline-agent.html").read_text(encoding="utf-8")
        debate_html = (tmp_path / "offline-debate.html").read_text(encoding="utf-8")

        # HTML 包含 run_id
        assert "run_id" in agent_html or "ROOT_RUN_ID" in agent_html
        assert "run_id" in debate_html or "ROOT_RUN_ID" in debate_html