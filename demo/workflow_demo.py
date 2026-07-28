"""离线工作流示例：并行生成 -> 条件选择 -> 输出。

运行:
    python demo/workflow_demo.py

输出:
    output/workflow.json
    output/workflow.html

不读取 .env，不访问网络。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 确保可以导入 core
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import (
    ConditionalNode,
    EventCollector,
    ParallelNode,
    SequenceNode,
    Workflow,
    export_trace_json,
    trace_to_html,
)
from core.trace_json import TraceDocument

# ─── 简单节点定义 ────────────────────────────────────────────────────────


class ConstantNode:
    """返回常量值的节点。"""

    def __init__(self, value: str):
        self._value = value

    async def run(self, value, *, run_context, emitter):
        from core import NodeResult

        return NodeResult(value=self._value, run_id=run_context.run_id)


class AppendNode:
    """追加字符串的节点。"""

    def __init__(self, suffix: str):
        self._suffix = suffix

    async def run(self, value, *, run_context, emitter):
        from core import NodeResult

        new_value = str(value) + self._suffix
        return NodeResult(value=new_value, run_id=run_context.run_id)


# ─── 主示例 ────────────────────────────────────────────────────────


async def run_workflow_demo(output_dir: Path) -> tuple[str, str]:
    """运行工作流示例，输出 JSON 和 HTML。"""
    collector = EventCollector()

    # 创建并行节点：生成两个候选
    parallel = ParallelNode(
        [
            AppendNode("-candidate-A"),
            AppendNode("-candidate-B"),
        ],
        max_concurrency=2,
    )

    # 创建条件节点：检查输入是否包含特定值
    def has_candidates(value) -> bool:
        # value 是列表，检查是否有内容
        return isinstance(value, list) and len(value) > 0

    conditional = ConditionalNode(
        predicate=has_candidates,
        when_true=ConstantNode("selected-best-candidate"),
        when_false=ConstantNode("no-candidates"),
    )

    # 创建串行节点：并行 -> 条件选择
    sequence = SequenceNode([parallel, conditional])

    # 创建工作流
    workflow = Workflow(root=sequence, event_sink=collector)

    # 运行
    result = await workflow.run("start")

    # 创建 TraceDocument
    doc = TraceDocument(
        schema_version=1,
        root_run_id=result.run_id,
        events=collector.snapshot(),
    )

    # 输出路径
    json_path = output_dir / "workflow.json"
    html_path = output_dir / "workflow.html"

    # 导出
    export_trace_json(doc, json_path)
    export_trace_json(doc, html_path.with_suffix(".json"))

    # HTML 导出
    html = trace_to_html(doc, title="Workflow Demo")
    html_path.write_text(html, encoding="utf-8")

    return str(json_path), str(html_path)


async def main(output_dir: str | Path | None = None) -> None:
    """运行所有工作流示例。"""
    output_dir = Path(output_dir or Path(__file__).parent.parent / "output")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Running workflow demo...")
    json_path, html_path = await run_workflow_demo(output_dir)
    print(f"   JSON: {json_path}")
    print(f"   HTML: {html_path}")

    print("Done. Generated workflow trace.")


if __name__ == "__main__":
    asyncio.run(main())