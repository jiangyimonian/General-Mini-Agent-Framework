"""Workflow 节点适配器：将 Agent 和 Debate 接入工作流。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .events import RunContext, RunEventEmitter
from .workflow import JSONValue, NodeResult

if TYPE_CHECKING:
    from .agent import Agent, AgentResult
    from .async_agent import AsyncAgent
    from .debate import Debate, DebateResult


@dataclass
class AsyncAgentNode:
    """AsyncAgent 工作流节点适配器。

    将 AsyncAgent 接入工作流，字符串输入映射到 content。
    """

    agent: AsyncAgent

    async def run(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
        emitter: RunEventEmitter,
    ) -> NodeResult:
        """执行 AsyncAgent。

        Args:
            value: 输入值（必须是字符串）
            run_context: 运行上下文
            emitter: 事件发射器

        Returns:
            NodeResult: 节点结果
        """
        # 验证输入是字符串
        if not isinstance(value, str):
            return NodeResult(
                value=None,
                run_id=run_context.run_id,
                error_code="invalid_node_input",
                error="AsyncAgentNode requires string input",
            )

        # 临时设置 event_sink
        original_sink = self.agent.event_sink
        self.agent.event_sink = emitter._sink  # type: ignore[assignment]

        try:
            # 执行 Agent
            result = await self.agent.run(value)

            # 转换结果
            return self._convert_result(result, run_context)
        finally:
            # 恢复原始 sink
            self.agent.event_sink = original_sink

    def _convert_result(
        self,
        result: AgentResult,
        run_context: RunContext,
    ) -> NodeResult:
        """将 AgentResult 转换为 NodeResult。"""
        if result.stop_reason == "completed":
            return NodeResult(
                value=result.content,
                run_id=result.run_id,
            )
        else:
            return NodeResult(
                value=None,
                run_id=result.run_id,
                error_code=f"agent_{result.stop_reason}",
                error=f"Agent stopped with: {result.stop_reason}",
            )


@dataclass
class AgentNode:
    """同步 Agent 工作流节点适配器。

    将同步 Agent 接入工作流，通过 asyncio.to_thread 执行。
    """

    agent: Agent

    async def run(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
        emitter: RunEventEmitter,
    ) -> NodeResult:
        """执行同步 Agent。

        Args:
            value: 输入值（必须是字符串）
            run_context: 运行上下文
            emitter: 事件发射器

        Returns:
            NodeResult: 节点结果
        """
        # 验证输入是字符串
        if not isinstance(value, str):
            return NodeResult(
                value=None,
                run_id=run_context.run_id,
                error_code="invalid_node_input",
                error="AgentNode requires string input",
            )

        # 临时设置 event_sink
        original_sink = self.agent.event_sink
        self.agent.event_sink = emitter._sink  # type: ignore[assignment]

        try:
            # 通过 asyncio.to_thread 执行同步 Agent
            result = await asyncio.to_thread(self.agent.run, value)

            # 转换结果
            return self._convert_result(result, run_context)
        finally:
            # 恢复原始 sink
            self.agent.event_sink = original_sink

    def _convert_result(
        self,
        result: AgentResult,
        run_context: RunContext,
    ) -> NodeResult:
        """将 AgentResult 转换为 NodeResult。"""
        if result.stop_reason == "completed":
            return NodeResult(
                value=result.content,
                run_id=result.run_id,
            )
        else:
            return NodeResult(
                value=None,
                run_id=result.run_id,
                error_code=f"agent_{result.stop_reason}",
                error=f"Agent stopped with: {result.stop_reason}",
            )


@dataclass
class DebateNode:
    """Debate 工作流节点适配器。

    将 Debate 接入工作流，字符串输入映射到问题。
    """

    debate: Debate

    async def run(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
        emitter: RunEventEmitter,
    ) -> NodeResult:
        """执行 Debate。

        Args:
            value: 输入值（必须是字符串）
            run_context: 运行上下文
            emitter: 事件发射器

        Returns:
            NodeResult: 节点结果
        """
        # 验证输入是字符串
        if not isinstance(value, str):
            return NodeResult(
                value=None,
                run_id=run_context.run_id,
                error_code="invalid_node_input",
                error="DebateNode requires string input",
            )

        # 临时设置 event_sink
        original_sink = self.debate.event_sink
        self.debate.event_sink = emitter._sink  # type: ignore[assignment]

        try:
            # 执行 Debate（同步）
            result = await asyncio.to_thread(self.debate.run, value)

            # 转换结果
            return self._convert_result(result, run_context)
        finally:
            # 恢复原始 sink
            self.debate.event_sink = original_sink

    def _convert_result(
        self,
        result: DebateResult,
        run_context: RunContext,
    ) -> NodeResult:
        """将 DebateResult 转换为 NodeResult。"""
        if result.stop_reason == "completed":
            return NodeResult(
                value=result.verdict,
                run_id=result.run_id,
            )
        else:
            return NodeResult(
                value=None,
                run_id=result.run_id,
                error_code=f"debate_{result.stop_reason}",
                error=f"Debate stopped with: {result.stop_reason}",
            )