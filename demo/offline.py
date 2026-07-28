"""完全离线的 Agent 和 Debate 示例。

运行:
    python demo/offline.py

输出:
    output/offline-agent.json
    output/offline-agent.html
    output/offline-debate.json
    output/offline-debate.html

不读取 .env，不访问网络。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 确保可以导入 core
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.agent import Agent
from core.debate import create_debate
from core.events import EventCollector
from core.tools import tool
from core.trace import export_trace_html
from core.trace_json import TraceDocument
from demo.scripted_models import ScriptedChatModel, agent_with_tool_response, debate_responses

# ─── 工具定义 ────────────────────────────────────────────────────────


@tool(description="计算数学表达式")
def calculate(expression: str) -> float:
    allowed = set("0123456789.+-*/()eE% ")
    if not all(c in allowed for c in expression):
        raise ValueError("表达式包含非法字符")
    return eval(expression)


# ─── Agent 场景 ────────────────────────────────────────────────────────


def run_agent_scenario(output_dir: Path) -> tuple[str, str]:
    """运行单 Agent 场景，输出 JSON 和 HTML。"""
    collector = EventCollector()
    model = ScriptedChatModel(agent_with_tool_response())

    agent = Agent(
        llm=model,
        tools=[calculate],
        max_iterations=5,
        event_sink=collector,
    )

    result = agent.run("What is 2+2?")

    # 创建 TraceDocument
    doc = TraceDocument(
        schema_version=1,
        root_run_id=result.run_id,
        events=collector.snapshot(),
    )

    # 输出路径
    json_path = output_dir / "offline-agent.json"
    html_path = output_dir / "offline-agent.html"

    # 导出
    from core.trace_json import export_trace_json
    export_trace_json(doc, json_path)
    export_trace_html(doc, html_path, title="Offline Agent Trace")

    return str(json_path), str(html_path)


# ─── Debate 场景 ────────────────────────────────────────────────────────


def run_debate_scenario(output_dir: Path) -> tuple[str, str]:
    """运行 Debate 场景，输出 JSON 和 HTML。"""
    collector = EventCollector()

    # Solver 使用第一个响应
    solver_model = ScriptedChatModel(debate_responses()[:1])
    solver = Agent(
        llm=solver_model,
        max_iterations=3,
        event_sink=collector,
    )

    # Critic 使用第二个响应
    critic_model = ScriptedChatModel(debate_responses()[1:2])
    critic = Agent(
        llm=critic_model,
        max_iterations=3,
        event_sink=collector,
    )

    # Judge 使用第三个响应
    judge_model = ScriptedChatModel(debate_responses()[2:])
    judge = Agent(
        llm=judge_model,
        max_iterations=3,
        event_sink=collector,
    )

    debate = create_debate(solver, critic, judge, max_rounds=1)
    result = debate.run("What is the answer?")

    # 创建 TraceDocument
    doc = TraceDocument(
        schema_version=1,
        root_run_id=result.run_id,
        events=collector.snapshot(),
    )

    # 输出路径
    json_path = output_dir / "offline-debate.json"
    html_path = output_dir / "offline-debate.html"

    # 导出
    from core.trace_json import export_trace_json
    export_trace_json(doc, json_path)
    export_trace_html(doc, html_path, title="Offline Debate Trace")

    return str(json_path), str(html_path)


# ─── 主入口 ────────────────────────────────────────────────────────────


def main(output_dir: str | Path | None = None) -> None:
    """运行所有离线场景。"""
    output_dir = Path(output_dir or Path(__file__).parent.parent / "output")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("🤖 Running offline Agent scenario...")
    agent_json, agent_html = run_agent_scenario(output_dir)
    print(f"   JSON: {agent_json}")
    print(f"   HTML: {agent_html}")

    print("⚔️ Running offline Debate scenario...")
    debate_json, debate_html = run_debate_scenario(output_dir)
    print(f"   JSON: {debate_json}")
    print(f"   HTML: {debate_html}")

    print("✅ Done. Generated 4 files.")


if __name__ == "__main__":
    main()