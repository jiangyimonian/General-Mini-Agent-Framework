"""Deterministic multi-Agent participation and judging."""

from __future__ import annotations

from collections.abc import Callable, Generator, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from .agent import Agent, AgentStopReason, StreamEvent

SOLVER_PROMPT = """你是一个严谨的问题求解者。请分析问题并给出你的答案。

{role_context}
"""

CRITIC_PROMPT = """你是一个严格的审阅者。请检查已有回答的计算、推理、边界和假设。

{role_context}
"""

JUDGE_PROMPT = """你是一个公正的裁判。请综合所有参与者的意见并给出最终答案。

{role_context}
"""


DebateStopReason = Literal[
    "completed",
    "no_judge",
    "participant_error",
    "judge_error",
]


@dataclass
class DebateRole:
    """One configured participant or Judge."""

    name: str
    agent: Agent
    prompt: str
    role_context: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("role name must be non-empty")
        if not self.prompt.strip():
            raise ValueError(f"prompt for role {self.name!r} must be non-empty")


@dataclass
class DebateTurn:
    """The terminal result of one role execution."""

    role: str
    content: str
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: AgentStopReason = "completed"
    error: str | None = None

    def __post_init__(self) -> None:
        self.usage = dict(self.usage)


@dataclass
class DebateRound:
    """Participant turns completed in one round."""

    number: int
    turns: list[DebateTurn] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.turns = list(self.turns)


ConvergenceCheck = Callable[[DebateRound], bool]


@dataclass
class DebateConfig:
    max_rounds: int = 3
    convergence_check: ConvergenceCheck | None = None

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise ValueError("max_rounds must be at least 1")


@dataclass
class DebateResult:
    verdict: str = ""
    rounds: list[DebateRound] = field(default_factory=list)
    judge_turn: DebateTurn | None = None
    total_usage: dict[str, int] = field(default_factory=dict)
    stop_reason: DebateStopReason = "completed"
    converged: bool = False
    error: str | None = None


class DebateRoundStartEvent(TypedDict):
    type: Literal["round_start"]
    round: int


class DebateSpeakerEvent(TypedDict):
    type: Literal["speaker"]
    role: str
    phase: Literal["participant", "judge"]
    round: int | None


class DebateAgentEvent(TypedDict):
    type: Literal["agent_event"]
    role: str
    event: StreamEvent


class DebateDoneEvent(TypedDict):
    type: Literal["debate_done"]
    verdict: str
    rounds: list[DebateRound]
    judge_turn: DebateTurn | None
    total_usage: dict[str, int]
    stop_reason: DebateStopReason
    converged: bool
    error: str | None


DebateStreamEvent = (
    DebateRoundStartEvent | DebateSpeakerEvent | DebateAgentEvent | DebateDoneEvent
)


class Debate:
    """Run ordered participants and one separate final Judge."""

    def __init__(
        self,
        participants: Sequence[DebateRole],
        *,
        judge: DebateRole | None = None,
        config: DebateConfig | None = None,
    ) -> None:
        self.participants = list(participants)
        self.judge = judge
        self.config = config or DebateConfig()
        self._validate_roles()

    def _validate_roles(self) -> None:
        if not self.participants:
            raise ValueError("at least one participant is required")

        names = [role.name for role in self.participants]
        if len(set(names)) != len(names):
            raise ValueError("participant role names must be unique")
        if self.judge is not None and self.judge.name in names:
            raise ValueError("Judge role name must be distinct from participant names")

    def run(self, question: str) -> DebateResult:
        """Run one isolated synchronous collaboration."""
        total_usage: dict[str, int] = {}
        rounds: list[DebateRound] = []
        converged = False

        for round_number in range(1, self.config.max_rounds + 1):
            turns: list[DebateTurn] = []
            for participant in self.participants:
                result = participant.agent.run(
                    self._build_context(participant, question, rounds, turns)
                )
                turn = self._to_turn(participant, result)
                turns.append(turn)
                self._accumulate_usage(total_usage, turn.usage)
                if turn.stop_reason != "completed":
                    rounds.append(DebateRound(number=round_number, turns=turns))
                    return DebateResult(
                        rounds=rounds,
                        total_usage=total_usage,
                        stop_reason="participant_error",
                        error=self._turn_error(turn),
                    )

            debate_round = DebateRound(number=round_number, turns=turns)
            rounds.append(debate_round)
            if (
                self.config.convergence_check is not None
                and self.config.convergence_check(debate_round)
            ):
                converged = True
                break

        if self.judge is None:
            return DebateResult(
                rounds=rounds,
                total_usage=total_usage,
                stop_reason="no_judge",
                converged=converged,
            )

        judge_result = self.judge.agent.run(
            self._build_context(self.judge, question, rounds, [])
        )
        judge_turn = self._to_turn(self.judge, judge_result)
        self._accumulate_usage(total_usage, judge_turn.usage)
        if judge_turn.stop_reason != "completed":
            return DebateResult(
                rounds=rounds,
                judge_turn=judge_turn,
                total_usage=total_usage,
                stop_reason="judge_error",
                converged=converged,
                error=self._turn_error(judge_turn),
            )
        return DebateResult(
            verdict=judge_turn.content,
            rounds=rounds,
            judge_turn=judge_turn,
            total_usage=total_usage,
            converged=converged,
        )

    def run_stream(self, question: str) -> Iterator[DebateStreamEvent]:
        """Run one isolated streaming collaboration."""
        total_usage: dict[str, int] = {}
        rounds: list[DebateRound] = []
        converged = False

        for round_number in range(1, self.config.max_rounds + 1):
            yield DebateRoundStartEvent(type="round_start", round=round_number)
            turns: list[DebateTurn] = []
            for participant in self.participants:
                yield DebateSpeakerEvent(
                    type="speaker",
                    role=participant.name,
                    phase="participant",
                    round=round_number,
                )
                turn = yield from self._stream_role(
                    participant,
                    self._build_context(participant, question, rounds, turns),
                )
                turns.append(turn)
                self._accumulate_usage(total_usage, turn.usage)
                if turn.stop_reason != "completed":
                    rounds.append(DebateRound(number=round_number, turns=turns))
                    result = DebateResult(
                        rounds=rounds,
                        total_usage=total_usage,
                        stop_reason="participant_error",
                        error=self._turn_error(turn),
                    )
                    yield self._done_event(result)
                    return

            debate_round = DebateRound(number=round_number, turns=turns)
            rounds.append(debate_round)
            if (
                self.config.convergence_check is not None
                and self.config.convergence_check(debate_round)
            ):
                converged = True
                break

        if self.judge is None:
            yield self._done_event(
                DebateResult(
                    rounds=rounds,
                    total_usage=total_usage,
                    stop_reason="no_judge",
                    converged=converged,
                )
            )
            return

        yield DebateSpeakerEvent(
            type="speaker",
            role=self.judge.name,
            phase="judge",
            round=None,
        )
        judge_turn = yield from self._stream_role(
            self.judge,
            self._build_context(self.judge, question, rounds, []),
        )
        self._accumulate_usage(total_usage, judge_turn.usage)
        if judge_turn.stop_reason != "completed":
            result = DebateResult(
                rounds=rounds,
                judge_turn=judge_turn,
                total_usage=total_usage,
                stop_reason="judge_error",
                converged=converged,
                error=self._turn_error(judge_turn),
            )
        else:
            result = DebateResult(
                verdict=judge_turn.content,
                rounds=rounds,
                judge_turn=judge_turn,
                total_usage=total_usage,
                converged=converged,
            )
        yield self._done_event(result)

    def _stream_role(
        self,
        role: DebateRole,
        context: str,
    ) -> Generator[DebateAgentEvent, None, DebateTurn]:
        done_event: StreamEvent | None = None
        for event in role.agent.run_stream(context):
            yield DebateAgentEvent(type="agent_event", role=role.name, event=event)
            if event["type"] == "done":
                done_event = event

        if done_event is None:
            return DebateTurn(
                role=role.name,
                content="",
                stop_reason="incomplete",
                error=f"role {role.name!r} stream ended without a done event",
            )
        return DebateTurn(
            role=role.name,
            content=done_event["content"],
            usage=done_event["usage"],
            stop_reason=done_event["stop_reason"],
            error=done_event.get("error"),
        )

    @staticmethod
    def _build_context(
        role: DebateRole,
        question: str,
        rounds: list[DebateRound],
        current_turns: list[DebateTurn],
    ) -> str:
        history = [f"User: {question}"]
        for debate_round in rounds:
            for turn in debate_round.turns:
                history.append(f"[{turn.role}]: {turn.content}")
        for turn in current_turns:
            history.append(f"[{turn.role}]: {turn.content}")

        prompt = role.prompt.format(role_context=role.role_context)
        return f"{prompt}\n\n## Conversation\n\n" + "\n".join(history)

    @staticmethod
    def _to_turn(role: DebateRole, result: object) -> DebateTurn:
        return DebateTurn(
            role=role.name,
            content=getattr(result, "content"),
            usage=getattr(result, "usage"),
            stop_reason=getattr(result, "stop_reason"),
            error=getattr(result, "error"),
        )

    @staticmethod
    def _turn_error(turn: DebateTurn) -> str:
        return turn.error or f"role {turn.role!r} stopped with {turn.stop_reason}"

    @staticmethod
    def _done_event(result: DebateResult) -> DebateDoneEvent:
        return DebateDoneEvent(
            type="debate_done",
            verdict=result.verdict,
            rounds=result.rounds,
            judge_turn=result.judge_turn,
            total_usage=result.total_usage,
            stop_reason=result.stop_reason,
            converged=result.converged,
            error=result.error,
        )

    @staticmethod
    def _accumulate_usage(total: dict[str, int], current: dict[str, int]) -> None:
        for key, value in current.items():
            if isinstance(value, int):
                total[key] = total.get(key, 0) + value


def create_debate(
    solver: Agent,
    critic: Agent,
    judge: Agent,
    *,
    max_rounds: int = 3,
    solver_context: str = "",
    critic_context: str = "",
) -> Debate:
    """Create the conventional Solver, Critic, and Judge collaboration."""
    return Debate(
        participants=[
            DebateRole("Solver", solver, SOLVER_PROMPT, solver_context),
            DebateRole("Critic", critic, CRITIC_PROMPT, critic_context),
        ],
        judge=DebateRole("Judge", judge, JUDGE_PROMPT),
        config=DebateConfig(max_rounds=max_rounds),
    )
