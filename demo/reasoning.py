"""
General Mini Agent Framework 同步推理示例。

运行前请在 .env 文件中配置:
  DEEPSEEK_API_KEY=your_api_key_here
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# 加载 .env 文件
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from core.llm import LLM, LLMConfig
from core.tools import tool
from core.agent import Agent


# ─── 工具定义 ────────────────────────────────────────────────


@tool(description="计算数学表达式的值，如 \"3 + 5 * 2\"")
def calculate(expression: str) -> float:
    """计算数学表达式

    Args:
        expression: 数学表达式字符串，如 "1.496e11 / 3e8"
    """
    # 安全计算：只允许数字、运算符、括号、空格
    allowed = set("0123456789.+-*/()eE% ")
    if not all(c in allowed for c in expression):
        raise ValueError("表达式包含非法字符")
    return eval(expression)


@tool(description="查询常识知识")
def search_knowledge(query: str) -> str:
    """搜索与查询相关的常识知识

    Args:
        query: 查询关键词，如 "光速"、"地球质量"
    """
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


# ─── 测试问题集 ─────────────────────────────────────────────


QUESTIONS = [
    # 多步推理题 — 需要多次调用 calculate
    {
        "question": (
            "光从太阳到地球需要多长时间？"
            "已知条件：光速约 3×10⁸ 米/秒，太阳到地球约 1.496×10¹¹ 米"
        ),
        "expected": "约 8.31 分钟",
    },
    # 需要工具组合
    {
        "question": "地球绕太阳公转的线速度是多少？（提示：轨道近似圆形）",
        "expected": "约 29.8 公里/秒",
    },
]

# ─── 带高亮的 trace 打印 ──────────────────────────────────


def print_trace(trace: list[dict]) -> None:
    """打印推理轨迹"""
    print("\n" + "=" * 60)
    print("📋 推理轨迹")
    print("=" * 60)

    for step in trace:
        if "final_answer" in step:
            print(f"\n{'─' * 40}")
            print(f"✅ 最终答案: {step['final_answer']}")
            print(f"{'─' * 40}")
            continue

        print(f"\n─ 第 {step['iteration'] + 1} 轮 ─")
        thought = step.get("thought", "").strip()
        if thought:
            # 提取 Thought: 后面的内容
            for line in thought.split("\n"):
                stripped = line.strip()
                if stripped and not stripped.lower().startswith("action:"):
                    print(f"  💭 {stripped}")

        print(f"  🔧 工具: {step['tool']}")
        print(f"  📥 参数: {step['arguments']}")
        print(f"  📤 结果: {step['observation']}")


# ─── 主函数 ─────────────────────────────────────────────────


def main():
    api_key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("错误: 请设置 DEEPSEEK_API_KEY 环境变量")
        print("  export DEEPSEEK_API_KEY=your_key_here")
        sys.exit(1)

    # LLM 配置（默认 DeepSeek，也可换其他 OpenAI 兼容服务）
    config = LLMConfig(
        api_key=api_key,
        base_url=os.environ.get(
            "LLM_BASE_URL",
            "https://api.deepseek.com/v1",
        ),
        model=os.environ.get("LLM_MODEL", "deepseek-chat"),
        temperature=0.0,
    )
    llm = LLM(config)

    # 构建 Agent
    agent = Agent(
        llm=llm,
        tools=[calculate, search_knowledge],
        max_iterations=10,
    )

    # 跑第一个问题
    q = QUESTIONS[0]
    print(f"\n🔍 问题: {q['question']}\n")

    result = agent.run(q["question"])
    print_trace(result.trace)

    print(f"\n{'=' * 60}")
    print(f"📊 统计: {result.iterations} 轮迭代")
    if result.usage:
        print(f"   Token 用量: {result.usage}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
