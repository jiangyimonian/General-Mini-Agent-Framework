"""1.3.1 稳定化测试：并行调度、资源清理和事件互操作。"""

import asyncio

import pytest

from general_mini_agent.agent import AgentResult
from general_mini_agent.async_debate import (
    AsyncDebate,
    AsyncDebateConfig,
    AsyncDebateRole,
)


class SlowAsyncAgent:
    """慢速 Agent，用于测试并发和取消。"""

    def __init__(self, content: str, delay: float = 0.1):
        self._content = content
        self._delay = delay
        self.started = False
        self.completed = False
        self.cancelled = False

    async def run_async(self, user_input: str, *, run_context=None) -> AgentResult:
        self.started = True
        try:
            await asyncio.sleep(self._delay)
            self.completed = True
            return AgentResult(
                content=self._content,
                stop_reason="completed",
                usage={"total_tokens": 10},
            )
        except asyncio.CancelledError:
            self.cancelled = True
            raise

    async def run_stream_async(self, user_input: str, *, memory_query=None):
        self.started = True
        try:
            await asyncio.sleep(self._delay)
            yield {"type": "text", "text": self._content}
            yield {
                "type": "done",
                "content": self._content,
                "trace": [],
                "usage": {"total_tokens": 10},
                "iterations": 1,
                "stop_reason": "completed",
            }
            self.completed = True
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_parallel_with_many_participants() -> None:
    """测试大量并行参与者（资源清理）。"""
    agents = [SlowAsyncAgent(f"response_{i}", delay=0.05) for i in range(10)]
    roles = [
        AsyncDebateRole(f"Agent{i}", agent, f"You are Agent{i}. {{role_context}}")
        for i, agent in enumerate(agents)
    ]
    judge = SlowAsyncAgent("verdict", delay=0.05)

    debate = AsyncDebate(
        participants=roles,
        judge=AsyncDebateRole("Judge", judge, "You are Judge. {role_context}"),
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    result = await debate.run_async("question")

    assert result.stop_reason == "completed"
    assert len(result.rounds[0].turns) == 10
    assert all(agent.started for agent in agents)
    assert all(agent.completed for agent in agents)


@pytest.mark.asyncio
async def test_parallel_stream_with_many_participants() -> None:
    """测试大量并行参与者流式（队列不阻塞）。"""
    agents = [SlowAsyncAgent(f"response_{i}", delay=0.05) for i in range(10)]
    roles = [
        AsyncDebateRole(f"Agent{i}", agent, f"You are Agent{i}. {{role_context}}")
        for i, agent in enumerate(agents)
    ]
    judge = SlowAsyncAgent("verdict", delay=0.05)

    debate = AsyncDebate(
        participants=roles,
        judge=AsyncDebateRole("Judge", judge, "You are Judge. {role_context}"),
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    events = [e async for e in debate.run_stream_async("question")]

    done_events = [e for e in events if e["type"] == "debate_done"]
    assert len(done_events) == 1
    assert done_events[0]["stop_reason"] == "completed"
    assert all(agent.started for agent in agents)
    assert all(agent.completed for agent in agents)


@pytest.mark.asyncio
async def test_parallel_early_cancellation_cleanup() -> None:
    """测试提前取消时的资源清理。"""
    agents = [SlowAsyncAgent(f"response_{i}", delay=1.0) for i in range(5)]
    roles = [
        AsyncDebateRole(f"Agent{i}", agent, f"You are Agent{i}. {{role_context}}")
        for i, agent in enumerate(agents)
    ]

    debate = AsyncDebate(
        participants=roles,
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    async def run_with_timeout():
        async with asyncio.timeout(0.1):
            await debate.run_async("question")

    with pytest.raises(asyncio.TimeoutError):
        await run_with_timeout()

    # 所有 agent 应该已启动
    assert all(agent.started for agent in agents)
    # 所有 agent 应该收到取消信号
    await asyncio.sleep(0.1)  # 给取消传播一些时间
    assert all(agent.cancelled for agent in agents)


@pytest.mark.asyncio
async def test_parallel_stream_early_cancellation_cleanup() -> None:
    """测试流式提前取消时的资源清理。"""
    agents = [SlowAsyncAgent(f"response_{i}", delay=1.0) for i in range(5)]
    roles = [
        AsyncDebateRole(f"Agent{i}", agent, f"You are Agent{i}. {{role_context}}")
        for i, agent in enumerate(agents)
    ]

    debate = AsyncDebate(
        participants=roles,
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    collected_events = []

    async def consume_with_timeout():
        async with asyncio.timeout(0.1):
            async for event in debate.run_stream_async("question"):
                collected_events.append(event)

    with pytest.raises(asyncio.TimeoutError):
        await consume_with_timeout()

    # 所有 agent 应该已启动
    assert all(agent.started for agent in agents)
    # 等待取消传播
    await asyncio.sleep(0.1)
    # 所有 agent 应该收到取消信号
    assert all(agent.cancelled for agent in agents)


@pytest.mark.asyncio
async def test_parallel_exception_in_one_participant_does_not_block_others() -> None:
    """测试一个参与者异常不阻塞其他参与者。"""

    class FailingAgent:
        def __init__(self):
            self.started = False

        async def run_async(self, user_input: str, *, run_context=None) -> AgentResult:
            self.started = True
            raise RuntimeError("simulated failure")

    failing = FailingAgent()
    success1 = SlowAsyncAgent("ok1", delay=0.05)
    success2 = SlowAsyncAgent("ok2", delay=0.05)

    debate = AsyncDebate(
        participants=[
            AsyncDebateRole("Failing", failing, "You fail. {role_context}"),
            AsyncDebateRole("Success1", success1, "You succeed. {role_context}"),
            AsyncDebateRole("Success2", success2, "You succeed. {role_context}"),
        ],
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    result = await debate.run_async("question")

    # 失败参与者应该标记为 incomplete
    assert result.stop_reason == "participant_error"
    # 所有参与者应该已启动
    assert failing.started
    assert success1.started
    assert success2.started
    # 成功的参与者应该完成
    assert success1.completed
    assert success2.completed
