"""异步多Agent协作与评判。

1.3.0 版本：添加并行参与者模式支持。
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict

from .agent import StreamEvent
from .async_agent import AsyncAgent
from .debate import (
    ConvergenceCheck,
    DebateResult,
    DebateRound,
    DebateStopReason,
    DebateTurn,
)
from .events import EventSink, RunContext, RunEventEmitter

# 并行执行模式类型
AsyncParticipantExecution = Literal["sequential", "parallel"]

SOLVER_PROMPT = """你是一个严谨的问题求解者。请分析问题并给出你的答案。

{role_context}
"""

CRITIC_PROMPT = """你是一个严格的审阅者。请检查已有回答的计算、推理、边界和假设。

{role_context}
"""

JUDGE_PROMPT = """你是一个公正的裁判。请综合所有参与者的意见并给出最终答案。

{role_context}
"""


@dataclass
class AsyncDebateRole:
    """一个配置好的参与者或裁判。"""

    name: str
    agent: AsyncAgent
    prompt: str
    role_context: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("role name must be non-empty")
        if not self.prompt.strip():
            raise ValueError(f"prompt for role {self.name!r} must be non-empty")


@dataclass
class AsyncDebateConfig:
    max_rounds: int = 3
    convergence_check: ConvergenceCheck | None = None
    participant_execution: AsyncParticipantExecution = "sequential"

    def __post_init__(self) -> None:
        if self.max_rounds < 1:
            raise ValueError("max_rounds must be at least 1")
        if self.participant_execution not in ("sequential", "parallel"):
            raise ValueError("participant_execution must be 'sequential' or 'parallel'")


class AsyncDebateRoundStartEvent(TypedDict):
    type: Literal["round_start"]
    round: int


class AsyncDebateSpeakerEvent(TypedDict):
    type: Literal["speaker"]
    role: str
    phase: Literal["participant", "judge"]
    round: int | None


class AsyncDebateAgentEvent(TypedDict):
    type: Literal["agent_event"]
    role: str
    event: StreamEvent


class AsyncDebateDoneEvent(TypedDict):
    type: Literal["debate_done"]
    verdict: str
    rounds: list[DebateRound]
    judge_turn: DebateTurn | None
    total_usage: dict[str, int]
    stop_reason: DebateStopReason
    converged: bool
    error: str | None


AsyncDebateStreamEvent = (
    AsyncDebateRoundStartEvent
    | AsyncDebateSpeakerEvent
    | AsyncDebateAgentEvent
    | AsyncDebateDoneEvent
)


class AsyncDebate:
    """运行顺序的参与者和一个单独的最终裁判。"""

    def __init__(
        self,
        participants: Sequence[AsyncDebateRole],
        *,
        judge: AsyncDebateRole | None = None,
        config: AsyncDebateConfig | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self.participants = list(participants)
        self.judge = judge
        self.config = config or AsyncDebateConfig()
        self.event_sink = event_sink
        self._validate_roles()

    def _validate_roles(self) -> None:
        if not self.participants:
            raise ValueError("at least one participant is required")

        names = [role.name for role in self.participants]
        if len(set(names)) != len(names):
            raise ValueError("participant role names must be unique")
        if self.judge is not None and self.judge.name in names:
            raise ValueError("Judge role name must be distinct from participant names")

    async def run_async(
        self,
        question: str,
        *,
        run_context: RunContext | None = None,
        event_sink: EventSink | None = None,
    ) -> DebateResult:
        """运行一次独立的异步协作。"""
        total_usage: dict[str, int] = {}
        rounds: list[DebateRound] = []
        converged = False

        emitter = RunEventEmitter(
            sink=event_sink or self.event_sink,
            run_id=run_context.run_id if run_context else None,
            parent_run_id=run_context.parent_run_id if run_context else None,
        )
        emitter.emit("debate_started", {"question": question})

        for round_number in range(1, self.config.max_rounds + 1):
            if self.config.participant_execution == "parallel":
                turns, failed_turn = await self._run_parallel_round(
                    question, rounds, round_number, emitter
                )
            else:
                turns, failed_turn = await self._run_sequential_round(
                    question, rounds, round_number, emitter
                )

            for turn in turns:
                self._accumulate_usage(total_usage, turn.usage)

            debate_round = DebateRound(number=round_number, turns=turns)
            rounds.append(debate_round)

            if failed_turn is not None:
                emitter.emit("debate_finished", {"stop_reason": "participant_error"})
                return DebateResult(
                    rounds=rounds,
                    total_usage=total_usage,
                    stop_reason="participant_error",
                    error=self._turn_error(failed_turn),
                    run_id=emitter.run_id,
                )

            if (
                self.config.convergence_check is not None
                and self.config.convergence_check(debate_round)
            ):
                converged = True
                break

        if self.judge is None:
            emitter.emit("debate_finished", {"stop_reason": "no_judge"})
            return DebateResult(
                rounds=rounds,
                total_usage=total_usage,
                stop_reason="no_judge",
                converged=converged,
                run_id=emitter.run_id,
            )

        judge_turn = await self._run_role(
            self.judge,
            self._build_context(self.judge, question, rounds, []),
            emitter.child(),
        )
        self._accumulate_usage(total_usage, judge_turn.usage)

        if judge_turn.stop_reason != "completed":
            emitter.emit("debate_finished", {"stop_reason": "judge_error"})
            return DebateResult(
                rounds=rounds,
                judge_turn=judge_turn,
                total_usage=total_usage,
                stop_reason="judge_error",
                converged=converged,
                error=self._turn_error(judge_turn),
                run_id=emitter.run_id,
            )

        emitter.emit(
            "debate_finished",
            {"stop_reason": "completed", "verdict": judge_turn.content},
        )
        return DebateResult(
            verdict=judge_turn.content,
            rounds=rounds,
            judge_turn=judge_turn,
            total_usage=total_usage,
            converged=converged,
            run_id=emitter.run_id,
        )

    def run_stream_async(
        self,
        question: str,
        *,
        run_context: RunContext | None = None,
        event_sink: EventSink | None = None,
    ) -> AsyncIterator[AsyncDebateStreamEvent]:
        """运行一次独立的流式异步协作。"""
        return self._run_stream_async_impl(question, run_context, event_sink)

    async def _run_stream_async_impl(
        self,
        question: str,
        run_context: RunContext | None = None,
        event_sink: EventSink | None = None,
    ) -> AsyncIterator[AsyncDebateStreamEvent]:
        """流式实现。"""
        import asyncio

        total_usage: dict[str, int] = {}
        rounds: list[DebateRound] = []
        converged = False

        emitter = RunEventEmitter(
            sink=event_sink or self.event_sink,
            run_id=run_context.run_id if run_context else None,
            parent_run_id=run_context.parent_run_id if run_context else None,
        )
        emitter.emit("debate_started", {"question": question})

        for round_number in range(1, self.config.max_rounds + 1):
            yield AsyncDebateRoundStartEvent(type="round_start", round=round_number)
            turns: list[DebateTurn] = []
            failed_turn: DebateTurn | None = None

            if self.config.participant_execution == "parallel":
                # 并行流式回合：使用队列复用事件
                queue: asyncio.Queue[AsyncDebateStreamEvent | None] = asyncio.Queue(
                    maxsize=100
                )
                turn_containers: list[list[DebateTurn | None]] = [
                    [None] for _ in self.participants
                ]
                tasks: list[asyncio.Task[None]] = []
                active_count = 0

                async def worker(
                    role: AsyncDebateRole,
                    context: str,
                    child_emitter: RunEventEmitter,
                    turn_container: list[DebateTurn | None],
                ) -> None:
                    nonlocal active_count
                    try:
                        done_event: StreamEvent | None = None
                        async for event in role.agent.run_stream_async(context):
                            agent_event: AsyncDebateAgentEvent = {
                                "type": "agent_event",
                                "role": role.name,
                                "event": event,
                            }
                            await queue.put(agent_event)
                            if event["type"] == "done":
                                done_event = event

                        if done_event is None:
                            turn = DebateTurn(
                                role=role.name,
                                content="",
                                stop_reason="incomplete",
                                error=f"role {role.name!r} stream ended without a done event",
                                run_id=child_emitter.run_id,
                            )
                        else:
                            turn = DebateTurn(
                                role=role.name,
                                content=done_event["content"],
                                usage=done_event["usage"],
                                stop_reason=done_event["stop_reason"],
                                error=done_event.get("error"),
                                run_id=child_emitter.run_id,
                            )
                        turn_container[0] = turn
                    except asyncio.CancelledError:
                        raise
                    finally:
                        await queue.put(None)

                try:
                    # 启动所有工作任务
                    for i, role in enumerate(self.participants):
                        context = self._build_context(role, question, rounds, [])
                        task = asyncio.create_task(
                            worker(role, context, emitter.child(), turn_containers[i]),
                            name=f"parallel_stream_{role.name}",
                        )
                        tasks.append(task)
                        active_count += 1

                    # Yield speaker 事件
                    for role in self.participants:
                        yield AsyncDebateSpeakerEvent(
                            type="speaker",
                            role=role.name,
                            phase="participant",
                            round=round_number,
                        )

                    # 收集并 yield 所有事件
                    while active_count > 0:
                        event = await queue.get()
                        if event is None:
                            active_count -= 1
                        else:
                            yield event

                    # 等待所有任务完成
                    await asyncio.gather(*tasks, return_exceptions=True)

                finally:
                    # 取消所有未完成的任务
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)

                # 按声明顺序归档结果
                for i, container in enumerate(turn_containers):
                    turn = container[0]
                    if turn is not None:
                        turns.append(turn)
                    else:
                        turns.append(
                            DebateTurn(
                                role=self.participants[i].name,
                                content="",
                                stop_reason="incomplete",
                                error="parallel stream task cancelled or failed",
                                run_id=emitter.run_id,
                            )
                        )

                # 检查是否有失败的参与者
                failed_turn = next(
                    (turn for turn in turns if turn.stop_reason != "completed"), None
                )
            else:
                # 顺序流式回合
                for role in self.participants:
                    yield AsyncDebateSpeakerEvent(
                        type="speaker",
                        role=role.name,
                        phase="participant",
                        round=round_number,
                    )
                    turn_container: list[DebateTurn | None] = [None]
                    async for event in self._pump_and_yield_stream_role(
                        role,
                        self._build_context(role, question, rounds, turns),
                        emitter.child(),
                        turn_container,
                    ):
                        yield event
                    turn = turn_container[0]
                    assert turn is not None
                    turns.append(turn)
                    if turn.stop_reason != "completed":
                        failed_turn = turn
                        break

            for turn in turns:
                self._accumulate_usage(total_usage, turn.usage)

            debate_round = DebateRound(number=round_number, turns=turns)
            rounds.append(debate_round)

            if failed_turn is not None:
                result = DebateResult(
                    rounds=rounds,
                    total_usage=total_usage,
                    stop_reason="participant_error",
                    error=self._turn_error(failed_turn),
                    run_id=emitter.run_id,
                )
                emitter.emit("debate_finished", {"stop_reason": "participant_error"})
                yield self._done_event(result)
                return

            if (
                self.config.convergence_check is not None
                and self.config.convergence_check(debate_round)
            ):
                converged = True
                break

        if self.judge is None:
            result = DebateResult(
                rounds=rounds,
                total_usage=total_usage,
                stop_reason="no_judge",
                converged=converged,
                run_id=emitter.run_id,
            )
            emitter.emit("debate_finished", {"stop_reason": "no_judge"})
            yield self._done_event(result)
            return

        yield AsyncDebateSpeakerEvent(
            type="speaker",
            role=self.judge.name,
            phase="judge",
            round=None,
        )
        judge_turn_container: list[DebateTurn | None] = [None]
        async for event in self._pump_and_yield_stream_role(
            self.judge,
            self._build_context(self.judge, question, rounds, []),
            emitter.child(),
            judge_turn_container,
        ):
            yield event
        judge_turn = judge_turn_container[0]
        assert judge_turn is not None
        self._accumulate_usage(total_usage, judge_turn.usage)

        if judge_turn.stop_reason != "completed":
            result = DebateResult(
                rounds=rounds,
                judge_turn=judge_turn,
                total_usage=total_usage,
                stop_reason="judge_error",
                converged=converged,
                error=self._turn_error(judge_turn),
                run_id=emitter.run_id,
            )
            emitter.emit("debate_finished", {"stop_reason": "judge_error"})
        else:
            result = DebateResult(
                verdict=judge_turn.content,
                rounds=rounds,
                judge_turn=judge_turn,
                total_usage=total_usage,
                converged=converged,
                run_id=emitter.run_id,
            )
            emitter.emit(
                "debate_finished",
                {"stop_reason": "completed", "verdict": judge_turn.content},
            )

        yield self._done_event(result)

    async def _run_sequential_round(
        self,
        question: str,
        rounds: list[DebateRound],
        round_number: int,
        emitter: RunEventEmitter,
    ) -> tuple[list[DebateTurn], DebateTurn | None]:
        """运行一个顺序的回合。"""
        turns: list[DebateTurn] = []
        for role in self.participants:
            turn = await self._run_role(
                role,
                self._build_context(role, question, rounds, turns),
                emitter.child(),
            )
            turns.append(turn)
            if turn.stop_reason != "completed":
                return turns, turn
        return turns, None

    async def _run_parallel_round(
        self,
        question: str,
        rounds: list[DebateRound],
        round_number: int,
        emitter: RunEventEmitter,
    ) -> tuple[list[DebateTurn], DebateTurn | None]:
        """运行一个并行的回合。

        并行参与者只读取已完成轮次，不读取同轮其他参与者的回答。
        结果按声明顺序归档。
        """
        import asyncio

        # 为每个参与者构建上下文（基于已完成轮次，不包含同轮回答）
        contexts = [
            self._build_context(role, question, rounds, [])
            for role in self.participants
        ]

        # 并行执行所有参与者（return_exceptions=True 捕获异常）
        turn_results = await asyncio.gather(
            *[
                self._run_role(role, context, emitter.child())
                for role, context in zip(self.participants, contexts, strict=True)
            ],
            return_exceptions=True,
        )

        # 按声明顺序归档结果，处理异常
        turns: list[DebateTurn] = []
        for i, result in enumerate(turn_results):
            if isinstance(result, Exception):
                # 参与者抛出异常，创建错误 turn
                turns.append(
                    DebateTurn(
                        role=self.participants[i].name,
                        content="",
                        stop_reason="model_error",
                        error=f"participant raised exception: {type(result).__name__}",
                        run_id=emitter.run_id,
                    )
                )
            else:
                turns.append(result)

        # 检查是否有失败的参与者
        failed_turn = next(
            (turn for turn in turns if turn.stop_reason != "completed"), None
        )

        return turns, failed_turn

    async def _run_role(
        self,
        role: AsyncDebateRole,
        context: str,
        child_emitter: RunEventEmitter,
    ) -> DebateTurn:
        """运行一个角色。"""
        result = await role.agent.run_async(
            context, run_context=child_emitter.context()
        )
        return DebateTurn(
            role=role.name,
            content=result.content,
            usage=result.usage,
            stop_reason=result.stop_reason,
            error=result.error,
            run_id=child_emitter.run_id,
        )

    async def _pump_and_yield_stream_role(
        self,
        role: AsyncDebateRole,
        context: str,
        child_emitter: RunEventEmitter,
        turn_container: list[DebateTurn | None],
    ) -> AsyncIterator[AsyncDebateAgentEvent]:
        """流式运行一个角色，yield 事件，同时通过容器返回最终的 turn。"""
        done_event: StreamEvent | None = None
        async for event in role.agent.run_stream_async(context):
            agent_event: AsyncDebateAgentEvent = {
                "type": "agent_event",
                "role": role.name,
                "event": event,
            }
            yield agent_event
            if event["type"] == "done":
                done_event = event

        if done_event is None:
            turn = DebateTurn(
                role=role.name,
                content="",
                stop_reason="incomplete",
                error=f"role {role.name!r} stream ended without a done event",
                run_id=child_emitter.run_id,
            )
        else:
            turn = DebateTurn(
                role=role.name,
                content=done_event["content"],
                usage=done_event["usage"],
                stop_reason=done_event["stop_reason"],
                error=done_event.get("error"),
                run_id=child_emitter.run_id,
            )
        turn_container[0] = turn

    @staticmethod
    def _build_context(
        role: AsyncDebateRole,
        question: str,
        rounds: list[DebateRound],
        current_turns: list[DebateTurn],
    ) -> str:
        """构建上下文。"""
        history = [f"User: {question}"]
        for debate_round in rounds:
            for turn in debate_round.turns:
                history.append(f"[{turn.role}]: {turn.content}")
        for turn in current_turns:
            history.append(f"[{turn.role}]: {turn.content}")

        prompt = role.prompt.format(role_context=role.role_context)
        return f"{prompt}\n\n## Conversation\n\n" + "\n".join(history)

    @staticmethod
    def _turn_error(turn: DebateTurn) -> str:
        return turn.error or f"role {turn.role!r} stopped with {turn.stop_reason}"

    @staticmethod
    def _done_event(result: DebateResult) -> AsyncDebateDoneEvent:
        return AsyncDebateDoneEvent(
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


def create_async_debate(
    solver: AsyncAgent,
    critic: AsyncAgent,
    judge: AsyncAgent,
    *,
    max_rounds: int = 3,
    participant_execution: AsyncParticipantExecution = "sequential",
    solver_context: str = "",
    critic_context: str = "",
) -> AsyncDebate:
    """创建常规的求解者、审阅者和裁判协作流。"""
    return AsyncDebate(
        participants=[
            AsyncDebateRole("Solver", solver, SOLVER_PROMPT, solver_context),
            AsyncDebateRole("Critic", critic, CRITIC_PROMPT, critic_context),
        ],
        judge=AsyncDebateRole("Judge", judge, JUDGE_PROMPT),
        config=AsyncDebateConfig(
            max_rounds=max_rounds,
            participant_execution=participant_execution,
        ),
    )
