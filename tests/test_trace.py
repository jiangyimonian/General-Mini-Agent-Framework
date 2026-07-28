"""Regression tests for self-contained HTML trace renderers."""

from datetime import UTC, datetime

import pytest

from core.events import RunEvent
from core.trace import trace_to_html
from core.trace_json import TraceDocument


class TestTraceDocumentToHtml:
    """测试 TraceDocument 到 HTML 的渲染。"""

    def test_html_contains_run_id_and_events(self) -> None:
        """HTML 包含 run ID 和事件类型。"""
        events = (
            RunEvent(
                run_id="test-run-123",
                parent_run_id=None,
                sequence=1,
                occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                elapsed_ms=100.0,
                type="run_started",
                payload={"input": "test question"},
            ),
            RunEvent(
                run_id="test-run-123",
                parent_run_id=None,
                sequence=2,
                occurred_at=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
                elapsed_ms=1100.0,
                type="run_finished",
                payload={"stop_reason": "completed", "answer": "final answer"},
            ),
        )
        doc = TraceDocument(schema_version=1, root_run_id="test-run-123", events=events)

        html = trace_to_html(doc, title="Test Trace")

        # run ID 和事件类型出现在嵌入 JSON 中
        assert "test-run-123" in html
        assert "run_started" in html
        assert "run_finished" in html
        assert "completed" in html
        # 无外部资源
        assert "http://" not in html
        assert "https://" not in html
        assert "<script src=" not in html
        assert "<link" not in html

    def test_html_contains_elapsed_and_usage(self) -> None:
        """HTML 包含耗时和 usage 数据。"""
        events = (
            RunEvent(
                run_id="run-1",
                parent_run_id=None,
                sequence=1,
                occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                elapsed_ms=500.0,
                type="model_request_finished",
                payload={"usage": {"total_tokens": 100, "prompt_tokens": 80, "completion_tokens": 20}},
            ),
        )
        doc = TraceDocument(schema_version=1, root_run_id="run-1", events=events)

        html = trace_to_html(doc)

        assert "500.0" in html
        assert "100" in html

    def test_html_contains_role_name_for_debate(self) -> None:
        """HTML 包含角色名（Debate 场景）。"""
        events = (
            RunEvent(
                run_id="debate-run",
                parent_run_id=None,
                sequence=1,
                occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                elapsed_ms=0.0,
                type="run_started",
                payload={"input": "question"},
            ),
            RunEvent(
                run_id="solver-run",
                parent_run_id="debate-run",
                sequence=1,
                occurred_at=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
                elapsed_ms=1000.0,
                type="run_finished",
                payload={"role": "Solver", "stop_reason": "completed"},
            ),
        )
        doc = TraceDocument(schema_version=1, root_run_id="debate-run", events=events)

        html = trace_to_html(doc)

        assert "Solver" in html


class TestHtmlFiltering:
    """测试 HTML 过滤功能。"""

    def test_html_contains_filter_controls(self) -> None:
        """HTML 包含过滤控件。"""
        events = (
            RunEvent(
                run_id="run-1",
                parent_run_id=None,
                sequence=1,
                occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                elapsed_ms=0.0,
                type="run_started",
                payload={"input": "test"},
            ),
            RunEvent(
                run_id="run-1",
                parent_run_id=None,
                sequence=2,
                occurred_at=datetime(2026, 1, 1, 12, 0, 1, tzinfo=UTC),
                elapsed_ms=1000.0,
                type="run_finished",
                payload={"stop_reason": "completed"},
            ),
            RunEvent(
                run_id="run-1",
                parent_run_id=None,
                sequence=3,
                occurred_at=datetime(2026, 1, 1, 12, 0, 2, tzinfo=UTC),
                elapsed_ms=2000.0,
                type="run_finished",
                payload={"stop_reason": "error", "error": "something failed"},
            ),
        )
        doc = TraceDocument(schema_version=1, root_run_id="run-1", events=events)

        html = trace_to_html(doc)

        # 过滤控件存在
        assert 'id="filter-type"' in html
        assert 'id="filter-run"' in html
        assert 'id="filter-stop"' in html
        assert 'id="filter-error"' in html
        # JavaScript 设置 data 属性逻辑存在
        assert "data-event-type" in html
        assert "data-run-id" in html
        assert "data-stop-reason" in html
        assert "applyFilters" in html

    def test_filter_controls_have_labels(self) -> None:
        """过滤控件有 label。"""
        events = (
            RunEvent(
                run_id="run-1",
                parent_run_id=None,
                sequence=1,
                occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                elapsed_ms=0.0,
                type="run_started",
                payload={},
            ),
        )
        doc = TraceDocument(schema_version=1, root_run_id="run-1", events=events)

        html = trace_to_html(doc)

        assert "<label" in html
        assert 'for="filter-type"' in html


class TestHtmlSecurity:
    """测试 HTML 安全性。"""

    def test_xss_payload_is_escaped(self) -> None:
        """XSS payload 被正确转义。"""
        malicious = "</script><script>alert(1)</script>"
        events = (
            RunEvent(
                run_id="run-1",
                parent_run_id=None,
                sequence=1,
                occurred_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
                elapsed_ms=0.0,
                type="run_started",
                payload={"input": malicious},
            ),
        )
        doc = TraceDocument(schema_version=1, root_run_id="run-1", events=events)

        html = trace_to_html(doc)

        # 原始恶意脚本标签不应出现在 script 数据块中
        assert "</script><script>alert(1)</script>" not in html
        # 但原文应可恢复（转义后存在）
        assert "alert(1)" in html or "&lt;/script&gt;" in html


# ─── 兼容性测试（旧 API，将在后续版本移除）───


def test_render_html_preserves_stat_labels_without_literal_backslashes() -> None:
    from types import SimpleNamespace

    from core.trace import render_html

    html = render_html(
        SimpleNamespace(content="answer", iterations=1, trace=[], usage={}),
        question="question",
    )

    assert '<div class="stat-label">Prompt Tokens</div>' in html
    assert '<div class="stat-label">Completion Tokens</div>' in html
    assert "\\\n" not in html


def test_debate_to_html_preserves_stat_labels_without_literal_backslashes() -> None:
    from types import SimpleNamespace

    from core.trace import debate_to_html

    html = debate_to_html(
        SimpleNamespace(verdict="verdict", rounds=[], total_usage={}),
        question="question",
    )

    assert '<div class="stat-label">Total Tokens</div>' in html
    assert '<div class="stat-label">Completion</div>' in html
    assert "\\\n" not in html


def test_debate_to_html_serializes_typed_rounds_and_judge() -> None:
    from core.debate import DebateResult, DebateRound, DebateTurn
    from core.trace import debate_to_html

    participant = DebateTurn(role="Solver", content="proposal")
    judge = DebateTurn(role="Judge", content="final verdict")
    result = DebateResult(
        verdict="final verdict",
        rounds=[DebateRound(number=1, turns=[participant])],
        judge_turn=judge,
    )

    html = debate_to_html(result, question="question")

    assert '"number": 1' in html
    assert '"role": "Solver"' in html
    assert '"content": "proposal"' in html
    assert '"role": "Judge"' in html
    assert "final verdict" in html
