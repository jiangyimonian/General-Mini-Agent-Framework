"""
General Mini Agent Framework HTML 轨迹导出示例。

运行:
    python demo/export_demo.py          → 生成 output/trace.html
    python demo/export_demo.py debate   → 生成 output/debate.html
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from core.llm import LLM, LLMConfig
from core.tools import tool
from core.agent import Agent
from core.debate import Debate
from core.trace import export_trace, export_debate


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

    debate = Debate(solver=solver, critic=critic, judge=judge)
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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "debate":
        run_debate_export()
    else:
        run_trace_export()
