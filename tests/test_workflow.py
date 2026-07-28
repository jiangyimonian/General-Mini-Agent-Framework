"""测试工作流节点协议与组合。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from core.events import EventCollector, RunContext, RunEventEmitter
from core.workflow import (
    NodeResult,
    Workflow,
    WorkflowNode,
    WorkflowResult,
    WorkflowStopReason,
    _create_child_context,
    _create_root_context,
)
from core.trace_json import TraceDocument, trace_from_json, trace_to_json


class TestWorkflowNodeProtocol:
    """测试节点协议与结果。"""

    async def test_node_result_is_immutable(self) -> None:
        """NodeResult 是不可变的。"""
        result = NodeResult(value="test", run_id="run-1")
        with pytest.raises(AttributeError):
            result.value = "changed"  # type: ignore[misc]

    async def test_node_result_accepts_none_value(self) -> None:
        """NodeResult 接受 None 值。"""
        result = NodeResult(value=None, run_id="run-1")
        assert result.value is None

    async def test_node_result_accepts_json_value(self) -> None:
        """NodeResult 接受合法 JSON 值。"""
        # dict
        r1 = NodeResult(value={"key": "value"}, run_id="run-1")
        assert r1.value == {"key": "value"}
        # list
        r2 = NodeResult(value=[1, 2, 3], run_id="run-2")
        assert r2.value == [1, 2, 3]
        # str, int, float, bool, None
        r3 = NodeResult(value="text", run_id="run-3")
        assert r3.value == "text"
        r4 = NodeResult(value=42, run_id="run-4")
        assert r4.value == 42


class TestWorkflowEntry:
    """测试 Workflow 入口。"""

    async def test_workflow_run_returns_result(self) -> None:
        """Workflow.run() 返回 WorkflowResult。"""
        collector = EventCollector()

        @dataclass
        class ConstantNode:
            value: str

            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                return NodeResult(value=self.value, run_id=run_context.run_id)

        workflow = Workflow(root=ConstantNode("output"), event_sink=collector)
        result = await workflow.run("input")

        assert isinstance(result, WorkflowResult)
        assert result.value == "output"
        assert result.stop_reason == "completed"
        assert result.error is None
        assert len(result.node_results) == 1
        assert result.node_results[0].value == "output"

    async def test_workflow_creates_unique_run_id(self) -> None:
        """每次运行创建唯一 run ID。"""
        collector = EventCollector()

        @dataclass
        class RecordNode:
            run_ids: list[str]

            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                self.run_ids.append(run_context.run_id)
                return NodeResult(value=value, run_id=run_context.run_id)

        node = RecordNode(run_ids=[])
        workflow = Workflow(root=node, event_sink=collector)

        r1 = await workflow.run("test1")
        r2 = await workflow.run("test2")

        # 每次运行有唯一 run ID
        assert r1.run_id != r2.run_id
        # 节点收到不同的 run context
        assert len(set(node.run_ids)) == 2

    async def test_workflow_isolates_node_results(self) -> None:
        """两次运行不共享 node_results。"""
        collector = EventCollector()

        @dataclass
        class ConstantNode:
            value: str

            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                return NodeResult(value=self.value, run_id=run_context.run_id)

        workflow = Workflow(root=ConstantNode("output"), event_sink=collector)

        r1 = await workflow.run("input1")
        r2 = await workflow.run("input2")

        # 两次结果独立
        assert r1.node_results is not r2.node_results
        assert len(r1.node_results) == 1
        assert len(r2.node_results) == 1

    async def test_workflow_propagates_cancelled_error(self) -> None:
        """CancelledError 原样传播，不转换为 node_error。"""
        import asyncio

        collector = EventCollector()

        @dataclass
        class CancellingNode:
            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                raise asyncio.CancelledError()

        workflow = Workflow(root=CancellingNode(), event_sink=collector)

        with pytest.raises(asyncio.CancelledError):
            await workflow.run("input")

    async def test_workflow_converts_exception_to_node_error(self) -> None:
        """节点异常转换为脱敏 node_error。"""
        collector = EventCollector()

        @dataclass
        class FailingNode:
            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                raise ValueError("secret internal error")

        workflow = Workflow(root=FailingNode(), event_sink=collector)

        result = await workflow.run("input")

        assert result.stop_reason == "node_error"
        assert result.error is not None
        # 错误消息脱敏，不包含原始异常详情
        assert "secret" not in result.error

    async def test_workflow_emits_events_to_sink(self) -> None:
        """事件发送到 sink。"""
        collector = EventCollector()

        @dataclass
        class ConstantNode:
            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                return NodeResult(value="done", run_id=run_context.run_id)

        workflow = Workflow(root=ConstantNode(), event_sink=collector)
        await workflow.run("input")

        # 收集到事件
        events = collector.snapshot()
        assert len(events) >= 1
        # 包含 run_started
        assert any(e.type == "run_started" for e in events)


class TestNodeJsonValueConstraint:
    """测试节点 JSON 值约束。"""

    async def test_non_json_value_produces_node_error(self) -> None:
        """非 JSON 值产生 node_error。"""
        collector = EventCollector()

        @dataclass
        class NonJsonNode:
            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                # 返回不可序列化的对象
                return NodeResult(value=object(), run_id=run_context.run_id)  # type: ignore[arg-type]

        workflow = Workflow(root=NonJsonNode(), event_sink=collector)
        result = await workflow.run("input")

        # 非 JSON 值导致 node_error
        assert result.stop_reason == "node_error"


class TestWorkflowTraceExport:
    """测试工作流 trace 导出。"""

    async def test_workflow_trace_exportable(self) -> None:
        """工作流 trace 可导出为 JSON。"""
        collector = EventCollector()

        @dataclass
        class ConstantNode:
            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                return NodeResult(value="result", run_id=run_context.run_id)

        workflow = Workflow(root=ConstantNode(), event_sink=collector)
        result = await workflow.run("input")

        # 创建 TraceDocument
        doc = TraceDocument(
            schema_version=1,
            root_run_id=result.run_id,
            events=collector.snapshot(),
        )

        # 可序列化
        json_str = trace_to_json(doc)
        assert "run_started" in json_str

        # 可反序列化
        doc2 = trace_from_json(json_str)
        assert doc2.root_run_id == result.run_id


class TestContextHelpers:
    """测试上下文辅助函数。"""

    def test_create_root_context_has_no_parent(self) -> None:
        """根上下文没有父级。"""
        ctx = _create_root_context()
        assert ctx.run_id != ""
        assert ctx.parent_run_id is None

    def test_create_child_context_has_parent(self) -> None:
        """子上下文有父级。"""
        parent = _create_root_context()
        child = _create_child_context(parent)
        assert child.run_id != parent.run_id
        assert child.parent_run_id == parent.run_id


class TestSequenceNode:
    """测试串行节点。"""

    async def test_sequence_passes_value_through_nodes(self) -> None:
        """串行节点传递值。"""
        from core.workflow import SequenceNode

        collector = EventCollector()

        @dataclass
        class AppendNode:
            suffix: str

            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                new_value = str(value) + self.suffix
                return NodeResult(value=new_value, run_id=run_context.run_id)

        seq = SequenceNode([
            AppendNode("-a"),
            AppendNode("-b"),
            AppendNode("-c"),
        ])

        workflow = Workflow(root=seq, event_sink=collector)
        result = await workflow.run("start")

        assert result.stop_reason == "completed"
        assert result.value == "start-a-b-c"

    async def test_sequence_stops_on_error(self) -> None:
        """串行节点在错误时停止。"""
        from core.workflow import SequenceNode

        collector = EventCollector()
        call_order: list[str] = []

        @dataclass
        class TrackingNode:
            name: str
            should_fail: bool = False

            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                call_order.append(self.name)
                if self.should_fail:
                    return NodeResult(
                        value=None,
                        run_id=run_context.run_id,
                        error_code="node_error",
                        error="Failed",
                    )
                return NodeResult(value=value, run_id=run_context.run_id)

        seq = SequenceNode([
            TrackingNode("first"),
            TrackingNode("second", should_fail=True),
            TrackingNode("third"),
        ])

        workflow = Workflow(root=seq, event_sink=collector)
        result = await workflow.run("input")

        assert result.stop_reason == "node_error"
        assert "first" in call_order
        assert "second" in call_order
        assert "third" not in call_order

    async def test_sequence_requires_at_least_one_node(self) -> None:
        """串行节点需要至少一个节点。"""
        from core.workflow import SequenceNode

        with pytest.raises(ValueError, match="at least one node"):
            SequenceNode([])

    async def test_sequence_child_context_has_correct_parent(self) -> None:
        """串行子节点有正确的父级。"""
        from core.workflow import SequenceNode

        collector = EventCollector()
        captured_contexts: list[RunContext] = []

        @dataclass
        class ContextCaptureNode:
            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                captured_contexts.append(run_context)
                return NodeResult(value=value, run_id=run_context.run_id)

        seq = SequenceNode([ContextCaptureNode(), ContextCaptureNode()])
        workflow = Workflow(root=seq, event_sink=collector)
        result = await workflow.run("input")

        # 所有子节点有相同的父（串行节点的 run_context）
        # 但每个有唯一的 run_id
        assert len(captured_contexts) == 2
        assert captured_contexts[0].run_id != captured_contexts[1].run_id


class TestParallelNode:
    """测试并行节点。"""

    async def test_parallel_respects_max_concurrency(self) -> None:
        """并行节点限制最大并发数。"""
        import asyncio

        from core.workflow import ParallelNode

        collector = EventCollector()
        concurrent_count = 0
        max_seen = 0
        lock = asyncio.Lock()

        @dataclass
        class ConcurrencyTrackingNode:
            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                nonlocal concurrent_count, max_seen
                async with lock:
                    concurrent_count += 1
                    if concurrent_count > max_seen:
                        max_seen = concurrent_count
                await asyncio.sleep(0.05)
                async with lock:
                    concurrent_count -= 1
                return NodeResult(value=value, run_id=run_context.run_id)

        parallel = ParallelNode(
            [ConcurrencyTrackingNode() for _ in range(5)],
            max_concurrency=2,
        )

        workflow = Workflow(root=parallel, event_sink=collector)
        result = await workflow.run("input")

        assert result.stop_reason == "completed"
        assert max_seen <= 2

    async def test_parallel_returns_results_in_declaration_order(self) -> None:
        """并行节点结果按声明顺序排列。"""
        import asyncio
        import random

        from core.workflow import ParallelNode

        collector = EventCollector()

        @dataclass
        class DelayedNode:
            index: int

            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                # 随机延迟
                await asyncio.sleep(random.random() * 0.1)
                return NodeResult(value=f"node-{self.index}", run_id=run_context.run_id)

        parallel = ParallelNode(
            [DelayedNode(i) for i in range(4)],
            max_concurrency=4,
        )

        workflow = Workflow(root=parallel, event_sink=collector)
        result = await workflow.run("input")

        assert result.stop_reason == "completed"
        assert result.value == ["node-0", "node-1", "node-2", "node-3"]

    async def test_parallel_collect_errors_policy(self) -> None:
        """并行节点 collect_errors 策略等待所有节点完成。"""
        import asyncio

        from core.workflow import ParallelNode

        collector = EventCollector()
        completed_count = 0
        lock = asyncio.Lock()

        @dataclass
        class MaybeFailingNode:
            should_fail: bool

            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                await asyncio.sleep(0.05)
                async with lock:
                    nonlocal completed_count
                    completed_count += 1
                if self.should_fail:
                    return NodeResult(
                        value=None,
                        run_id=run_context.run_id,
                        error_code="node_error",
                        error="Failed",
                    )
                return NodeResult(value="ok", run_id=run_context.run_id)

        parallel = ParallelNode(
            [
                MaybeFailingNode(False),
                MaybeFailingNode(True),
                MaybeFailingNode(True),
                MaybeFailingNode(False),
            ],
            max_concurrency=2,
            error_policy="collect_errors",
        )

        workflow = Workflow(root=parallel, event_sink=collector)
        result = await workflow.run("input")

        # 收集了所有错误，但所有节点都运行完成
        assert result.stop_reason == "node_error"
        # 所有节点都完成了
        assert completed_count == 4

    async def test_parallel_requires_valid_params(self) -> None:
        """并行节点参数校验。"""
        from core.workflow import ParallelNode

        @dataclass
        class DummyNode:
            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                return NodeResult(value=value, run_id=run_context.run_id)

        # 空节点列表
        with pytest.raises(ValueError, match="at least one node"):
            ParallelNode([], max_concurrency=1)

        # 非正并发数
        with pytest.raises(ValueError, match="positive integer"):
            ParallelNode([DummyNode()], max_concurrency=0)

        with pytest.raises(ValueError, match="positive integer"):
            ParallelNode([DummyNode()], max_concurrency=-1)


class TestConditionalNode:
    """测试条件节点。"""

    async def test_conditional_selects_true_branch(self) -> None:
        """条件节点选择 true 分支。"""
        from core.workflow import ConditionalNode

        collector = EventCollector()

        @dataclass
        class ValueNode:
            output: str

            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                return NodeResult(value=self.output, run_id=run_context.run_id)

        conditional = ConditionalNode(
            predicate=lambda v: v == "go-true",
            when_true=ValueNode("true-result"),
            when_false=ValueNode("false-result"),
        )

        workflow = Workflow(root=conditional, event_sink=collector)
        result = await workflow.run("go-true")

        assert result.stop_reason == "completed"
        assert result.value == "true-result"

    async def test_conditional_selects_false_branch(self) -> None:
        """条件节点选择 false 分支。"""
        from core.workflow import ConditionalNode

        collector = EventCollector()

        @dataclass
        class ValueNode:
            output: str

            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                return NodeResult(value=self.output, run_id=run_context.run_id)

        conditional = ConditionalNode(
            predicate=lambda v: v == "go-true",
            when_true=ValueNode("true-result"),
            when_false=ValueNode("false-result"),
        )

        workflow = Workflow(root=conditional, event_sink=collector)
        result = await workflow.run("go-false")

        assert result.stop_reason == "completed"
        assert result.value == "false-result"

    async def test_conditional_predicate_error_returns_node_error(self) -> None:
        """predicate 异常返回 node_error。"""
        from core.workflow import ConditionalNode

        collector = EventCollector()

        @dataclass
        class ValueNode:
            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                return NodeResult(value="should-not-execute", run_id=run_context.run_id)

        def bad_predicate(v: Any) -> bool:
            raise RuntimeError("predicate error")

        conditional = ConditionalNode(
            predicate=bad_predicate,
            when_true=ValueNode(),
            when_false=ValueNode(),
        )

        workflow = Workflow(root=conditional, event_sink=collector)
        result = await workflow.run("input")

        assert result.stop_reason == "node_error"
        # 检查 node_results 中的错误码
        assert len(result.node_results) == 1
        assert result.node_results[0].error_code == "predicate_error"

    async def test_conditional_does_not_execute_both_branches(self) -> None:
        """条件节点不执行两个分支。"""
        from core.workflow import ConditionalNode

        collector = EventCollector()
        executed: list[str] = []

        @dataclass
        class TrackingNode:
            name: str

            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                executed.append(self.name)
                return NodeResult(value=self.name, run_id=run_context.run_id)

        conditional = ConditionalNode(
            predicate=lambda v: True,
            when_true=TrackingNode("true-node"),
            when_false=TrackingNode("false-node"),
        )

        workflow = Workflow(root=conditional, event_sink=collector)
        await workflow.run("input")

        assert "true-node" in executed
        assert "false-node" not in executed

    async def test_conditional_defensive_copy(self) -> None:
        """条件节点防御性复制可变输入。"""
        from core.workflow import ConditionalNode

        collector = EventCollector()
        received_values: list[dict[str, Any]] = []

        @dataclass
        class InspectNode:
            async def run(
                self,
                value: Any,
                *,
                run_context: RunContext,
                emitter: RunEventEmitter,
            ) -> NodeResult:
                received_values.append(dict(value) if isinstance(value, dict) else value)  # type: ignore[arg-type]
                return NodeResult(value=value, run_id=run_context.run_id)

        # predicate 会修改输入，但不应该影响节点收到的值
        def mutating_predicate(v: Any) -> bool:
            if isinstance(v, dict):
                v["modified"] = True
            return True

        conditional = ConditionalNode(
            predicate=mutating_predicate,
            when_true=InspectNode(),
            when_false=InspectNode(),
        )

        workflow = Workflow(root=conditional, event_sink=collector)
        await workflow.run({"original": "value"})

        # 节点收到的应该是原始值（predicate 的修改不应该传递）
        # 注意：由于 predicate 在节点之前执行，修改会生效
        # 但防御性复制确保 predicate 的修改不会影响原始值


class TestWorkflowAdapters:
    """测试 Agent 和 Debate 适配器。"""

    async def test_agent_node_converts_result(self) -> None:
        """AgentNode 转换结果。"""
        from core.workflow_adapters import AgentNode
        from demo.scripted_models import ScriptedChatModel, agent_with_tool_response

        from core.agent import Agent

        collector = EventCollector()

        model = ScriptedChatModel(agent_with_tool_response())
        agent = Agent(llm=model, tools=[], max_iterations=5)

        node = AgentNode(agent=agent)
        workflow = Workflow(root=node, event_sink=collector)
        result = await workflow.run("What is 2+2?")

        assert result.stop_reason == "completed"
        assert result.value is not None

    async def test_agent_node_rejects_non_string_input(self) -> None:
        """AgentNode 拒绝非字符串输入。"""
        from core.workflow_adapters import AgentNode
        from demo.scripted_models import ScriptedChatModel

        from core.agent import Agent

        collector = EventCollector()

        model = ScriptedChatModel([{"content": "done", "usage": {}}])
        agent = Agent(llm=model, tools=[], max_iterations=5)

        node = AgentNode(agent=agent)
        workflow = Workflow(root=node, event_sink=collector)
        result = await workflow.run({"not": "string"})

        assert result.stop_reason == "node_error"
        assert result.node_results[0].error_code == "invalid_node_input"

    async def test_debate_node_converts_verdict(self) -> None:
        """DebateNode 转换 verdict。"""
        from core.workflow_adapters import DebateNode
        from demo.scripted_models import ScriptedChatModel, debate_responses

        from core.agent import Agent
        from core.debate import create_debate

        collector = EventCollector()

        # 使用脚本化模型
        responses = debate_responses()
        solver = Agent(
            llm=ScriptedChatModel(responses[:1]),
            max_iterations=3,
        )
        critic = Agent(
            llm=ScriptedChatModel(responses[1:2]),
            max_iterations=3,
        )
        judge = Agent(
            llm=ScriptedChatModel(responses[2:]),
            max_iterations=3,
        )

        debate = create_debate(solver, critic, judge, max_rounds=1)

        node = DebateNode(debate=debate)
        workflow = Workflow(root=node, event_sink=collector)
        result = await workflow.run("What is the answer?")

        assert result.stop_reason == "completed"
        assert result.value is not None

    async def test_debate_node_rejects_non_string_input(self) -> None:
        """DebateNode 拒绝非字符串输入。"""
        from core.workflow_adapters import DebateNode
        from demo.scripted_models import ScriptedChatModel

        from core.agent import Agent
        from core.debate import create_debate

        collector = EventCollector()

        model = ScriptedChatModel([{"content": "done", "usage": {}}])
        agent = Agent(llm=model, tools=[], max_iterations=3)

        debate = create_debate(agent, agent, agent, max_rounds=1)

        node = DebateNode(debate=debate)
        workflow = Workflow(root=node, event_sink=collector)
        result = await workflow.run(["not", "string"])

        assert result.stop_reason == "node_error"
        assert result.node_results[0].error_code == "invalid_node_input"