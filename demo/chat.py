"""
General Mini Agent Framework 交互式终端。

运行:
    python demo/chat.py

命令:
    /clear   清空上下文
    /trace   显示最近一次推理轨迹
    /export  导出最近一次推理为 HTML
    /exit    退出
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from core.llm import LLM, LLMConfig
from core.tools import tool
from core.agent import Agent
from core.trace import export_trace


# ─── 工具 ──────────────────────────────────────────────────


@tool(description="计算数学表达式的值，如 '3 + 5 * 2'")
def calculate(expression: str) -> float:
    allowed = set("0123456789.+-*/()eE% ")
    if not all(c in allowed for c in expression):
        raise ValueError("表达式包含非法字符")
    return eval(expression)


@tool(description="获取当前日期和时间")
def get_date() -> str:
    now = datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{now.year}年{now.month}月{now.day}日 {weekdays[now.weekday()]} {now.hour:02d}:{now.minute:02d}:{now.second:02d}"


@tool(description="查询常识知识，如物理常数、地理信息等")
def search(query: str) -> str:
    kb = {
        "光速": "真空光速 ≈ 3×10⁸ m/s",
        "日地距离": "1 天文单位 ≈ 1.496×10¹¹ m",
        "地球半径": "6371 km",
        "地球质量": "5.972×10²⁴ kg",
        "太阳质量": "1.989×10³⁰ kg",
        "重力加速度": "g ≈ 9.8 m/s²",
        "圆周率": "π ≈ 3.14159",
    }
    for k, v in kb.items():
        if k in query:
            return v
    return f"未找到「{query}」"


# ─── 颜色 ──────────────────────────────────────────────────

C = {
    "cyan":   "\033[36m",
    "green":  "\033[32m",
    "yellow": "\033[33m",
    "dim":    "\033[2m",
    "bold":   "\033[1m",
    "reset":  "\033[0m",
}


# ─── 主逻辑 ────────────────────────────────────────────────


def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("错误: 请设置 DEEPSEEK_API_KEY")
        sys.exit(1)

    config = LLMConfig(
        api_key=api_key,
        base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
        model=os.environ.get("LLM_MODEL", "deepseek-chat"),
        temperature=0.0,
    )

    agent = Agent(llm=LLM(config), tools=[calculate, search, get_date], max_iterations=10)
    last_result = None

    print(
        f"\n{C['bold']}General Mini Agent Framework{C['reset']}  "
        f"{C['dim']}输入问题开始对话，/exit 退出{C['reset']}\n"
    )

    while True:
        try:
            user_input = input(f"{C['green']}你{C['reset']}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue

        # ── 命令 ──────────────────────────────
        if user_input == "/exit":
            break
        elif user_input == "/clear":
            agent.memory.clear()
            print(f"{C['dim']}  上下文已清空{C['reset']}")
            continue
        elif user_input == "/trace" and last_result:
            print(f"\n{C['dim']}── 推理轨迹 ──{C['reset']}")
            for step in last_result.trace:
                if "final_answer" in step:
                    print(f"  {C['bold']}✅ {step['final_answer'][:200]}{C['reset']}")
                else:
                    print(f"  {C['cyan']}💭{C['reset']} {step.get('thought', '')[:100]}")
                    print(f"  {C['yellow']}🔧{C['reset']} {step['tool']}({step.get('arguments', {})})")
                    print(f"  {C['green']}📤{C['reset']} {step['observation'][:200]}")
            print()
            continue
        elif user_input == "/export" and last_result:
            path = os.path.join(os.path.dirname(__file__), "..", "output", "cli_trace.html")
            export_trace(
                last_result,
                path,
                question=user_input,
                title="General Mini Agent Framework - CLI Trace",
            )
            print(f"{C['dim']}  已导出到 {os.path.abspath(path)}{C['reset']}")
            continue
        elif user_input.startswith("/"):
            print(f"{C['dim']}  未知命令: {user_input}{C['reset']}")
            continue

        # ── 推理 ──────────────────────────────
        print(f"{C['cyan']}Agent{C['reset']}: ", end="", flush=True)
        start = time.time()
        round_count = 0
        last_round = -1
        just_had_tool = False  # 上一步是否刚执行了工具

        for event in agent.run_stream(user_input):
            etype = event["type"]

            if etype == "iteration_start":
                if event["iteration"] != last_round:
                    last_round = event["iteration"]
                    round_count += 1
                    if not just_had_tool and round_count > 1:
                        print()  # 新一轮，换行
                    print(f"\n{C['dim']}[第 {last_round + 1} 轮]{C['reset']} ", end="", flush=True)

            elif etype == "thought_chunk":
                print(event.get("text", ""), end="", flush=True)

            elif etype == "tool_call":
                just_had_tool = True
                print(f"\n  {C['yellow']}🔧 {event['name']}({event['arguments']}){C['reset']}")

            elif etype == "observation":
                print(f"  {C['green']}📤 {event['text'][:200]}{C['reset']}")
                just_had_tool = False

            elif etype == "done":
                elapsed = time.time() - start
                usage = event.get("usage", {})
                trace = event.get("trace", [])

                # 按轮次分组汇总
                print(f"\n  {C['dim']}{'─' * 40}{C['reset']}")
                rounds_seen = {}
                for s in trace:
                    r = s.get("iteration", 0) + 1
                    if r not in rounds_seen:
                        rounds_seen[r] = []
                    if "tool" in s:
                        rounds_seen[r].append(f"🔧{s['tool']}")
                    elif "final_answer" in s:
                        rounds_seen[r].append("✅答案")
                for r, acts in sorted(rounds_seen.items()):
                    print(f"  {C['dim']}第{r}轮: {' → '.join(acts)}{C['reset']}")

                print(f"  {C['dim']}总计: {event['iterations']} 轮 · {elapsed:.1f}s · {usage.get('total_tokens', 0)} tokens{C['reset']}")
                last_result = type("Result", (), {
                    "trace": trace,
                    "content": event["content"],
                    "usage": event["usage"],
                    "iterations": event["iterations"],
                })()

        print()


if __name__ == "__main__":
    main()
