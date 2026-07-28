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


def test_import_from_core_emits_deprecation():
    """导入 core 必须产生 DeprecationWarning。"""
    # 清理模块缓存以确保重新导入
    import sys

    for module in list(sys.modules.keys()):
        if module.startswith("core"):
            del sys.modules[module]

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from core import Agent  # noqa: F401

        assert len(w) >= 1, "导入 core 必须产生至少一个 DeprecationWarning"
        assert any(
            issubclass(x.category, DeprecationWarning) for x in w
        ), f"期望 DeprecationWarning，但得到: {[x.category for x in w]}"


def test_object_identity_consistency():
    """验证两个命名空间导出对象身份一致。"""
    # 清理模块缓存以确保重新导入
    import sys

    for module in list(sys.modules.keys()):
        if module.startswith("core") or module.startswith("general_mini_agent"):
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

    # 抑制弃用警告以避免噪音
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from core import (
            LLM as LegacyLLM,
        )
        from core import (
            Agent as LegacyAgent,
        )
        from core import (
            AgentConfig as LegacyAgentConfig,
        )
        from core import (
            AgentResult as LegacyAgentResult,
        )
        from core import (
            AgentStopReason as LegacyAgentStopReason,
        )
        from core import (
            AsyncAgent as LegacyAsyncAgent,
        )
        from core import (
            AsyncChatModel as LegacyAsyncChatModel,
        )
        from core import (
            AsyncLLM as LegacyAsyncLLM,
        )
        from core import (
            AsyncStreamingChatModel as LegacyAsyncStreamingChatModel,
        )
        from core import (
            AsyncToolRegistry as LegacyAsyncToolRegistry,
        )
        from core import (
            ChatModel as LegacyChatModel,
        )
        from core import (
            Debate as LegacyDebate,
        )
        from core import (
            DebateConfig as LegacyDebateConfig,
        )
        from core import (
            DebateResult as LegacyDebateResult,
        )
        from core import (
            DebateRole as LegacyDebateRole,
        )
        from core import (
            LLMConfig as LegacyLLMConfig,
        )
        from core import (
            LLMResponse as LegacyLLMResponse,
        )
        from core import (
            StreamingChatModel as LegacyStreamingChatModel,
        )
        from core import (
            Tool as LegacyTool,
        )
        from core import (
            ToolRegistry as LegacyToolRegistry,
        )
        from core import (
            Workflow as LegacyWorkflow,
        )
        from core import (
            WorkflowNode as LegacyWorkflowNode,
        )
        from core import (
            WorkflowResult as LegacyWorkflowResult,
        )

    # 验证对象身份
    assert Agent is LegacyAgent, "Agent 对象身份不一致"
    assert AgentConfig is LegacyAgentConfig, "AgentConfig 对象身份不一致"
    assert AgentResult is LegacyAgentResult, "AgentResult 对象身份不一致"
    assert AgentStopReason is LegacyAgentStopReason, "AgentStopReason 对象身份不一致"
    assert AsyncAgent is LegacyAsyncAgent, "AsyncAgent 对象身份不一致"
    assert AsyncChatModel is LegacyAsyncChatModel, "AsyncChatModel 对象身份不一致"
    assert AsyncLLM is LegacyAsyncLLM, "AsyncLLM 对象身份不一致"
    assert AsyncStreamingChatModel is LegacyAsyncStreamingChatModel, (
    "AsyncStreamingChatModel 对象身份不一致"
)
    assert AsyncToolRegistry is LegacyAsyncToolRegistry, "AsyncToolRegistry 对象身份不一致"
    assert ChatModel is LegacyChatModel, "ChatModel 对象身份不一致"
    assert LLM is LegacyLLM, "LLM 对象身份不一致"
    assert LLMConfig is LegacyLLMConfig, "LLMConfig 对象身份不一致"
    assert LLMResponse is LegacyLLMResponse, "LLMResponse 对象身份不一致"
    assert StreamingChatModel is LegacyStreamingChatModel, "StreamingChatModel 对象身份不一致"
    assert Tool is LegacyTool, "Tool 对象身份不一致"
    assert ToolRegistry is LegacyToolRegistry, "ToolRegistry 对象身份不一致"
    assert Debate is LegacyDebate, "Debate 对象身份不一致"
    assert DebateConfig is LegacyDebateConfig, "DebateConfig 对象身份不一致"
    assert DebateResult is LegacyDebateResult, "DebateResult 对象身份不一致"
    assert DebateRole is LegacyDebateRole, "DebateRole 对象身份不一致"
    assert Workflow is LegacyWorkflow, "Workflow 对象身份不一致"
    assert WorkflowNode is LegacyWorkflowNode, "WorkflowNode 对象身份不一致"
    assert WorkflowResult is LegacyWorkflowResult, "WorkflowResult 对象身份不一致"


def test_wheel_contains_both_packages():
    """验证 wheel 包含 general_mini_agent 和 core。"""
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

            # 检查两个包都存在
            has_general_mini_agent = any("general_mini_agent/" in name for name in names)
            has_core = any("core/" in name for name in names)

            assert has_general_mini_agent, "wheel 必须包含 general_mini_agent 包"
            assert has_core, "wheel 必须包含 core 包（作为兼容层）"

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

            # 验证 core 子模块文件是 re-export（不包含实现逻辑）
            for reexport_file in implementation_files:
                core_file_path = f"core/{reexport_file}"
                if any(core_file_path == n for n in names):
                    # 检查文件内容是否只是 re-export
                    content = whl.read(core_file_path)
                    content_str = content.decode("utf-8")
                    # re-export 文件应该包含 "from general_mini_agent"
                    assert "from general_mini_agent" in content_str, (
                        f"core/{reexport_file} 应该是 re-export 文件"
                    )


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

# 导入 core 必须抛出 DeprecationWarning
try:
    from core import Agent as LegacyAgent
    print("ERROR: 应该产生 DeprecationWarning")
except DeprecationWarning:
    print("OK: 正确产生 DeprecationWarning")
"""

        test_result = subprocess.run(
            [str(venv_python), "-c", test_code],
            capture_output=True,
            text=True,
        )

        assert test_result.returncode == 0, f"测试导入失败: {test_result.stderr}"
        assert "OK: 正确产生 DeprecationWarning" in test_result.stdout