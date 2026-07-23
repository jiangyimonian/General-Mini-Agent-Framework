"""基于 Solver、Critic 和 Judge 角色的多 Agent 协作编排器。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .agent import Agent

# ─── 角色定义 ────────────────────────────────────────────────

SOLVER_PROMPT = """你是一个严谨的问题求解者。请认真分析问题并给出你的答案。

{role_context}

当你得出最终结论后，请以「Final Answer:」开头给出你的最终回答。"""

CRITIC_PROMPT = """你是一个挑剔的审阅者。请仔细检查对方答案中的问题：

1. 计算是否有误？
2. 推理是否有逻辑漏洞？
3. 是否有未考虑的边界情况？
4. 假设是否合理？

{role_context}

请逐条指出问题。如果答案确实无懈可击，可以说「没有发现问题」。
当你完成审阅后，请以「Final Answer:」开头给出你的最终判断。"""

JUDGE_PROMPT = """你是一个公正的裁判。请审阅辩论双方的观点：

1. 综合双方论据
2. 判断谁的观点更可靠
3. 如果双方都没有完美解答，给出你的最佳答案

{role_context}

请以「Final Answer:」开头给出最终答案。"""


# ─── 角色配置 ────────────────────────────────────────────────


@dataclass
class DebateRole:
    """辩论角色"""
    name: str
    agent: Agent
    prompt: str
    role_context: str = ""


# ─── 辩论配置 ────────────────────────────────────────────────


@dataclass
class DebateConfig:
    max_rounds: int = 3          # 最大辩论轮数
    roles: list[DebateRole] = field(default_factory=list)
    convergence_threshold: float = 0.8  # 收敛阈值（裁判置信度）
    verbose: bool = True


# ─── 结果类型 ────────────────────────────────────────────────


@dataclass
class DebateResult:
    verdict: str                 # 最终结论
    rounds: list[dict]           # 每轮记录
    total_usage: dict[str, int]  # token 总计


# ─── 辩论编排器 ────────────────────────────────────────────


class Debate:
    """多 Agent 辩论编排器。

    使用方式:

        solver = Agent(llm=llm, tools=[...])
        critic = Agent(llm=llm, tools=[...])
        judge  = Agent(llm=llm, tools=[...])

        debate = Debate(solver=solver, critic=critic, judge=judge)
        result = debate.run("地球绕太阳的线速度是多少？")

        print(result.verdict)  # → 最终答案
        for r in result.rounds:
            print(r)           # → 每轮辩论记录
    """

    def __init__(
        self,
        solver: Agent | None = None,
        critic: Agent | None = None,
        judge: Agent | None = None,
        config: DebateConfig | None = None,
    ):
        self.config = config or DebateConfig()

        if solver:
            self._add_role("Solver", solver, SOLVER_PROMPT)
        if critic:
            self._add_role("Critic", critic, CRITIC_PROMPT)
        if judge:
            self._add_role("Judge", judge, JUDGE_PROMPT)

        self.shared_context: list[dict] = []

    def _add_role(self, name: str, agent: Agent, prompt: str):
        self.config.roles.append(DebateRole(
            name=name, agent=agent, prompt=prompt,
        ))

    # ── 主流程 ─────────────────────────────────────────

    def run(self, question: str) -> DebateResult:
        rounds: list[dict] = []
        total_usage: dict[str, int] = {}

        # 初始问题
        self.shared_context.append({
            "role": "user", "content": question,
        })

        for round_num in range(self.config.max_rounds):
            round_record = {"round": round_num, "responses": []}
            for role in self.config.roles:
                context = self._build_context_for_role(role)
                result = role.agent.run(context)
                round_record["responses"].append({
                    "role": role.name,
                    "content": result.content,
                    "usage": result.usage,
                })
                self._accumulate_usage(total_usage, result.usage)

                # 追加到共享上下文
                self.shared_context.append({
                    "role": "assistant",
                    "name": role.name,
                    "content": f"[{role.name}]: {result.content}",
                })

                # Judge 发言后辩论结束
                if role.name == "Judge":
                    rounds.append(round_record)
                    return DebateResult(
                        verdict=result.content,
                        rounds=rounds,
                        total_usage=total_usage,
                    )

                # 收敛检查：Critic 认可 Solver 时提前结束
                if role.name == "Critic" and self._has_converged(result.content):
                    # Judge 直接裁决
                    judge_role = next(
                        (r for r in self.config.roles if r.name == "Judge"), None
                    )
                    if judge_role:
                        self.shared_context.append({
                            "role": "user",
                            "content": (
                                "Critic 认为以下答案没有明显问题，"
                                "请你确认并给出最终判断：\n"
                                + round_record["responses"][0]["content"]
                            ),
                        })
                        judge_result = judge_role.agent.run(
                            self.shared_context[-1]["content"]
                        )
                        round_record["responses"].append({
                            "role": "Judge",
                            "content": judge_result.content,
                            "usage": judge_result.usage,
                        })
                        self._accumulate_usage(total_usage, judge_result.usage)
                        rounds.append(round_record)
                        return DebateResult(
                            verdict=judge_result.content,
                            rounds=rounds,
                            total_usage=total_usage,
                        )

            rounds.append(round_record)

        # 达到最大轮数，让最后一个可用 Judge 裁决
        judge_role = next(
            (r for r in self.config.roles if r.name == "Judge"), None
        )
        if judge_role:
            self.shared_context.append({
                "role": "user",
                "content": "辩论已达最大轮数，请给出你的最终判断。",
            })
            final = judge_role.agent.run(
                self.shared_context[-1]["content"]
            )
            self._accumulate_usage(total_usage, final.usage)
            return DebateResult(
                verdict=final.content,
                rounds=rounds,
                total_usage=total_usage,
            )

        return DebateResult(
            verdict="（辩论未达成一致）",
            rounds=rounds,
            total_usage=total_usage,
        )

    def run_stream(self, question: str):
        """流式辩论 — 逐事件 yield，供前端实时消费"""
        total_usage: dict[str, int] = {}

        self.shared_context.append({
            "role": "user", "content": question,
        })

        for round_num in range(self.config.max_rounds):
            yield {"type": "round_start", "round": round_num}

            for role in self.config.roles:
                yield {"type": "speaker", "role": role.name}

                for event in role.agent.run_stream(
                    self._build_context_for_role(role)
                ):
                    yield {**event, "role": role.name}  # 注入角色名

                    if event["type"] == "done":
                        self._accumulate_usage(total_usage, event.get("usage", {}))
                        self.shared_context.append({
                            "role": "assistant",
                            "name": role.name,
                            "content": f"[{role.name}]: {event['content']}",
                        })

                        if role.name == "Judge":
                            yield {
                                "type": "debate_done",
                                "verdict": event["content"],
                                "total_usage": total_usage,
                            }
                            return

    # ── 内部方法 ───────────────────────────────────────

    def _build_context_for_role(self, role: DebateRole) -> str:
        """为特定角色构建上下文提示"""
        # 共享对话历史
        history = "\n".join(
            f"{m.get('name', m['role'])}: {m['content']}"
            for m in self.shared_context
        )

        prompt = role.prompt.format(role_context=role.role_context)
        return f"{prompt}\n\n## 对话历史\n\n{history}"

    @staticmethod
    def _has_converged(critic_response: str) -> bool:
        """检查 Critic 是否认可答案"""
        indicators = [
            "没有发现问题",
            "无懈可击",
            "没有明显问题",
            "没有问题",
            "答案正确",
            "无需修正",
        ]
        return any(phrase in critic_response for phrase in indicators)

    @staticmethod
    def _accumulate_usage(total: dict, current: dict) -> None:
        for key, val in current.items():
            if isinstance(val, int):
                total[key] = total.get(key, 0) + val


# ─── 便捷工厂函数 ────────────────────────────────────────────


def create_debate(
    solver: Agent,
    critic: Agent,
    judge: Agent,
    *,
    max_rounds: int = 3,
    solver_context: str = "",
    critic_context: str = "",
) -> Debate:
    """快速创建三 Agent 辩论。

    Args:
        solver: 求解者
        critic: 审阅者
        judge: 裁判
        max_rounds: 最大辩论轮数
        solver_context: Solver 额外的角色说明
        critic_context: Critic 额外的角色说明
    """
    debate = Debate()

    # 定制角色上下文
    for role in [
        DebateRole("Solver", solver, SOLVER_PROMPT, solver_context),
        DebateRole("Critic", critic, CRITIC_PROMPT, critic_context),
        DebateRole("Judge", judge, JUDGE_PROMPT, ""),
    ]:
        debate.config.roles.append(role)

    debate.config.max_rounds = max_rounds
    return debate
