"""测试命名空间兼容性和对象身份一致性。"""

import warnings
from pathlib import Path

import pytest


def test_import_from_general_mini_agent_no_warning():
    """导入正式命名空间不应产生警告。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from general_mini_agent import Agent  # noqa: F401

        assert len(w) == 0, f"导入正式命名空间不应产生警告，但得到: {[str(x.message) for x in w]}"


def test_object_identity_consistency():
    """验证命名空间导出对象身份一致。"""
    # 清理模块缓存以确保重新导入
    import sys

    for module in list(sys.modules.keys()):
        if module.startswith("general_mini_agent"):
            del sys.modules[module]

    # 重新导入
    from general_mini_agent import (
        LLM,
        Agent,
        AgentConfig,
        AgentResult,
        AgentStopReason,
        AsyncAgent,
        AsyncChatModel,
        AsyncLLM,
        AsyncStreamingChatModel,
        AsyncToolRegistry,
        ChatModel,
        Debate,
        DebateConfig,
        DebateResult,
        DebateRole,
        LLMConfig,
        LLMResponse,
        StreamingChatModel,
        Tool,
        ToolRegistry,
        Workflow,
        WorkflowNode,
        WorkflowResult,
    )

    # 验证所有对象可用
    assert all((
        LLM, Agent, AgentConfig, AgentResult, AgentStopReason,
        AsyncAgent, AsyncChatModel, AsyncLLM, AsyncStreamingChatModel, AsyncToolRegistry,
        ChatModel, Debate, DebateConfig, DebateResult, DebateRole,
        LLMConfig, LLMResponse, StreamingChatModel, Tool, ToolRegistry,
        Workflow, WorkflowNode, WorkflowResult,
    ))


def test_wheel_contains_both_packages():
    """验证 wheel 包含 general_mini_agent。"""
    import sys
    import tempfile

    # 构建 wheel
    with tempfile.TemporaryDirectory() as tmpdir:
        import subprocess

        result = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", tmpdir],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.skip(f"构建 wheel 失败: {result.stderr}")

        # 查找 wheel 文件
        wheel_files = list(Path(tmpdir).glob("*.whl"))
        assert len(wheel_files) > 0, "未找到 wheel 文件"

        # 检查 wheel 内容
        import zipfile

        with zipfile.ZipFile(wheel_files[0]) as whl:
            names = whl.namelist()

            # 检查包存在
            has_general_mini_agent = any("general_mini_agent/" in name for name in names)

            assert has_general_mini_agent, "wheel 必须包含 general_mini_agent 包"

            # 检查实现文件只在新命名空间
            implementation_files = [
                "agent.py",
                "async_agent.py",
                "async_llm.py",
                "async_tools.py",
                "config.py",
                "context.py",
                "debate.py",
                "events.py",
                "llm.py",
                "logging.py",
                "long_term_memory.py",
                "memory.py",
                "providers.py",
                "tools.py",
                "trace.py",
                "trace_json.py",
                "workflow.py",
                "workflow_adapters.py",
            ]

            for impl_file in implementation_files:
                in_general_mini_agent = any(
                    f"general_mini_agent/{impl_file}" in name for name in names
                )

                assert in_general_mini_agent, f"{impl_file} 应该在 general_mini_agent 中"


def test_import_in_clean_environment():
    """在干净环境中测试导入。"""
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建虚拟环境
        result = subprocess.run(
            [sys.executable, "-m", "venv", f"{tmpdir}/venv"],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.skip(f"创建虚拟环境失败: {result.stderr}")

        # 安装 wheel
        venv_python = (
            Path(tmpdir) / "venv" / "Scripts" / "python.exe"
            if sys.platform == "win32"
            else Path(tmpdir) / "venv" / "bin" / "python"
        )

        # 构建 wheel
        build_result = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", tmpdir],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
        )

        if build_result.returncode != 0:
            pytest.skip(f"构建 wheel 失败: {build_result.stderr}")

        # 安装 wheel
        wheel_files = list(Path(tmpdir).glob("*.whl"))
        install_result = subprocess.run(
            [str(venv_python), "-m", "pip", "install", str(wheel_files[0])],
            capture_output=True,
            text=True,
        )

        if install_result.returncode != 0:
            pytest.skip(f"安装 wheel 失败: {install_result.stderr}")

        # 测试导入
        test_code = """
import warnings
warnings.filterwarnings('error', category=DeprecationWarning)

# 导入正式命名空间不应该警告
from general_mini_agent import Agent, LLM, Tool

print("OK: 成功导入 general_mini_agent")
"""

        test_result = subprocess.run(
            [str(venv_python), "-c", test_code],
            capture_output=True,
            text=True,
        )

        assert test_result.returncode == 0, f"测试导入失败: {test_result.stderr}"
        assert "OK: 成功导入 general_mini_agent" in test_result.stdout