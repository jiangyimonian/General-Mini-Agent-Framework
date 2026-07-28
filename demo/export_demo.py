"""
General Mini Agent Framework HTML 轨迹导出示例。

运行:
    python demo/export_demo.py          → 生成 output/trace.html
    python demo/export_demo.py debate   → 生成 output/debate.html
    python demo/export_demo.py json     → 生成 output/trace.json
"""

# Experimental example: not covered by the 0.1.0 stable API.

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from core.agent import Agent  # noqa: E402
from core.debate import create_debate  # noqa: E402
from core.events import EventCollector  # noqa: E402
from core.llm import LLM, LLMConfig  # noqa: E402
from core.tools import tool  # noqa: E402
from core.trace import export_debate, export_trace  # noqa: E402
from core.trace_json import TraceDocument, export_trace_json  # noqa: E402


@tool(description="计算数学表达式的值")
def calculate(expression: str) -> float:
    allowed = set("0123456789.+-*/()eE% ")
    if not all(c in allowed for c in expression):
        raise ValueError("表达式包含非法字符")
    return eval(expression)


@tool(description="查询常识知识")
def search_knowledge(query: str) -> str:
    kb = {
        "光速": "真空光速 ≈ 3×10⁸ m/s",
        "日地距离": "1 天文单位 ≈ 1.496×10¹¹ m",
        "地球周长": "地球赤道周长 ≈ 40,075 km",
    }
    for k, v in kb.items():
        if k in query:
            return v
    return f"未找到「{query}」"


def make_llm():
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("错误: 请设置 DEEPSEEK_API_KEY")
        sys.exit(1)
    return LLM(LLMConfig(api_key=api_key, temperature=0.0))


def run_trace_export():
    agent = Agent(llm=make_llm(), tools=[calculate, search_knowledge])
    question = "光从太阳到地球需要多长时间？"
    print(f"🤖 运行 Agent: {question}")
    result = agent.run(question)
    path = os.path.join(os.path.dirname(__file__), "..", "output", "trace.html")
    export_trace(
        result,
        path,
        question=question,
        title="General Mini Agent Framework - Agent Trace",
    )
    print(f"✅ 导出到: {os.path.abspath(path)}")


def run_debate_export():
    solver = Agent(llm=make_llm(), tools=[calculate, search_knowledge], max_iterations=6)
    critic = Agent(llm=make_llm(), tools=[calculate, search_knowledge], max_iterations=4)
    judge  = Agent(llm=make_llm(), tools=[calculate, search_knowledge], max_iterations=4)

    debate = create_debate(solver, critic, judge)
    question = "地球绕太阳公转的线速度是多少？提示：轨道近似圆形"
    print(f"⚔️ 运行 Debate: {question}")
    result = debate.run(question)
    path = os.path.join(os.path.dirname(__file__), "..", "output", "debate.html")
    export_debate(
        result,
        path,
        question=question,
        title="General Mini Agent Framework - Debate Trace",
    )
    print(f"✅ 导出到: {os.path.abspath(path)}")


def run_json_export():
    """演示 JSON trace 导出。"""
    collector = EventCollector()
    agent = Agent(llm=make_llm(), tools=[calculate, search_knowledge], event_sink=collector)
    question = "光从太阳到地球需要多长时间？"
    print(f"🤖 运行 Agent (带事件收集): {question}")
    result = agent.run(question)

    # 创建 trace 文档
    doc = TraceDocument(
        schema_version=1,
        root_run_id=result.run_id,
        events=collector.snapshot(),
    )

    # 导出 JSON
    output_dir = os.path.join(os.path.dirname(__file__), "..", "output")
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "trace.json")
    export_trace_json(doc, path)
    print(f"✅ JSON 导出到: {os.path.abspath(path)}")
    print(f"   事件数: {len(doc.events)}")
    print(f"   run_id: {doc.root_run_id}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "debate":
            run_debate_export()
        elif arg == "json":
            run_json_export()
        else:
            print(f"未知参数: {arg}")
            print("用法: python demo/export_demo.py [debate|json]")
    else:
        run_trace_export()
