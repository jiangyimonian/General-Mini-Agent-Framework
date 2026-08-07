from collections import deque

import pytest

from general_mini_agent.agent import AgentResult
from general_mini_agent.async_debate import (
    AsyncDebate,
    AsyncDebateConfig,
    AsyncDebateRole,
    create_async_debate,
)
from general_mini_agent.debate import DebateResult, DebateRound


class ScriptedAsyncAgent:
    def __init__(self, *responses: AgentResult) -> None:
        self._responses = deque(responses)
        self.inputs: list[str] = []

    async def run_async(self, user_input: str, *, run_context=None) -> AgentResult:
        self.inputs.append(user_input)
        return self._responses.popleft()

    async def run_stream_async(self, user_input: str, *, memory_query=None):
        self.inputs.append(user_input)
        result = self._responses.popleft()
        event = {
            "type": "done",
            "content": result.content,
            "trace": result.trace,
            "usage": result.usage,
            "iterations": result.iterations,
            "stop_reason": result.stop_reason,
        }
        if result.error is not None:
            event["error"] = result.error
        yield event


def completed(content: str, tokens: int = 1) -> AgentResult:
    return AgentResult(
        content=content,
        usage={"total_tokens": tokens},
        stop_reason="completed",
    )


def failed(content: str, error: str, tokens: int = 1) -> AgentResult:
    return AgentResult(
        content=content,
        usage={"total_tokens": tokens},
        stop_reason="model_error",
        error=error,
    )


def async_role(name: str, agent: ScriptedAsyncAgent | None = None) -> AsyncDebateRole:
    return AsyncDebateRole(
        name=name,
        agent=agent or ScriptedAsyncAgent(completed("unused")),  # type: ignore[arg-type]
        prompt=f"You are {name}.\n{{role_context}}",
    )


def test_async_debate_config_rejects_non_positive_max_rounds() -> None:
    with pytest.raises(ValueError, match="max_rounds"):
        AsyncDebateConfig(max_rounds=0)


def test_async_debate_requires_participants_with_unique_role_names() -> None:
    agent = ScriptedAsyncAgent(completed("unused"))

    with pytest.raises(ValueError, match="at least one participant"):
        AsyncDebate([])
    with pytest.raises(ValueError, match="unique"):
        AsyncDebate([async_role("Solver", agent), async_role("Solver", agent)])
    with pytest.raises(ValueError, match="distinct"):
        AsyncDebate([async_role("Judge", agent)], judge=async_role("Judge", agent))


@pytest.mark.asyncio
async def test_async_run_returns_typed_round_and_separate_judge_turn() -> None:
    participant = ScriptedAsyncAgent(completed("proposal", 2))
    judge = ScriptedAsyncAgent(completed("verdict", 3))
    debate = AsyncDebate(
        [async_role("Solver", participant)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1),
    )

    result = await debate.run_async("question")

    assert result.verdict == "verdict"
    assert result.stop_reason == "completed"
    assert result.total_usage == {"total_tokens": 5}
    assert isinstance(result.rounds[0], DebateRound)
    assert result.rounds[0].number == 1
    assert len(result.rounds[0].turns) == 1
    turn = result.rounds[0].turns[0]
    assert turn.role == "Solver"
    assert turn.content == "proposal"
    assert turn.usage == {"total_tokens": 2}
    assert turn.stop_reason == "completed"
    assert turn.run_id  # non-empty

    assert result.judge_turn is not None
    assert result.judge_turn.role == "Judge"
    assert result.judge_turn.content == "verdict"
    assert result.judge_turn.usage == {"total_tokens": 3}
    assert result.judge_turn.stop_reason == "completed"
    assert result.judge_turn.run_id  # non-empty

    # Debate run_id should be set
    assert result.run_id


@pytest.mark.asyncio
async def test_repeated_async_runs_do_not_share_context() -> None:
    participant = ScriptedAsyncAgent(completed("first"), completed("second"))
    judge = ScriptedAsyncAgent(completed("first verdict"), completed("second verdict"))
    debate = AsyncDebate(
        [async_role("Solver", participant)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1),
    )

    await debate.run_async("first question")
    await debate.run_async("second question")

    assert "first question" in participant.inputs[0]
    assert "first question" not in participant.inputs[1]
    assert "first" not in judge.inputs[1]
    assert "second question" in participant.inputs[1]
    assert "second question" in judge.inputs[1]


@pytest.mark.asyncio
async def test_sequential_async_debate_preserves_same_round_context_and_runs_judge() -> None:
    solver = ScriptedAsyncAgent(completed("proposal", 2))
    critic = ScriptedAsyncAgent(completed("review", 3))
    judge = ScriptedAsyncAgent(completed("verdict", 5))
    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1),
    )

    result = await debate.run_async("question")

    assert result.stop_reason == "completed"
    assert result.verdict == "verdict"
    assert result.total_usage == {"total_tokens": 10}
    assert "[Solver]: proposal" in critic.inputs[0]
    assert "[Critic]: review" in judge.inputs[0]
    assert [turn.role for turn in result.rounds[0].turns] == ["Solver", "Critic"]
    assert result.run_id and all(turn.run_id for turn in result.rounds[0].turns)


@pytest.mark.asyncio
async def test_sequential_async_debate_stops_before_later_roles_after_failure() -> None:
    solver = ScriptedAsyncAgent(failed("partial", "unavailable", 2))
    critic = ScriptedAsyncAgent(completed("must not run"))
    judge = ScriptedAsyncAgent(completed("must not run"))
    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=2),
    )

    result = await debate.run_async("question")

    assert result.stop_reason == "participant_error"
    assert result.error == "unavailable"
    assert critic.inputs == []
    assert judge.inputs == []


@pytest.mark.asyncio
async def test_multiple_rounds_complete_before_judge_runs_once() -> None:
    solver = ScriptedAsyncAgent(completed("s1"), completed("s2"), completed("s3"))
    critic = ScriptedAsyncAgent(completed("c1"), completed("c2"), completed("c3"))
    judge = ScriptedAsyncAgent(completed("final"))
    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=3),
    )

    result = await debate.run_async("question")

    assert [round_.number for round_ in result.rounds] == [1, 2, 3]
    assert [[turn.role for turn in round_.turns] for round_ in result.rounds] == [
        ["Solver", "Critic"],
        ["Solver", "Critic"],
        ["Solver", "Critic"],
    ]
    assert len(solver.inputs) == 3
    assert len(critic.inputs) == 3
    assert len(judge.inputs) == 1
    assert "[Solver]: s3" in judge.inputs[0]
    assert "[Critic]: c3" in judge.inputs[0]


@pytest.mark.asyncio
async def test_convergence_transitions_after_complete_round() -> None:
    solver = ScriptedAsyncAgent(completed("proposal"))
    critic = ScriptedAsyncAgent(completed("approved"))
    judge = ScriptedAsyncAgent(completed("final"))
    checked_rounds: list[int] = []

    def converged(round_: DebateRound) -> bool:
        checked_rounds.append(round_.number)
        return True

    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=3, convergence_check=converged),
    )

    result = await debate.run_async("question")

    assert checked_rounds == [1]
    assert len(result.rounds) == 1
    assert [turn.role for turn in result.rounds[0].turns] == ["Solver", "Critic"]
    assert result.converged is True
    assert len(judge.inputs) == 1


@pytest.mark.asyncio
async def test_create_async_debate_builds_three_role_convenience_flow() -> None:
    solver = ScriptedAsyncAgent(completed("proposal"))
    critic = ScriptedAsyncAgent(completed("review"))
    judge = ScriptedAsyncAgent(completed("final"))

    debate = create_async_debate(
        solver,  # type: ignore[arg-type]
        critic,  # type: ignore[arg-type]
        judge,  # type: ignore[arg-type]
        max_rounds=1,
        solver_context="solve carefully",
        critic_context="check carefully",
    )
    result = await debate.run_async("question")

    assert [turn.role for turn in result.rounds[0].turns] == ["Solver", "Critic"]
    assert result.judge_turn is not None
    assert result.judge_turn.role == "Judge"
    assert "solve carefully" in solver.inputs[0]
    assert "check carefully" in critic.inputs[0]


@pytest.mark.asyncio
async def test_judge_failure_preserves_rounds_without_a_verdict() -> None:
    participant = ScriptedAsyncAgent(completed("proposal", 2))
    judge = ScriptedAsyncAgent(failed("partial verdict", "judge unavailable", 3))
    debate = AsyncDebate(
        [async_role("Solver", participant)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1),
    )

    result = await debate.run_async("question")

    assert result.stop_reason == "judge_error"
    assert result.error == "judge unavailable"
    assert result.verdict == ""
    assert result.judge_turn is not None
    assert result.judge_turn.content == "partial verdict"
    assert result.total_usage == {"total_tokens": 5}


@pytest.mark.asyncio
async def test_missing_judge_returns_explicit_terminal_result() -> None:
    participant = ScriptedAsyncAgent(completed("proposal"))
    debate = AsyncDebate(
        [async_role("Solver", participant)],
        config=AsyncDebateConfig(max_rounds=1),
    )

    result = await debate.run_async("question")

    assert result.stop_reason == "no_judge"
    assert result.verdict == ""
    assert result.judge_turn is None


@pytest.mark.asyncio
async def test_async_stream_runs_are_isolated_and_end_with_one_terminal_event() -> None:
    participant = ScriptedAsyncAgent(completed("first"), completed("second"))
    judge = ScriptedAsyncAgent(completed("first verdict"), completed("second verdict"))
    debate = AsyncDebate(
        [async_role("Solver", participant)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1),
    )

    first_events = [event async for event in debate.run_stream_async("first question")]
    second_events = [
        event async for event in debate.run_stream_async("second question")
    ]

    assert [event["role"] for event in first_events if event["type"] == "speaker"] == [
        "Solver",
        "Judge",
    ]
    first_done = [event for event in first_events if event["type"] == "debate_done"]
    second_done = [event for event in second_events if event["type"] == "debate_done"]
    assert len(first_done) == 1
    assert first_done[0]["verdict"] == "first verdict"
    assert first_done[0]["stop_reason"] == "completed"
    assert len(second_done) == 1
    assert second_done[0]["verdict"] == "second verdict"
    assert "first question" not in participant.inputs[1]
    assert "first" not in judge.inputs[1]


@pytest.mark.asyncio
async def test_sequential_async_stream_keeps_speaker_order_and_emits_one_terminal_result() -> None:
    solver = ScriptedAsyncAgent(
        completed("proposal", 2), completed("proposal", 2)
    )
    critic = ScriptedAsyncAgent(
        completed("review", 3), completed("review", 3)
    )
    judge = ScriptedAsyncAgent(
        completed("verdict", 5), completed("verdict", 5)
    )
    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1),
    )

    events = [event async for event in debate.run_stream_async("question")]

    assert [event["role"] for event in events if event["type"] == "speaker"] == [
        "Solver",
        "Critic",
        "Judge",
    ]
    assert [event for event in events if event["type"] == "debate_done"][0][
        "verdict"
    ] == "verdict"


def test_core_exports_stable_async_debate_contracts() -> None:
    from general_mini_agent import AsyncDebate as ExportedAsyncDebate
    from general_mini_agent import AsyncDebateConfig as ExportedAsyncDebateConfig
    from general_mini_agent import AsyncDebateRole as ExportedAsyncDebateRole

    assert ExportedAsyncDebate is AsyncDebate
    assert ExportedAsyncDebateConfig is AsyncDebateConfig
    assert ExportedAsyncDebateRole is AsyncDebateRole


# =============================================================================
# 1.3.0 Parallel Async Debate Tests
# =============================================================================


def test_async_debate_config_rejects_invalid_execution_mode() -> None:
    """Task 1.3-A: 不支持的执行模式应报错。"""
    with pytest.raises(ValueError, match="participant_execution"):
        AsyncDebateConfig(participant_execution="invalid")  # type: ignore[arg-type]


def test_async_debate_config_defaults_to_sequential() -> None:
    """Task 1.3-A: 省略模式时应为 sequential。"""
    config = AsyncDebateConfig()
    assert config.participant_execution == "sequential"


@pytest.mark.asyncio
async def test_parallel_participants_do_not_see_same_round_answers() -> None:
    """Task 1.3-A: 并行参与者不能看到同轮其他参与者的回答。"""
    # 使用一个可以检查输入内容的 agent
    solver = ScriptedAsyncAgent(completed("proposal", 2))
    critic = ScriptedAsyncAgent(completed("review", 3))
    judge = ScriptedAsyncAgent(completed("verdict", 5))

    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    result = await debate.run_async("question")

    assert result.stop_reason == "completed"
    # Critic 不应该看到 Solver 的同轮回答（并行执行）
    assert "[Solver]: proposal" not in critic.inputs[0]
    # Judge 应该看到所有参与者的回答
    assert "[Solver]: proposal" in judge.inputs[0]
    assert "[Critic]: review" in judge.inputs[0]


@pytest.mark.asyncio
async def test_parallel_barrier_all_participants_start_before_any_completes() -> None:
    """Task 1.3-A: 并行参与者同时开始（barrier 测试）。"""
    import asyncio

    start_times: list[float] = []
    complete_times: list[float] = []

    class BarrierAsyncAgent:
        def __init__(self, name: str) -> None:
            self.name = name
            self.inputs: list[str] = []

        async def run_async(self, user_input: str, *, run_context=None) -> AgentResult:
            start_times.append(asyncio.get_event_loop().time())
            self.inputs.append(user_input)
            await asyncio.sleep(0.05)  # 模拟工作
            complete_times.append(asyncio.get_event_loop().time())
            return completed(f"{self.name} result")

    solver = BarrierAsyncAgent("Solver")
    critic = BarrierAsyncAgent("Critic")
    judge_agent = ScriptedAsyncAgent(completed("verdict"))

    debate = AsyncDebate(
        [
            AsyncDebateRole("Solver", solver, "You are Solver. {role_context}"),
            AsyncDebateRole("Critic", critic, "You are Critic. {role_context}"),
        ],
        judge=async_role("Judge", judge_agent),
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    await debate.run_async("question")

    # 验证两个参与者都已启动
    assert len(start_times) == 2
    assert len(complete_times) == 2

    # 并行执行：第一个完成时间应该早于第二个开始时间 + 容差
    # 即：两个参与者应该几乎同时开始（在彼此完成之前）
    # 排序后：start_times 应该都在前，complete_times 应该都在后
    all_times = sorted(start_times + complete_times)
    # 前两个应该是开始时间，后两个是完成时间
    assert all_times[0] in start_times and all_times[1] in start_times
    assert all_times[2] in complete_times and all_times[3] in complete_times


@pytest.mark.asyncio
async def test_parallel_results_are_archived_in_declaration_order() -> None:
    """Task 1.3-A: 并行结果按声明顺序归档。"""
    solver = ScriptedAsyncAgent(completed("proposal", 2))
    critic = ScriptedAsyncAgent(completed("review", 3))
    judge = ScriptedAsyncAgent(completed("verdict", 5))

    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    result = await debate.run_async("question")

    # 结果按声明顺序归档
    assert [turn.role for turn in result.rounds[0].turns] == ["Solver", "Critic"]
    assert result.rounds[0].turns[0].content == "proposal"
    assert result.rounds[0].turns[1].content == "review"


@pytest.mark.asyncio
async def test_parallel_usage_accumulated_correctly() -> None:
    """Task 1.3-A: 并行执行的 usage 正确累计。"""
    solver = ScriptedAsyncAgent(completed("proposal", 10))
    critic = ScriptedAsyncAgent(completed("review", 20))
    judge = ScriptedAsyncAgent(completed("verdict", 30))

    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    result = await debate.run_async("question")

    assert result.total_usage == {"total_tokens": 60}


# =============================================================================
# 1.3-B: Parallel Failure, Cancellation, and Stream Multiplexing
# =============================================================================


@pytest.mark.asyncio
async def test_parallel_round_with_partial_failure_preserves_all_turns() -> None:
    """Task 1.3-B: 并行回合中一个失败，所有 turn 保留，Judge 跳过。"""
    solver = ScriptedAsyncAgent(completed("proposal", 10))
    critic = ScriptedAsyncAgent(failed("partial", "critic error", 20))
    judge = ScriptedAsyncAgent(completed("must not run"))

    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    result = await debate.run_async("question")

    # 失败应该导致 participant_error
    assert result.stop_reason == "participant_error"
    assert result.error == "critic error"
    # 两个 turn 都应该保留
    assert len(result.rounds[0].turns) == 2
    assert result.rounds[0].turns[0].role == "Solver"
    assert result.rounds[0].turns[0].stop_reason == "completed"
    assert result.rounds[0].turns[1].role == "Critic"
    assert result.rounds[0].turns[1].stop_reason == "model_error"
    # usage 应该包含两个参与者的
    assert result.total_usage == {"total_tokens": 30}
    # Judge 不应该运行
    assert judge.inputs == []


@pytest.mark.asyncio
async def test_parallel_cancellation_propagates_to_all_participants() -> None:
    """Task 1.3-B: 取消应该传播到所有阻塞的参与者任务。"""
    import asyncio

    cancelled_count = 0
    started_count = 0

    class CancellableAsyncAgent:
        def __init__(self, name: str) -> None:
            self.name = name

        async def run_async(self, user_input: str, *, run_context=None) -> AgentResult:
            nonlocal cancelled_count, started_count
            started_count += 1
            try:
                await asyncio.sleep(10)  # 长时间睡眠，等待取消
                return completed(f"{self.name} result")
            except asyncio.CancelledError:
                cancelled_count += 1
                raise

    solver = CancellableAsyncAgent("Solver")
    critic = CancellableAsyncAgent("Critic")

    debate = AsyncDebate(
        [
            AsyncDebateRole("Solver", solver, "You are Solver. {role_context}"),
            AsyncDebateRole("Critic", critic, "You are Critic. {role_context}"),
        ],
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    async def run_with_timeout() -> DebateResult:
        async with asyncio.timeout(0.1):
            return await debate.run_async("question")

    with pytest.raises(asyncio.TimeoutError):
        await run_with_timeout()

    # 两个参与者都应该已启动
    assert started_count == 2
    # 取消应该传播到两个参与者
    assert cancelled_count == 2


@pytest.mark.asyncio
async def test_parallel_stream_events_identify_originating_role() -> None:
    """Task 1.3-B: 并行流式事件应该标识发起角色。"""
    solver = ScriptedAsyncAgent(completed("proposal", 2))
    critic = ScriptedAsyncAgent(completed("review", 3))
    judge = ScriptedAsyncAgent(completed("verdict", 5))

    debate = AsyncDebate(
        [async_role("Solver", solver), async_role("Critic", critic)],
        judge=async_role("Judge", judge),
        config=AsyncDebateConfig(max_rounds=1, participant_execution="parallel"),
    )

    events = [event async for event in debate.run_stream_async("question")]

    # 应该有 speaker 事件标识参与者
    speaker_events = [e for e in events if e["type"] == "speaker"]
    speaker_roles = [e["role"] for e in speaker_events]
    # Solver 和 Critic 应该在 speaker 事件中（并行）
    # Judge 也应该在
    assert "Solver" in speaker_roles
    assert "Critic" in speaker_roles
    assert "Judge" in speaker_roles

    # 应该有 agent_event 事件标识角色
    agent_events = [e for e in events if e["type"] == "agent_event"]
    for event in agent_events:
        assert "role" in event
        assert event["role"] in ("Solver", "Critic", "Judge")

    # 最终 rounds 应该按声明顺序
    done_events = [e for e in events if e["type"] == "debate_done"]
    assert len(done_events) == 1
    done_event = done_events[0]
    assert done_event["stop_reason"] == "completed"
    assert [turn.role for turn in done_event["rounds"][0].turns] == ["Solver", "Critic"]
