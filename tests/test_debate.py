from collections import deque

import pytest

from general_mini_agent.agent import AgentResult
from general_mini_agent.debate import (
    Debate,
    DebateConfig,
    DebateRole,
    DebateRound,
    DebateTurn,
    create_debate,
)


class ScriptedAgent:
    def __init__(self, *responses: AgentResult) -> None:
        self._responses = deque(responses)
        self.inputs: list[str] = []

    def run(self, user_input: str, *, run_context=None) -> AgentResult:
        self.inputs.append(user_input)
        return self._responses.popleft()

    def run_stream(self, user_input: str, *, run_context=None):
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


def role(name: str, agent: ScriptedAgent) -> DebateRole:
    return DebateRole(
        name=name,
        agent=agent,  # type: ignore[arg-type]
        prompt=f"You are {name}.\n{{role_context}}",
    )


def test_debate_config_rejects_non_positive_max_rounds() -> None:
    with pytest.raises(ValueError, match="max_rounds"):
        DebateConfig(max_rounds=0)


def test_debate_requires_participants_with_unique_role_names() -> None:
    agent = ScriptedAgent(completed("unused"))

    with pytest.raises(ValueError, match="participant"):
        Debate([])
    with pytest.raises(ValueError, match="unique"):
        Debate([role("Solver", agent), role("Solver", agent)])
    with pytest.raises(ValueError, match="Judge"):
        Debate([role("Judge", agent)], judge=role("Judge", agent))


def test_sync_run_returns_typed_round_and_separate_judge_turn() -> None:
    participant = ScriptedAgent(completed("proposal", 2))
    judge = ScriptedAgent(completed("verdict", 3))
    debate = Debate(
        [role("Solver", participant)],
        judge=role("Judge", judge),
        config=DebateConfig(max_rounds=1),
    )

    result = debate.run("question")

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


def test_repeated_sync_runs_do_not_share_context() -> None:
    participant = ScriptedAgent(completed("first"), completed("second"))
    judge = ScriptedAgent(completed("first verdict"), completed("second verdict"))
    debate = Debate(
        [role("Solver", participant)],
        judge=role("Judge", judge),
        config=DebateConfig(max_rounds=1),
    )

    debate.run("first question")
    debate.run("second question")

    assert "first question" in participant.inputs[0]
    assert "first question" not in participant.inputs[1]
    assert "first" not in judge.inputs[1]
    assert "second question" in participant.inputs[1]
    assert "second question" in judge.inputs[1]


def test_multiple_rounds_complete_before_judge_runs_once() -> None:
    solver = ScriptedAgent(completed("s1"), completed("s2"), completed("s3"))
    critic = ScriptedAgent(completed("c1"), completed("c2"), completed("c3"))
    judge = ScriptedAgent(completed("final"))
    debate = Debate(
        [role("Solver", solver), role("Critic", critic)],
        judge=role("Judge", judge),
        config=DebateConfig(max_rounds=3),
    )

    result = debate.run("question")

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


def test_convergence_transitions_after_complete_round() -> None:
    solver = ScriptedAgent(completed("proposal"))
    critic = ScriptedAgent(completed("approved"))
    judge = ScriptedAgent(completed("final"))
    checked_rounds: list[int] = []

    def converged(round_: DebateRound) -> bool:
        checked_rounds.append(round_.number)
        return True

    debate = Debate(
        [role("Solver", solver), role("Critic", critic)],
        judge=role("Judge", judge),
        config=DebateConfig(max_rounds=3, convergence_check=converged),
    )

    result = debate.run("question")

    assert checked_rounds == [1]
    assert len(result.rounds) == 1
    assert [turn.role for turn in result.rounds[0].turns] == ["Solver", "Critic"]
    assert result.converged is True
    assert len(judge.inputs) == 1


def test_create_debate_builds_three_role_convenience_flow() -> None:
    solver = ScriptedAgent(completed("proposal"))
    critic = ScriptedAgent(completed("review"))
    judge = ScriptedAgent(completed("final"))

    debate = create_debate(
        solver,  # type: ignore[arg-type]
        critic,  # type: ignore[arg-type]
        judge,  # type: ignore[arg-type]
        max_rounds=1,
        solver_context="solve carefully",
        critic_context="check carefully",
    )
    result = debate.run("question")

    assert [turn.role for turn in result.rounds[0].turns] == ["Solver", "Critic"]
    assert result.judge_turn is not None
    assert result.judge_turn.role == "Judge"
    assert "solve carefully" in solver.inputs[0]
    assert "check carefully" in critic.inputs[0]


def test_participant_failure_stops_before_later_roles_and_judge() -> None:
    solver = ScriptedAgent(failed("partial", "model unavailable", 2))
    critic = ScriptedAgent(completed("must not run"))
    judge = ScriptedAgent(completed("must not run"))
    debate = Debate(
        [role("Solver", solver), role("Critic", critic)],
        judge=role("Judge", judge),
        config=DebateConfig(max_rounds=2),
    )

    result = debate.run("question")

    assert result.stop_reason == "participant_error"
    assert result.error == "model unavailable"
    assert result.verdict == ""
    assert result.total_usage == {"total_tokens": 2}
    assert len(result.rounds) == 1
    assert result.rounds[0].turns[0].stop_reason == "model_error"
    assert critic.inputs == []
    assert judge.inputs == []


def test_judge_failure_preserves_rounds_without_a_verdict() -> None:
    participant = ScriptedAgent(completed("proposal", 2))
    judge = ScriptedAgent(failed("partial verdict", "judge unavailable", 3))
    debate = Debate(
        [role("Solver", participant)],
        judge=role("Judge", judge),
        config=DebateConfig(max_rounds=1),
    )

    result = debate.run("question")

    assert result.stop_reason == "judge_error"
    assert result.error == "judge unavailable"
    assert result.verdict == ""
    assert result.judge_turn is not None
    assert result.judge_turn.content == "partial verdict"
    assert result.total_usage == {"total_tokens": 5}


def test_missing_judge_returns_explicit_terminal_result() -> None:
    participant = ScriptedAgent(completed("proposal"))
    debate = Debate(
        [role("Solver", participant)],
        config=DebateConfig(max_rounds=1),
    )

    result = debate.run("question")

    assert result.stop_reason == "no_judge"
    assert result.verdict == ""
    assert result.judge_turn is None


def test_stream_runs_are_isolated_and_end_with_one_terminal_event() -> None:
    participant = ScriptedAgent(completed("first"), completed("second"))
    judge = ScriptedAgent(completed("first verdict"), completed("second verdict"))
    debate = Debate(
        [role("Solver", participant)],
        judge=role("Judge", judge),
        config=DebateConfig(max_rounds=1),
    )

    first_events = list(debate.run_stream("first question"))
    second_events = list(debate.run_stream("second question"))

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


def test_core_exports_stable_debate_contracts() -> None:
    from general_mini_agent import (
        Debate as ExportedDebate,
    )
    from general_mini_agent import (
        DebateConfig as ExportedDebateConfig,
    )
    from general_mini_agent import (
        DebateResult as ExportedDebateResult,
    )
    from general_mini_agent import (
        DebateRole as ExportedDebateRole,
    )
    from general_mini_agent import (
        DebateRound as ExportedDebateRound,
    )
    from general_mini_agent import (
        DebateStreamEvent,
    )
    from general_mini_agent import (
        DebateTurn as ExportedDebateTurn,
    )

    assert ExportedDebate is Debate
    assert ExportedDebateConfig is DebateConfig
    assert ExportedDebateRole is DebateRole
    assert ExportedDebateRound is DebateRound
    assert ExportedDebateTurn is DebateTurn
    assert ExportedDebateResult is not None
    assert DebateStreamEvent is not None
