"""
General Mini Agent Framework 多 Agent 协作示例。

运行前请设置 .env:
  DEEPSEEK_API_KEY=your_api_key_here
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


# ─── 工具定义 ────────────────────────────────────────────────


@tool(description="计算数学表达式的值")
def calculate(expression: str) -> float:
    allowed = set("0123456789.+-*/()eE% ")
    if not all(c in allowed for c in expression):
        raise ValueError("表达式包含非法字符")
    return eval(expression)


@tool(description="查询常识知识")
def search_knowledge(query: str) -> str:
    knowledge_base = {
        "光速": "真空光速 299,792,458 m/s，常取 3×10⁸ m/s",
        "日地距离": "1 天文单位 ≈ 1.496×10¹¹ m",
        "地球质量": "5.972×10²⁴ kg",
        "太阳质量": "1.989×10³⁰ kg",
        "圆周率": "π ≈ 3.141592653589793",
        "万有引力常数": "G ≈ 6.674×10⁻¹¹ N·m²/kg²",
        "地球半径": "6371 km = 6.371×10⁶ m",
    }
    for key, value in knowledge_base.items():
        if key in query:
            return value
    return f"未找到「{query}」"


# ─── 格式化 ────────────────────────────────────────────────


C = {
    "solver": "\033[36m",  # 青
    "critic": "\033[33m",  # 黄
    "judge":  "\033[1;32m", # 亮绿
    "dim":    "\033[2m",
    "reset":  "\033[0m",
}


def print_role(name: str, content: str) -> None:
    color = C.get(name.lower(), C["reset"])
    print(f"\n{color}┌─ {name} ─────────────────────{C['reset']}")
    # 只打印前 500 字符，避免刷屏
    display = content[:500] + ("..." if len(content) > 500 else "")
    print(f"{color}│{C['reset']} {display}")


# ─── 主流程 ────────────────────────────────────────────────


def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("错误: 请设置 DEEPSEEK_API_KEY 环境变量")
        sys.exit(1)

    config = LLMConfig(
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        model=os.environ.get("LLM_MODEL", "deepseek-chat"),
        temperature=0.0,
    )

    # 三个 Agent，共享同一个 LLM 实例和工具集
    solver = Agent(
        llm=LLM(config),
        tools=[calculate, search_knowledge],
        max_iterations=6,
    )

    critic = Agent(
        llm=LLM(config),
        tools=[calculate, search_knowledge],
        max_iterations=4,
    )

    judge = Agent(
        llm=LLM(config),
        tools=[calculate, search_knowledge],
        max_iterations=4,
    )

    # 创建辩论
    debate = Debate(solver=solver, critic=critic, judge=judge)
    debate.config.max_rounds = 2

    # 一个故意有陷阱的问题
    question = "地球绕太阳公转的线速度是多少？提示：轨道近似圆形"

    print(f"\n🔍 辩论问题: {question}\n")
    print(f"{C['dim']}{'═' * 50}{C['reset']}")

    result = debate.run(question)

    # 输出辩论过程
    for r in result.rounds:
        print(f"\n{C['dim']}── 第 {r['round'] + 1} 轮辩论 ──{C['reset']}")
        for resp in r["responses"]:
            print_role(resp["role"], resp["content"])

    print(f"\n{C['dim']}{'═' * 50}{C['reset']}")
    print(f"\n{C['judge']}📊 最终结论:{C['reset']}")
    print(f"  {result.verdict[:600]}")
    print()
    print(f"{C['dim']}Token 总计: {result.total_usage}{C['reset']}")


if __name__ == "__main__":
    main()
