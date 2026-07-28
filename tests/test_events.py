"""测试运行上下文、事件 envelope 和 JSON trace。"""

from datetime import UTC, datetime

import pytest

from core.events import (
    EventCollector,
    RunContext,
    RunEvent,
    RunEventEmitter,
)


class TestRunContext:
    """测试 RunContext 数据类。"""

    def test_run_context_holds_run_id(self) -> None:
        """RunContext 持有 run_id。"""
        ctx = RunContext(run_id="test-run-123", parent_run_id=None, started_at=datetime.now(UTC))
        assert ctx.run_id == "test-run-123"
        assert ctx.parent_run_id is None

    def test_run_context_holds_parent_run_id(self) -> None:
        """RunContext 持有 parent_run_id。"""
        ctx = RunContext(
            run_id="child-run", parent_run_id="parent-run", started_at=datetime.now(UTC)
        )
        assert ctx.parent_run_id == "parent-run"


class TestRunEvent:
    """测试 RunEvent 数据类。"""

    def test_run_event_is_frozen(self) -> None:
        """RunEvent 是不可变的。"""
        event = RunEvent(
            run_id="test-run",
            parent_run_id=None,
            sequence=1,
            occurred_at=datetime.now(UTC),
            elapsed_ms=100.0,
            type="test_event",
            payload={"key": "value"},
        )
        with pytest.raises(AttributeError):
            event.sequence = 2  # type: ignore

    def test_run_event_holds_all_fields(self) -> None:
        """RunEvent 持有所有字段。"""
        now = datetime.now(UTC)
        event = RunEvent(
            run_id="run-1",
            parent_run_id="parent-1",
            sequence=5,
            occurred_at=now,
            elapsed_ms=1234.5,
            type="model_request",
            payload={"model": "gpt-4", "tokens": 100},
        )
        assert event.run_id == "run-1"
        assert event.parent_run_id == "parent-1"
        assert event.sequence == 5
        assert event.occurred_at == now
        assert event.elapsed_ms == 1234.5
        assert event.type == "model_request"
        assert event.payload == {"model": "gpt-4", "tokens": 100}


class TestRunEventEmitter:
    """测试 RunEventEmitter。"""

    def test_sequence_starts_at_one(self) -> None:
        """事件序号从 1 开始。"""
        emitter = RunEventEmitter()
        event = emitter.emit("test", {"key": "value"})
        assert event.sequence == 1

    def test_sequence_strictly_increments(self) -> None:
        """事件序号严格递增。"""
        emitter = RunEventEmitter()
        event1 = emitter.emit("event_1", {})
        event2 = emitter.emit("event_2", {})
        event3 = emitter.emit("event_3", {})
        assert event1.sequence == 1
        assert event2.sequence == 2
        assert event3.sequence == 3

    def test_two_emitters_have_independent_sequences(self) -> None:
        """两个 emitter 的序号独立。"""
        emitter1 = RunEventEmitter()
        emitter2 = RunEventEmitter()
        event1 = emitter1.emit("test", {})
        event2 = emitter2.emit("test", {})
        assert event1.sequence == 1
        assert event2.sequence == 1

    def test_payload_is_defensively_copied(self) -> None:
        """payload 被防御性复制。"""
        original = {"nested": {"key": "value"}}
        emitter = RunEventEmitter()
        event = emitter.emit("test", original)
        # 修改原始字典不影响事件
        original["nested"]["key"] = "changed"
        assert event.payload["nested"]["key"] == "value"

    def test_negative_elapsed_is_rejected(self) -> None:
        """负耗时被拒绝。"""
        emitter = RunEventEmitter()
        with pytest.raises(ValueError, match="elapsed"):
            emitter.emit("test", {}, elapsed_ms=-1.0)

    def test_run_id_is_unique(self) -> None:
        """run_id 是唯一的。"""
        emitter1 = RunEventEmitter()
        emitter2 = RunEventEmitter()
        assert emitter1.run_id != emitter2.run_id

    def test_run_id_can_be_injected(self) -> None:
        """run_id 可以被注入。"""
        emitter = RunEventEmitter(run_id="custom-run-id")
        assert emitter.run_id == "custom-run-id"

    def test_child_has_parent_run_id(self) -> None:
        """子 emitter 拥有 parent_run_id。"""
        parent = RunEventEmitter(run_id="parent-run")
        child = parent.child()
        assert child.parent_run_id == "parent-run"
        assert child.run_id != "parent-run"

    def test_child_has_independent_sequence(self) -> None:
        """子 emitter 拥有独立的序号。"""
        parent = RunEventEmitter()
        parent.emit("parent_event", {})
        child = parent.child()
        event = child.emit("child_event", {})
        assert event.sequence == 1


class TestEventCollector:
    """测试 EventCollector。"""

    def test_collector_records_events(self) -> None:
        """collector 记录事件。"""
        collector = EventCollector()
        emitter = RunEventEmitter(sink=collector)
        emitter.emit("event_1", {"a": 1})
        emitter.emit("event_2", {"b": 2})
        snapshot = collector.snapshot()
        assert len(snapshot) == 2
        assert snapshot[0].type == "event_1"
        assert snapshot[1].type == "event_2"

    def test_snapshot_is_immutable(self) -> None:
        """snapshot 是不可变的。"""
        collector = EventCollector()
        emitter = RunEventEmitter(sink=collector)
        emitter.emit("test", {})
        snapshot = collector.snapshot()
        # snapshot 是 tuple，不可变
        assert isinstance(snapshot, tuple)

    def test_snapshot_is_isolated(self) -> None:
        """snapshot 与后续事件隔离。"""
        collector = EventCollector()
        emitter = RunEventEmitter(sink=collector)
        emitter.emit("event_1", {})
        snapshot1 = collector.snapshot()
        emitter.emit("event_2", {})
        snapshot2 = collector.snapshot()
        assert len(snapshot1) == 1
        assert len(snapshot2) == 2


class TestSinkError:
    """测试 sink 错误传播。"""

    def test_sink_exception_propagates(self) -> None:
        """sink 异常原样传播。"""
        class FailingSink:
            def emit(self, event: RunEvent) -> None:
                raise RuntimeError("sink failure")

        emitter = RunEventEmitter(sink=FailingSink())
        with pytest.raises(RuntimeError, match="sink failure"):
            emitter.emit("test", {})

    def test_event_fully_constructed_before_sink(self) -> None:
        """事件在调用 sink 前完全构造。"""
        captured_event = None

        class CapturingSink:
            def emit(self, event: RunEvent) -> None:
                nonlocal captured_event
                captured_event = event

        emitter = RunEventEmitter(sink=CapturingSink())
        emitter.emit("test", {"key": "value"})
        assert captured_event is not None
        assert captured_event.sequence == 1
        assert captured_event.type == "test"
        assert captured_event.payload == {"key": "value"}


class TestClockInjection:
    """测试时钟注入。"""

    def test_utc_now_can_be_injected(self) -> None:
        """utc_now 可以被注入。"""
        fixed_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        emitter = RunEventEmitter(utc_now=lambda: fixed_time)
        event = emitter.emit("test", {})
        assert event.occurred_at == fixed_time

    def test_elapsed_ms_can_be_overridden(self) -> None:
        """elapsed_ms 可以被显式指定。"""
        emitter = RunEventEmitter()
        event = emitter.emit("test", {}, elapsed_ms=12345.0)
        assert event.elapsed_ms == 12345.0

    def test_elapsed_ms_is_non_negative(self) -> None:
        """elapsed_ms 总是非负的（使用真实时钟）。"""
        emitter = RunEventEmitter()
        event = emitter.emit("test", {})
        assert event.elapsed_ms >= 0


class TestIdFactory:
    """测试 ID factory 注入。"""

    def test_id_factory_can_be_injected(self) -> None:
        """id_factory 可以被注入。"""
        ids = ["custom-id-1", "custom-id-2"]
        emitter = RunEventEmitter(id_factory=lambda: ids.pop(0))
        assert emitter.run_id == "custom-id-1"
        child = emitter.child()
        assert child.run_id == "custom-id-2"