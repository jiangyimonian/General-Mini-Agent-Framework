"""General Mini Agent Framework CLI.

命令行工具：
- gmaf --version - 显示版本
- gmaf doctor - 检查环境和配置
- gmaf init - 初始化项目配置
- gmaf run [任务] - 运行单次任务
- gmaf chat - 交互式聊天
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import FrameworkConfig, find_project_root
from .logging import get_logger
from .session import (
    conversation_from_session,
    list_sessions,
    load_session,
    save_session,
)
from .session import (
    delete_session as do_delete_session,
)

logger = get_logger(__name__)


def main() -> int:
    """CLI 主入口。"""
    parser = argparse.ArgumentParser(
        description="General Mini Agent Framework - 轻量可组合的 Python Agent 内核",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="使用 'gmaf <命令> --help' 查看命令详情",
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"gmaf {__version__}"
    )

    # 子命令
    subparsers = parser.add_subparsers(title="可用命令", dest="command", help="")

    # doctor 命令
    doctor_parser = subparsers.add_parser("doctor", help="检查环境和配置")
    doctor_parser.add_argument(
        "-v", "--verbose", action="store_true", help="显示详细信息"
    )

    # init 命令
    init_parser = subparsers.add_parser("init", help="初始化项目配置")
    init_parser.add_argument(
        "-d", "--directory", type=Path, default=Path.cwd(), help="目标目录"
    )
    init_parser.add_argument(
        "-f", "--force", action="store_true", help="覆盖已存在的配置文件"
    )

    # run 命令
    run_parser = subparsers.add_parser("run", help="运行单次任务")
    run_parser.add_argument("task", nargs="+", help="任务描述")
    run_parser.add_argument(
        "-w", "--workspace", type=Path, help="工作区目录"
    )
    run_parser.add_argument(
        "-o", "--output", type=Path, help="输出 trace 文件"
    )
    run_parser.add_argument(
        "--write", action="store_true", help="启用写操作"
    )
    run_parser.add_argument(
        "--execute", action="store_true", help="启用命令执行"
    )

    # chat 命令
    chat_parser = subparsers.add_parser("chat", help="交互式聊天")
    chat_parser.add_argument(
        "-w", "--workspace", type=Path, help="工作区目录"
    )
    chat_parser.add_argument(
        "--write", action="store_true", help="启用写操作"
    )
    chat_parser.add_argument(
        "--execute", action="store_true", help="启用命令执行"
    )
    chat_parser.add_argument(
        "-s", "--session", type=str, help="会话名称（加载/保存）"
    )

    # sessions 命令
    sessions_parser = subparsers.add_parser("sessions", help="列出所有会话")
    sessions_parser.add_argument(
        "-v", "--verbose", action="store_true", help="显示详细信息"
    )

    # delete 命令
    delete_parser = subparsers.add_parser("delete", help="删除会话")
    delete_parser.add_argument("name", type=str, help="会话名称")
    delete_parser.add_argument(
        "-f", "--force", action="store_true", help="不询问确认"
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "version":
        print(f"gmaf {__version__}")
        return 0

    if args.command == "doctor":
        return do_doctor(verbose=args.verbose)

    if args.command == "init":
        return do_init(args.directory, args.force)

    if args.command == "run":
        return do_run(
            " ".join(args.task),
            workspace=args.workspace,
            output=args.output,
            allow_write=args.write,
            allow_execute=args.execute,
        )

    if args.command == "chat":
        return do_chat(
            workspace=args.workspace,
            allow_write=args.write,
            allow_execute=args.execute,
            session_name=args.session,
        )

    if args.command == "sessions":
        return do_sessions(verbose=args.verbose)

    if args.command == "delete":
        return do_delete(args.name, force=args.force)

    return 0


def do_doctor(verbose: bool = False) -> int:
    """检查环境和配置。"""
    print(f"General Mini Agent Framework v{__version__}")
    print()

    all_ok = True

    # 检查 Python 版本
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    print(f"✅ Python 版本: {py_version}")

    # 检查项目根目录
    project_root = find_project_root()
    if project_root:
        print(f"✅ 项目根目录: {project_root}")
    else:
        print("⚠️ 未找到项目根目录 (使用 'gmaf init' 初始化)")

    # 检查配置
    try:
        config = FrameworkConfig.load()
        print("✅ 配置加载成功")
        if verbose:
            print(f"   - base_url: {config.base_url}")
            print(f"   - model: {config.model}")
            print(f"   - timeout: {config.timeout}s")
            print(f"   - max_retries: {config.max_retries}")
    except ValueError as e:
        print(f"❌ 配置加载失败: {e}")
        all_ok = False

    print()
    if all_ok:
        print("✅ 所有检查通过！")
        return 0
    else:
        print("⚠️ 部分检查失败，请查看上面的信息")
        return 1


def do_init(directory: Path, force: bool = False) -> int:
    """初始化项目配置。"""
    target_path = directory / ".gmaf.toml"

    if target_path.exists() and not force:
        print(f"❌ 配置文件已存在: {target_path}")
        print("使用 --force 覆盖")
        return 1

    # 创建配置文件
    template = '''# General Mini Agent Framework 配置

# API 配置
# api_key = "your-api-key-here"
# base_url = "https://api.openai.com/v1"
# model = "gpt-3.5-turbo"

# 超时和重试
# timeout = 60.0
# max_retries = 2

# 上下文窗口配置
# context_window = 65536
# reserved_output_tokens = 4096

# 提供商 (openai-compatible / deepseek / anthropic)
# provider = "openai-compatible"
'''

    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(template, encoding="utf-8")
        print(f"✅ 创建配置文件: {target_path}")
        print()
        print("下一步:")
        print("1. 编辑 .gmaf.toml 配置 API 密钥")
        print("2. 运行 'gmaf doctor' 检查配置")
        return 0
    except Exception as e:
        print(f"❌ 创建配置文件失败: {e}")
        return 1


def do_run(
    task: str,
    workspace: Path | None = None,
    output: Path | None = None,
    allow_write: bool = False,
    allow_execute: bool = False,
) -> int:
    """运行单次任务。"""
    from . import LLM, Agent, InMemoryConversation, LLMConfig
    from .config import FrameworkConfig

    try:
        config = FrameworkConfig.load()
    except ValueError as e:
        print(f"❌ 配置加载失败: {e}")
        print("运行 'gmaf doctor' 检查配置，或 'gmaf init' 初始化")
        return 1

    try:
        llm_config = LLMConfig(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            timeout=config.timeout,
            max_retries=config.max_retries,
            max_tokens=config.max_tokens,
        )
        llm = LLM(llm_config)
    except Exception as e:
        print(f"❌ LLM 初始化失败: {e}")
        return 1

    # 设置工作区
    workspace_path = workspace or (find_project_root() or Path.cwd())
    print(f"工作区: {workspace_path}")

    try:
        agent = Agent(
            llm=llm,
            tools=[],
            memory=InMemoryConversation(),
        )
        result = agent.run(task)
        print()
        print("回答:")
        print(result.content)
        return 0
    except Exception as e:
        print(f"❌ 任务执行失败: {e}")
        return 1


def do_chat(
    workspace: Path | None = None,
    allow_write: bool = False,
    allow_execute: bool = False,
    session_name: str | None = None,
) -> int:
    """交互式聊天。"""
    from . import LLM, Agent, InMemoryConversation, LLMConfig
    from .config import FrameworkConfig

    try:
        config = FrameworkConfig.load()
    except ValueError as e:
        print(f"❌ 配置加载失败: {e}")
        print("运行 'gmaf doctor' 检查配置，或 'gmaf init' 初始化")
        return 1

    try:
        llm_config = LLMConfig(
            api_key=config.api_key,
            base_url=config.base_url,
            model=config.model,
            timeout=config.timeout,
            max_retries=config.max_retries,
            max_tokens=config.max_tokens,
        )
        llm = LLM(llm_config)
    except Exception as e:
        print(f"❌ LLM 初始化失败: {e}")
        return 1

    # 设置工作区
    workspace_path = workspace or (find_project_root() or Path.cwd())
    print(f"工作区: {workspace_path}")

    # 加载会话
    conv = InMemoryConversation()
    if session_name:
        existing_session = load_session(session_name)
        if existing_session:
            conv = conversation_from_session(existing_session)
            print(
                f"✅ 已加载会话: {session_name} "
                f"({existing_session.metadata.message_count} 条消息)"
            )
        else:
            print(f"📍 新会话: {session_name}")

    # 创建 Agent
    agent = Agent(
        llm=llm,
        tools=[],
        memory=conv,
    )

    print()
    print(f"General Mini Agent Framework v{__version__} 交互式聊天")
    if session_name:
        print(f"会话: {session_name} (自动保存)")
    print("输入 'exit' 或 'quit' 退出")
    print("-" * 60)

    try:
        while True:
            try:
                user_input = input("\n你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if user_input.lower() in ("exit", "quit", "q"):
                break

            if not user_input:
                continue

            try:
                print("\n助手: ", end="", flush=True)
                has_output = False
                for event in agent.run_stream(user_input):
                    # 统一获取事件属性
                    if isinstance(event, dict):
                        event_type = event.get("type", "")
                        text = event.get("text", "")
                        name = event.get("name", "")
                        error = event.get("error", "")
                    else:
                        event_type = getattr(event, "type", "")
                        text = getattr(event, "text", "")
                        name = getattr(event, "name", "")
                        error = getattr(event, "error", "")

                    if event_type == "thought_chunk":
                        print(text, end="", flush=True)
                        has_output = True
                    elif event_type == "tool_call":
                        print(f"\n\n🔧 调用工具: {name}", flush=True)
                    elif event_type == "observation":
                        display = text[:200] + ("..." if len(text) > 200 else "")
                        print(f"📊 工具结果: {display}", flush=True)
                        print("\n助手: ", end="", flush=True)
                    elif event_type == "final_answer":
                        pass
                    elif event_type == "model_error":
                        print(f"\n❌ 模型错误: {error}")
                    elif event_type == "done":
                        # 如果没有流式输出，用 done.content 作为后备
                        if not has_output:
                            content = event.get("content", "") if isinstance(event, dict) else getattr(event, "content", "")
                            if content:
                                print(content, end="", flush=True)
                print()

                # 保存会话
                if session_name:
                    save_session(session_name, conv)
            except Exception as e:
                print(f"❌ 错误: {e}")

        return 0
    except KeyboardInterrupt:
        print()
        return 0


def do_sessions(verbose: bool = False) -> int:
    """列出所有会话。"""
    sessions = list(list_sessions())

    if not sessions:
        print("暂无会话")
        return 0

    print(f"找到 {len(sessions)} 个会话:")
    print()

    for i, s in enumerate(sessions, 1):
        if verbose:
            print(f"{i}. {s.name}")
            print(f"   创建: {s.created_at}")
            print(f"   更新: {s.updated_at}")
            print(f"   消息: {s.message_count}")
            if s.summary:
                print(f"   摘要: {s.summary}")
            print()
        else:
            updated = s.updated_at.split("T")[0] if "T" in s.updated_at else s.updated_at
            print(f"  {i}. {s.name} - {s.message_count} 条消息 ({updated})")

    if not verbose:
        print()
        print("使用 'gmaf sessions -v' 查看详情")

    return 0


def do_delete(name: str, force: bool = False) -> int:
    """删除会话。"""
    existing = load_session(name)
    if not existing:
        print(f"会话不存在: {name}")
        return 1

    if not force:
        try:
            confirm = input(
                f"确定删除会话 '{name}' "
                f"({existing.metadata.message_count} 条消息)? [y/N] "
            ).strip()
            if confirm.lower() not in ("y", "yes", "是"):
                print("取消删除")
                return 0
        except (EOFError, KeyboardInterrupt):
            print("\n取消删除")
            return 0

    success = do_delete_session(name)
    if success:
        print(f"✅ 已删除会话: {name}")
        return 0
    else:
        print(f"❌ 删除失败: {name}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
