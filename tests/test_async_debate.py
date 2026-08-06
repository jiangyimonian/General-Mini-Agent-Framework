from collections import deque

import pytest

from general_mini_agent.agent import AgentResult
from general_mini_agent.async_debate import (
    AsyncDebate,
    AsyncDebateConfig,
    AsyncDebateRole,
    create_async_debate,
)
from general_mini_agent.debate import DebateRound


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
