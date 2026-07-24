"""
General Mini Agent Framework 流式推理示例。

运行前请设置 .env:
  DEEPSEEK_API_KEY=your_api_key_here
"""

# Experimental example: not covered by the 0.1.0 stable API.

from __future__ import annotations

import os
import sys
import time

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from core.agent import Agent  # noqa: E402
from core.llm import LLM, LLMConfig  # noqa: E402
from core.tools import tool  # noqa: E402

# ─── 工具定义 ────────────────────────────────────────────────


@tool(description="计算数学表达式的值，如 \"3 + 5 * 2\"")
def calculate(expression: str) -> float:
    allowed = set("0123456789.+-*/()eE% ")
    if not all(c in allowed for c in expression):
        raise ValueError("表达式包含非法字符")
    return eval(expression)


@tool(description="查询常识知识")
def search_knowledge(query: str) -> str:
    knowledge_base = {
        "光速": "真空中的光速约为 299,792,458 米/秒，通常取 3×10⁸ 米/秒",
        "地球到太阳距离": "地球到太阳的平均距离约为 1.496×10¹¹ 米（1 个天文单位）",
        "地球质量": "地球质量约为 5.972×10²⁴ 千克",
        "太阳质量": "太阳质量约为 1.989×10³⁰ 千克",
        "圆周率": "圆周率 π ≈ 3.141592653589793",
        "重力加速度": "地球表面重力加速度 g ≈ 9.8 米/秒²",
    }
    for key, value in knowledge_base.items():
        if key in query:
            return value
    return f"未找到与「{query}」相关的知识"


# ─── 步骤色 ────────────────────────────────────────────────

C = {
    "thought": "\033[36m",   # 青
    "tool":    "\033[33m",   # 黄
    "result":  "\033[32m",   # 绿
    "final":   "\033[1;32m", # 亮绿
    "reset":   "\033[0m",
    "dim":     "\033[2m",    # 灰
}


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
    llm = LLM(config)

    agent = Agent(llm=llm, tools=[calculate, search_knowledge], max_iterations=10)

    question = (
        "光从太阳到地球需要多长时间？"
        "已知条件：光速约 3×10⁸ 米/秒，太阳到地球约 1.496×10¹¹ 米"
    )

    print(f"\n🔍 问题: {question}\n")
    start_time = time.time()

    iter_count = 0
    last_iter = -1

    for event in agent.run_stream(question):
        etype = event["type"]

        if etype == "iteration_start":
            iter_count = event["iteration"]
            if iter_count != last_iter:
                if iter_count > 0:
                    print()
                print(f"{C['dim']}─ 第 {iter_count + 1} 轮 ─{C['reset']}")
                last_iter = iter_count

        elif etype == "thought_chunk":
            if event.get("text"):
                print(f"{C['thought']}{event['text']}{C['reset']}", end="", flush=True)

        elif etype == "tool_call":
            print(f"\n  {C['tool']}🔧 调用 {event['name']}({event['arguments']}){C['reset']}")

        elif etype == "observation":
            print(f"  {C['result']}📤 {event['text']}{C['reset']}")

        elif etype == "final_answer":
            print(f"\n  {C['final']}✅ {event['text']}{C['reset']}")

        elif etype == "done":
            elapsed = time.time() - start_time
            usage = event.get("usage", {})
            print(f"\n\n{C['dim']}══════════════════════{C['reset']}")
            print(
                f"{C['dim']}📊 {event['iterations']} 轮迭代  │  ⏱ {elapsed:.1f}s  │  "
                f"Token: {usage.get('total_tokens', 0)}{C['reset']}"
            )


if __name__ == "__main__":
    main()
