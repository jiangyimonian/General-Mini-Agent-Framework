"""运行上下文、事件 envelope 和事件发射器。"""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

# 类型别名
JSONValue = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


@dataclass(frozen=True)
class RunContext:
    """运行上下文，持有 run_id 和父运行关系。"""

    run_id: str
    parent_run_id: str | None
    started_at: datetime


@dataclass(frozen=True)
class RunEvent:
    """运行事件 envelope，包装所有事件类型。"""

    run_id: str
    parent_run_id: str | None
    sequence: int
    occurred_at: datetime
    elapsed_ms: float
    type: str
    payload: dict[str, JSONValue]


class EventSink(Protocol):
    """事件 sink 协议。"""

    def emit(self, event: RunEvent) -> None: ...


class EventCollector:
    """内存事件收集器，线程安全。"""

    def __init__(self) -> None:
        self._events: list[RunEvent] = []
        self._lock = threading.Lock()

    def emit(self, event: RunEvent) -> None:
        """记录事件。"""
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> tuple[RunEvent, ...]:
        """返回不可变快照。"""
        with self._lock:
            return tuple(self._events)


class RunEventEmitter:
    """运行事件发射器，管理 run_id、序号和时钟。"""

    def __init__(
        self,
        run_id: str | None = None,
        parent_run_id: str | None = None,
        id_factory: Callable[[], str] | None = None,
        utc_now: Callable[[], datetime] | None = None,
        monotonic_ns: Callable[[], int] | None = None,
        sink: EventSink | None = None,
    ) -> None:
        self._id_factory = id_factory or (lambda: str(uuid.uuid4()))
        self._utc_now = utc_now or (lambda: datetime.now(UTC))
        self._monotonic_ns = monotonic_ns or time.monotonic_ns
        self._sink = sink

        self._run_id = run_id if run_id is not None else self._id_factory()
        self._parent_run_id = parent_run_id
        self._sequence = 0
        self._start_ns = self._monotonic_ns()
        self._lock = threading.Lock()

    @property
    def run_id(self) -> str:
        """当前 run_id。"""
        return self._run_id

    @property
    def parent_run_id(self) -> str | None:
        """父 run_id（如果有）。"""
        return self._parent_run_id

    def child(self) -> RunEventEmitter:
        """创建子 emitter，当前 run_id 作为 parent。"""
        return RunEventEmitter(
            parent_run_id=self._run_id,
            id_factory=self._id_factory,
            utc_now=self._utc_now,
            monotonic_ns=self._monotonic_ns,
            sink=self._sink,
        )

    def emit(
        self,
        event_type: str,
        payload: dict[str, JSONValue],
        *,
        elapsed_ms: float | None = None,
    ) -> RunEvent:
        """发射事件。"""
        with self._lock:
            self._sequence += 1
            now = self._utc_now()

            # 计算耗时
            if elapsed_ms is None:
                current_ns = self._monotonic_ns()
                elapsed_ms = (current_ns - self._start_ns) / 1_000_000.0

            if elapsed_ms < 0:
                raise ValueError(f"elapsed_ms must be non-negative, got {elapsed_ms}")

            # 防御性复制 payload
            payload_copy = deepcopy(payload)

            event = RunEvent(
                run_id=self._run_id,
                parent_run_id=self._parent_run_id,
                sequence=self._sequence,
                occurred_at=now,
                elapsed_ms=elapsed_ms,
                type=event_type,
                payload=payload_copy,
            )

            if self._sink is not None:
                self._sink.emit(event)

            return event

    def context(self) -> RunContext:
        """返回当前运行上下文。"""
        return RunContext(
            run_id=self._run_id,
            parent_run_id=self._parent_run_id,
            started_at=self._utc_now(),
        )