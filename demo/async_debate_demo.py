"""
异步多 Agent 协作示例（离线演示，无需 API 密钥）。

展示 AsyncDebate 的基本用法：
- 异步顺序执行角色
- 流式输出
- 工作流集成
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from collections.abc import AsyncIterator
from dataclasses import dataclass

from general_mini_agent.agent import AgentResult
from general_mini_agent.async_agent import AsyncAgent
from general_mini_agent.async_debate import AsyncDebate, AsyncDebateRole, create_async_debate
from general_mini_agent.async_llm import AsyncChatModel
from general_mini_agent.events import EventCollector

# ─── 脚本化异步模型（无需网络）──────────────────────────────


@dataclass
class ScriptedAsyncChatModel(AsyncChatModel):
    """脚本化异步模型，按队列返回预设响应。"""

    responses: list[dict]

    def __post_init__(self):
        from collections import deque
        self._responses = deque(self.responses)
        self.calls: list[dict] = []

    async def chat_async(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ):
        from general_mini_agent.llm import LLMResponse
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            return LLMResponse(content="Done.", usage={})
        resp = self._responses.popleft()
        return LLMResponse(
            content=resp.get("content", ""),
            tool_calls=None,
            usage=resp.get("usage", {}),
        )

    def chat_stream_async(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        self.calls.append({"messages": messages, "tools": tools})
        if not self._responses:
            yield {"type": "text", "text": "Done."}
            return
        resp = self._responses.popleft()
        if resp.get("content"):
            yield {"type": "text", "text": resp["content"]}
        yield {"type": "usage", "usage": resp.get("usage", {})}


# ─── 脚本化 Agent（无需网络）──────────────────────────────


class ScriptedAsyncAgent(AsyncAgent):
    """脚本化异步 Agent，直接返回预设响应。"""

    def __init__(self, content: str):
        # 我们不使用真实 LLM
        self._content = content
        self.inputs: list[str] = []

    async def run_async(
        self,
        user_input: str,
        *,
        memory_query=None,
        run_context=None,
    ) -> AgentResult:
        self.inputs.append(user_input)
        return AgentResult(
            content=self._content,
            stop_reason="completed",
            usage={"total_tokens": 10},
        )

    async def run_stream_async(self, user_input: str, *, memory_query=None):
        self.inputs.append(user_input)
        yield {"type": "text", "text": self._content}
        yield {
            "type": "done",
            "content": self._content,
            "trace": [],
            "usage": {"total_tokens": 10},
            "iterations": 1,
            "stop_reason": "completed",
        }


# ─── 格式化（无 emoji）────────────────────────────────────


C = {
    "solver": "\033[36m",  # 青
    "critic": "\033[33m",  # 黄
    "judge": "\033[1;32m",  # 亮绿
    "dim": "\033[2m",
    "reset": "\033[0m",
}


def print_role(name: str, content: str) -> None:
    color = C.get(name.lower(), C["reset"])
    print(f"\n{color}--- {name} -------------------{C['reset']}")
    display = content[:500] + ("..." if len(content) > 500 else "")
    print(f"{display}")


# ─── 示例 1：基础用法 ───────────────────────────────────────


async def example_basic():
    """基础 AsyncDebate 用法示例。"""
    print(f"\n{C['dim']}{'=' * 50}{C['reset']}")
    print(f"\n{C['judge']}[ 示例 1：基础 AsyncDebate 用法 ]{C['reset']}")

    # 创建三个脚本化 Agent
    solver = ScriptedAsyncAgent("我认为答案是 2 + 2 = 4")
    critic = ScriptedAsyncAgent("我审查了计算，看起来是正确的")
    judge = ScriptedAsyncAgent("综合来看，最终答案是 4")

    # 创建异步辩论
    debate = AsyncDebate(
        participants=[
            AsyncDebateRole(
                name="Solver",
                agent=solver,
                prompt="You are a problem solver.\n{role_context}",
            ),
            AsyncDebateRole(
                name="Critic",
                agent=critic,
                prompt="You are a critic.\n{role_context}",
            ),
        ],
        judge=AsyncDebateRole(
            name="Judge",
            agent=judge,
            prompt="You are a judge.\n{role_context}",
        ),
    )

    # 运行异步辩论
    result = await debate.run_async("2 + 2 等于多少？")

    # 输出结果
    for r in result.rounds:
        print(f"\n{C['dim']}-- 第 {r.number} 轮辩论 --{C['reset']}")
        for turn in r.turns:
            print_role(turn.role, turn.content)

    print(f"\n{C['dim']}{'=' * 50}{C['reset']}")
    print(f"\n{C['judge']}[ 最终结论 ]{C['reset']}")
    print(f"  {result.verdict}")
    print(f"\n{C['dim']}Token 总计: {result.total_usage}{C['reset']}")


# ─── 示例 2：流式输出 ─────────────────────────────────────


async def example_streaming():
    """流式输出示例。"""
    print(f"\n{C['dim']}{'=' * 50}{C['reset']}")
    print(f"\n{C['judge']}[ 示例 2：流式输出 ]{C['reset']}")

    # 创建三个脚本化 Agent
    solver = ScriptedAsyncAgent("我建议答案是 42")
    critic = ScriptedAsyncAgent("我同意这个答案")
    judge = ScriptedAsyncAgent("最终判决是 42")

    # 创建异步辩论
    debate = create_async_debate(solver, critic, judge, max_rounds=1)

    # 流式运行
    print(f"\n{C['dim']}-- 开始流式辩论 --{C['reset']}")
    events = [event async for event in debate.run_stream_async("宇宙的答案是什么？")]

    for event in events:
        if event["type"] == "speaker":
            color = C.get(event["role"].lower(), C["reset"])
            print(f"\n{color}{event['role']} 正在发言...{C['reset']}")
        elif event["type"] == "debate_done":
            print(f"\n{C['judge']}辩论结束，最终结论: {event['verdict']}{C['reset']}")


# ─── 示例 3：事件收集 ─────────────────────────────────────


async def example_events():
    """事件收集示例。"""
    print(f"\n{C['dim']}{'=' * 50}{C['reset']}")
    print(f"\n{C['judge']}[ 示例 3：事件收集 ]{C['reset']}")

    # 创建三个脚本化 Agent
    solver = ScriptedAsyncAgent("让我想想...是 100")
    critic = ScriptedAsyncAgent("我认为应该是 100")
    judge = ScriptedAsyncAgent("最终答案就是 100")

    # 创建事件收集器
    collector = EventCollector()

    # 创建辩论并设置事件 sink
    debate = create_async_debate(solver, critic, judge, max_rounds=1)

    # 运行辩论，传入事件 sink
    result = await debate.run_async("50 + 50 = ?", event_sink=collector)

    # 输出收集到的事件类型
    print(f"\n{C['dim']}-- 收集到的事件类型 --{C['reset']}")
    for e in collector.snapshot():
        print(f"  * {e.type}")

    print(f"\n{C['judge']}最终结论: {result.verdict}{C['reset']}")


# ─── 示例 4：并行执行模式 ─────────────────────────────────────


async def example_parallel():
    """并行执行模式示例（1.3.0 新增）。"""
    print(f"\n{C['dim']}{'=' * 50}{C['reset']}")
    print(f"\n{C['judge']}[ 示例 4：并行执行模式 ]{C['reset']}")

    # 创建三个脚本化 Agent
    solver = ScriptedAsyncAgent("并行求解：答案是 3.14159")
    critic = ScriptedAsyncAgent("并行审查：确认正确")
    judge = ScriptedAsyncAgent("并行判决：最终答案 3.14159")

    # 创建并行辩论（participant_execution="parallel"）
    debate = create_async_debate(
        solver,
        critic,
        judge,
        max_rounds=1,
        participant_execution="parallel",  # 显式启用并行执行
    )

    # 运行并行辩论
    result = await debate.run_async("圆周率是多少？")

    # 输出结果
    print(f"\n{C['dim']}-- 并行模式下的参与者 --{C['reset']}")
    print("  并行参与者不读取同轮其他参与者的回答")
    print("  Judge 接收所有参与者的完整回答")

    for turn in result.rounds[0].turns:
        print_role(turn.role, turn.content)

    print(f"\n{C['judge']}最终结论: {result.verdict}{C['reset']}")

    # 流式并行示例
    print(f"\n{C['dim']}-- 流式并行模式 --{C['reset']}")
    solver2 = ScriptedAsyncAgent("流式并行求解")
    critic2 = ScriptedAsyncAgent("流式并行审查")
    judge2 = ScriptedAsyncAgent("流式并行判决")

    debate2 = create_async_debate(
        solver2,
        critic2,
        judge2,
        max_rounds=1,
        participant_execution="parallel",
    )

    events = [e async for e in debate2.run_stream_async("测试")]
    speaker_events = [e for e in events if e["type"] == "speaker"]
    print(f"  收集到 {len(speaker_events)} 个 speaker 事件")
    for e in speaker_events:
        print(f"    - {e['role']}")

    print(f"\n{C['judge']}并行模式示例完成！{C['reset']}")


# ─── 主入口 ───────────────────────────────────────────────


async def main():
    """运行所有示例。"""
    print(f"\n{C['judge']}=============================================={C['reset']}")
    print(f"{C['judge']}  异步多 Agent 协作 (AsyncDebate) 演示          {C['reset']}")
    print(f"{C['judge']}=============================================={C['reset']}")

    # 运行示例
    await example_basic()
    await example_streaming()
    await example_events()
    await example_parallel()

    print(f"\n{C['dim']}{'=' * 50}{C['reset']}")
    print(f"\n{C['judge']}所有示例运行完成！{C['reset']}\n")


if __name__ == "__main__":
    asyncio.run(main())
