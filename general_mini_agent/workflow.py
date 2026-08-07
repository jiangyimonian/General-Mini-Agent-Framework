
"""可组合、可取消、可观察的工作流节点。

提供串行、有限并行、条件路由和循环节点，支持统一事件追踪。
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from .events import EventSink, RunContext, RunEventEmitter

# ─── 类型定义 ────────────────────────────────────────────────────────

JSONValue = None | bool | int | float | str | dict[str, Any] | list[Any]

WorkflowStopReason = Literal["completed", "node_error"]

WorkflowPredicate = Callable[[JSONValue], bool]

ParallelErrorPolicy = Literal["fail_fast", "collect_errors"]


# ─── 结果类型 ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NodeResult:
    """节点执行结果。"""

    value: JSONValue | None
    run_id: str
    error_code: str | None = None
    error: str | None = None


@dataclass
class WorkflowResult:
    """工作流执行结果。"""

    value: JSONValue | None
    run_id: str
    node_results: list[NodeResult] = field(default_factory=list)
    stop_reason: WorkflowStopReason = "completed"
    error: str | None = None


# ─── 节点协议 ────────────────────────────────────────────────────────


class WorkflowNode(Protocol):
    """工作流节点协议。"""

    async def run(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
        emitter: RunEventEmitter,
    ) -> NodeResult:
        """执行节点。

        Args:
            value: 输入值（JSONValue）
            run_context: 运行上下文，包含 run_id 和父子关系
            emitter: 事件发射器

        Returns:
            NodeResult: 节点结果
        """
        ...


# ─── 辅助函数 ────────────────────────────────────────────────────────


def _create_run_id() -> str:
    """生成唯一 run ID。"""
    return str(uuid.uuid4())


def _create_root_context() -> RunContext:
    """创建根运行上下文。"""
    return RunContext(
        run_id=_create_run_id(),
        parent_run_id=None,
        started_at=datetime.now(UTC),
    )


def _create_child_context(parent: RunContext) -> RunContext:
    """创建子运行上下文。"""
    return RunContext(
        run_id=_create_run_id(),
        parent_run_id=parent.run_id,
        started_at=datetime.now(UTC),
    )


# ─── 工作流入口 ────────────────────────────────────────────────────────


class Workflow:
    """工作流入口，持有根节点和可选事件 sink。"""

    def __init__(
        self,
        root: WorkflowNode,
        *,
        event_sink: EventSink | None = None,
    ) -> None:
        """初始化工作流。

        Args:
            root: 根节点
            event_sink: 可选的事件 sink
        """
        self._root = root
        self._event_sink = event_sink

    async def run(self, value: JSONValue) -> WorkflowResult:
        """执行工作流。

        每次调用创建新的 root emitter 和结果列表。
        节点异常转换为脱敏 node_error，但 CancelledError 原样传播。

        Args:
            value: 输入值（JSONValue）

        Returns:
            WorkflowResult: 工作流结果
        """
        # 创建 root context 和 emitter
        root_context = _create_root_context()
        emitter = RunEventEmitter(
            run_id=root_context.run_id,
            parent_run_id=None,
            sink=self._event_sink,
        )

        # 发出 run_started
        emitter.emit("run_started", {"input_type": type(value).__name__})

        node_results: list[NodeResult] = []
        stop_reason: WorkflowStopReason = "completed"
        error: str | None = None

        try:
            # 执行根节点
            result = await self._run_node(
                value, run_context=root_context, emitter=emitter
            )
            node_results.append(result)

            if result.error_code is not None:
                stop_reason = "node_error"
                error = result.error

        except asyncio.CancelledError:
            # CancelledError 原样传播
            emitter.emit("run_finished", {"stop_reason": "cancelled"})
            raise

        except Exception:
            # 其他异常转换为脱敏 node_error
            stop_reason = "node_error"
            error = "Node execution failed"
            node_results.append(
                NodeResult(
                    value=None,
                    run_id=root_context.run_id,
                    error_code="node_error",
                    error=error,
                )
            )

        # 发出 run_finished
        emitter.emit(
            "run_finished",
            {
                "stop_reason": stop_reason,
                "node_count": len(node_results),
            },
        )

        return WorkflowResult(
            value=node_results[-1].value if node_results else None,
            run_id=root_context.run_id,
            node_results=node_results,
            stop_reason=stop_reason,
            error=error,
        )

    async def _run_node(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
        emitter: RunEventEmitter,
    ) -> NodeResult:
        """执行单个节点，验证输入输出。"""
        # 验证输入是 JSONValue
        if not self._is_json_value(value):
            return NodeResult(
                value=None,
                run_id=run_context.run_id,
                error_code="invalid_node_input",
                error="Node input must be a JSON value",
            )

        # 执行节点
        result = await self._root.run(
            value, run_context=run_context, emitter=emitter
        )

        # 验证输出是 JSONValue
        if not self._is_json_value(result.value):
            return NodeResult(
                value=None,
                run_id=run_context.run_id,
                error_code="invalid_node_output",
                error="Node output must be a JSON value",
            )

        return result

    @staticmethod
    def _is_json_value(value: Any) -> bool:
        """检查值是否为合法 JSON 值。"""
        if value is None:
            return True
        if isinstance(value, bool):
            return True
        if isinstance(value, int):
            return True
        if isinstance(value, float):
            # 排除 NaN 和 Infinity
            import math

            if math.isnan(value) or math.isinf(value):
                return False
            return True
        if isinstance(value, str):
            return True
        if isinstance(value, dict):
            return all(
                isinstance(k, str) and Workflow._is_json_value(v)
                for k, v in value.items()
            )
        if isinstance(value, list):
            return all(Workflow._is_json_value(item) for item in value)
        return False


# ─── 串行节点 ────────────────────────────────────────────────────────


class SequenceNode:
    """串行节点：依次执行子节点，传递前一节点输出。"""

    def __init__(self, nodes: Sequence[WorkflowNode]) -> None:
        """初始化串行节点。

        Args:
            nodes: 子节点序列

        Raises:
            ValueError: 节点序列为空
        """
        if not nodes:
            raise ValueError("SequenceNode requires at least one node")
        self._nodes = list(nodes)

    async def run(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
        emitter: RunEventEmitter,
    ) -> NodeResult:
        """执行串行节点。

        只在节点 error_code is None 时继续。
        最终 value 等于最后成功节点结果。
        """
        emitter.emit("sequence_started", {"node_count": len(self._nodes)})

        current_value = value
        last_result: NodeResult | None = None

        for i, node in enumerate(self._nodes):
            # 创建子运行上下文
            child_context = _create_child_context(run_context)
            child_emitter = emitter.child()

            emitter.emit(
                "sequence_node_started",
                {"index": i, "child_run_id": child_context.run_id},
            )

            # 执行子节点
            result = await node.run(
                current_value, run_context=child_context, emitter=child_emitter
            )

            emitter.emit(
                "sequence_node_finished",
                {
                    "index": i,
                    "child_run_id": child_context.run_id,
                    "error_code": result.error_code,
                },
            )

            # 检查错误
            if result.error_code is not None:
                emitter.emit(
                    "sequence_finished",
                    {"stop_reason": "node_error", "failed_at": i},
                )
                return NodeResult(
                    value=None,
                    run_id=run_context.run_id,
                    error_code="sequence_failed",
                    error=f"Sequence failed at node {i}: {result.error}",
                )

            # 传递到下一节点
            current_value = result.value
            last_result = result

        emitter.emit("sequence_finished", {"stop_reason": "completed"})

        # 返回最后成功节点的结果
        if last_result is None:
            return NodeResult(
                value=None,
                run_id=run_context.run_id,
            )

        return NodeResult(
            value=last_result.value,
            run_id=run_context.run_id,
        )


# ─── 并行节点 ────────────────────────────────────────────────────────


class ParallelNode:
    """并行节点：并发执行子节点，结果按声明顺序排列。"""

    def __init__(
        self,
        nodes: Sequence[WorkflowNode],
        *,
        max_concurrency: int,
        error_policy: ParallelErrorPolicy = "fail_fast",
    ) -> None:
        """初始化并行节点。

        Args:
            nodes: 子节点序列
            max_concurrency: 最大并发数（正整数）
            error_policy: 错误策略

        Raises:
            ValueError: 节点序列为空或并发数非正
        """
        if not nodes:
            raise ValueError("ParallelNode requires at least one node")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")
        self._nodes = list(nodes)
        self._max_concurrency = max_concurrency
        self._error_policy = error_policy

    async def run(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
        emitter: RunEventEmitter,
    ) -> NodeResult:
        """执行并行节点。

        结果按声明顺序排列。
        fail_fast: 首个错误后取消未完成节点
        collect_errors: 等待全部节点，保留每个错误
        """
        emitter.emit(
            "parallel_started",
            {"node_count": len(self._nodes), "max_concurrency": self._max_concurrency},
        )

        semaphore = asyncio.Semaphore(self._max_concurrency)
        results: dict[int, NodeResult] = {}

        async def run_single_node(
            index: int,
            node: WorkflowNode,
        ) -> tuple[int, NodeResult]:
            """执行单个节点，记录索引。"""
            child_context = _create_child_context(run_context)
            child_emitter = emitter.child()

            async with semaphore:
                emitter.emit(
                    "parallel_node_started",
                    {"index": index, "child_run_id": child_context.run_id},
                )

                result = await node.run(
                    value, run_context=child_context, emitter=child_emitter
                )

                emitter.emit(
                    "parallel_node_finished",
                    {
                        "index": index,
                        "child_run_id": child_context.run_id,
                        "error_code": result.error_code,
                    },
                )

            return index, result

        tasks: list[asyncio.Task[tuple[int, NodeResult]]] = []

        try:
            async with asyncio.TaskGroup() as tg:
                for i, node in enumerate(self._nodes):
                    task = tg.create_task(run_single_node(i, node))
                    tasks.append(task)
        except asyncio.CancelledError:
            emitter.emit(
                "parallel_finished",
                {"stop_reason": "cancelled"},
            )
            raise
        except ExceptionGroup:
            # 收集异常组中的错误
            pass

        # 收集结果
        for task in tasks:
            if task.done():
                try:
                    idx, r = task.result()
                    results[idx] = r
                except Exception:
                    pass

        # 填充未完成的
        for i in range(len(self._nodes)):
            if i not in results:
                results[i] = NodeResult(
                    value=None,
                    run_id=run_context.run_id,
                    error_code="node_error",
                    error="Node failed",
                )

        # 按顺序排列
        ordered_results = [results[i] for i in range(len(self._nodes))]

        # 检查是否有错误
        errors = [r for r in ordered_results if r.error_code is not None]
        if errors:
            emitter.emit(
                "parallel_finished",
                {"stop_reason": "node_error", "error_count": len(errors)},
            )
            return NodeResult(
                value=None,
                run_id=run_context.run_id,
                error_code="parallel_failed",
                error=f"{len(errors)} parallel nodes failed",
            )

        # 成功：返回结果列表
        values = [r.value for r in ordered_results]

        emitter.emit(
            "parallel_finished",
            {"stop_reason": "completed"},
        )

        return NodeResult(
            value=values,
            run_id=run_context.run_id,
        )


# ─── 条件节点 ────────────────────────────────────────────────────────


class ConditionalNode:
    """条件节点：根据 predicate 选择分支。"""

    def __init__(
        self,
        predicate: WorkflowPredicate,
        when_true: WorkflowNode,
        when_false: WorkflowNode,
    ) -> None:
        """初始化条件节点。

        Args:
            predicate: 条件判断函数（同步，无重试）
            when_true: 条件为真时执行的节点
            when_false: 条件为假时执行的节点
        """
        self._predicate = predicate
        self._when_true = when_true
        self._when_false = when_false

    async def run(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
        emitter: RunEventEmitter,
    ) -> NodeResult:
        """执行条件节点。

        predicate 异常时返回 node_error，不执行任何分支。
        """
        emitter.emit("conditional_started", {})

        # 执行 predicate
        try:
            # 防御性复制输入（对可变类型）
            if isinstance(value, dict):
                input_copy = dict(value)
            elif isinstance(value, list):
                input_copy = list(value)
            else:
                input_copy = value

            condition_result = self._predicate(input_copy)
            # 必须是真实 bool
            if not isinstance(condition_result, bool):
                condition_result = bool(condition_result)
        except Exception as e:
            emitter.emit(
                "conditional_finished",
                {"stop_reason": "predicate_error"},
            )
            return NodeResult(
                value=None,
                run_id=run_context.run_id,
                error_code="predicate_error",
                error=f"Predicate raised exception: {type(e).__name__}",
            )

        # 选择分支
        branch = "true" if condition_result else "false"
        selected_node = self._when_true if condition_result else self._when_false

        emitter.emit(
            "conditional_branch_selected",
            {"branch": branch},
        )

        # 创建子上下文
        child_context = _create_child_context(run_context)
        child_emitter = emitter.child()

        # 执行选中分支
        result = await selected_node.run(
            value, run_context=child_context, emitter=child_emitter
        )

        emitter.emit(
            "conditional_finished",
            {"stop_reason": "completed", "branch": branch},
        )

        return NodeResult(
            value=result.value,
            run_id=run_context.run_id,
            error_code=result.error_code,
            error=result.error,
        )


# ─── 循环节点 ────────────────────────────────────────────────────────


class LoopNode:
    """循环节点：重复执行 body 直到 should_stop 返回 True。

    每次迭代传递前一次的输出作为下一次的输入。
    """

    def __init__(
        self,
        body: WorkflowNode,
        should_stop: WorkflowPredicate,
        max_iterations: int = 100,
    ) -> None:
        """初始化循环节点。

        Args:
            body: 循环体节点
            should_stop: 判断是否停止的谓词（接收当前值，返回 bool）
            max_iterations: 最大迭代次数（防止无限循环）

        Raises:
            ValueError: max_iterations 不是正整数
        """
        if max_iterations < 1:
            raise ValueError("max_iterations must be a positive integer")
        self._body = body
        self._should_stop = should_stop
        self._max_iterations = max_iterations

    async def run(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
        emitter: RunEventEmitter,
    ) -> NodeResult:
        """执行循环节点。

        循环直到 should_stop 返回 True 或达到 max_iterations。
        """
        emitter.emit(
            "loop_started",
            {"max_iterations": self._max_iterations},
        )

        current_value = value
        iteration_count = 0

        while True:
            iteration_count += 1

            # 检查是否达到最大迭代次数
            if iteration_count > self._max_iterations:
                emitter.emit(
                    "loop_finished",
                    {
                        "stop_reason": "max_iterations",
                        "iterations": iteration_count - 1,
                    },
                )
                return NodeResult(
                    value=current_value,
                    run_id=run_context.run_id,
                    error_code="max_iterations",
                    error=f"Reached max iterations ({self._max_iterations})",
                )

            # 执行 should_stop 判断
            try:
                # 防御性复制输入
                if isinstance(current_value, dict):
                    input_copy = dict(current_value)
                elif isinstance(current_value, list):
                    input_copy = list(current_value)
                else:
                    input_copy = current_value

                should_stop_result = self._should_stop(input_copy)
                if not isinstance(should_stop_result, bool):
                    should_stop_result = bool(should_stop_result)
            except Exception as e:
                emitter.emit(
                    "loop_finished",
                    {"stop_reason": "predicate_error", "iterations": iteration_count},
                )
                return NodeResult(
                    value=None,
                    run_id=run_context.run_id,
                    error_code="predicate_error",
                    error=f"Should_stop predicate raised exception: {type(e).__name__}",
                )

            # 检查是否停止
            if should_stop_result:
                emitter.emit(
                    "loop_finished",
                    {"stop_reason": "condition_met", "iterations": iteration_count - 1},
                )
                return NodeResult(
                    value=current_value,
                    run_id=run_context.run_id,
                )

            # 执行循环体
            emitter.emit(
                "loop_iteration_started",
                {"iteration": iteration_count},
            )

            child_context = _create_child_context(run_context)
            child_emitter = emitter.child()

            result = await self._body.run(
                current_value, run_context=child_context, emitter=child_emitter
            )

            emitter.emit(
                "loop_iteration_finished",
                {
                    "iteration": iteration_count,
                    "error_code": result.error_code,
                },
            )

            # 检查循环体是否出错
            if result.error_code is not None:
                emitter.emit(
                    "loop_finished",
                    {
                        "stop_reason": "body_error",
                        "iterations": iteration_count,
                    },
                )
                return NodeResult(
                    value=None,
                    run_id=run_context.run_id,
                    error_code="loop_body_error",
                    error=f"Loop body failed at iteration {iteration_count}: {result.error}",
                )

            # 更新当前值用于下一次迭代
            current_value = result.value

