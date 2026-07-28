"""版本化 JSON trace 导出和导入。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .events import RunEvent


@dataclass(frozen=True)
class TraceDocument:
    """版本化的 trace 文档。"""

    schema_version: int
    root_run_id: str
    events: tuple[RunEvent, ...]


def trace_to_json(document: TraceDocument, *, indent: int | None = 2) -> str:
    """导出 TraceDocument 为 JSON 字符串。

    使用 UTF-8、ensure_ascii=False、sort_keys=True 和 allow_nan=False。
    """
    if document.schema_version != 1:
        raise ValueError(f"unsupported schema_version: {document.schema_version}")

    for event in document.events:
        if event.elapsed_ms < 0:
            raise ValueError(f"elapsed_ms must be non-negative, got {event.elapsed_ms}")

    data = _encode_document(document)
    return json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        indent=indent,
    )


def trace_from_json(payload: str) -> TraceDocument:
    """从 JSON 字符串导入 TraceDocument。

    只接受 schema_version == 1，拒绝非法结构。
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc

    return _decode_document(data)


def export_trace_json(document: TraceDocument, path: str | Path) -> None:
    """导出 TraceDocument 到文件。"""
    path = Path(path)
    json_str = trace_to_json(document)
    path.write_text(json_str, encoding="utf-8")


def _encode_document(document: TraceDocument) -> dict[str, Any]:
    """将 TraceDocument 编码为 JSON 兼容字典。"""
    return {
        "schema_version": document.schema_version,
        "root_run_id": document.root_run_id,
        "events": [_encode_event(e) for e in document.events],
    }


def _encode_event(event: RunEvent) -> dict[str, Any]:
    """将 RunEvent 编码为 JSON 兼容字典。"""
    return {
        "run_id": event.run_id,
        "parent_run_id": event.parent_run_id,
        "sequence": event.sequence,
        "occurred_at": event.occurred_at.isoformat(),
        "elapsed_ms": event.elapsed_ms,
        "type": event.type,
        "payload": event.payload,
    }


def _decode_document(data: dict[str, Any]) -> TraceDocument:
    """从 JSON 兼容字典解码 TraceDocument。"""
    from datetime import datetime, timezone

    schema_version = data.get("schema_version")
    if schema_version != 1:
        raise ValueError(f"unsupported schema_version: {schema_version}")

    root_run_id = data.get("root_run_id")
    if not isinstance(root_run_id, str):
        raise ValueError("root_run_id must be a string")

    events_data = data.get("events", [])
    if not isinstance(events_data, list):
        raise ValueError("events must be a list")

    events = tuple(_decode_event(e) for e in events_data)

    # 验证事件序号
    for i, event in enumerate(events):
        if event.sequence != i + 1:
            raise ValueError(f"event sequence must start at 1 and be strictly increasing, got {event.sequence} at index {i}")

    return TraceDocument(
        schema_version=schema_version,
        root_run_id=root_run_id,
        events=events,
    )


def _decode_event(data: dict[str, Any]) -> RunEvent:
    """从 JSON 兼容字典解码 RunEvent。"""
    from datetime import datetime, timezone

    run_id = data.get("run_id")
    if not isinstance(run_id, str):
        raise ValueError("event run_id must be a string")

    parent_run_id = data.get("parent_run_id")
    if parent_run_id is not None and not isinstance(parent_run_id, str):
        raise ValueError("event parent_run_id must be a string or null")

    sequence = data.get("sequence")
    if not isinstance(sequence, int):
        raise ValueError("event sequence must be an integer")

    occurred_at_str = data.get("occurred_at")
    if not isinstance(occurred_at_str, str):
        raise ValueError("event occurred_at must be an ISO 8601 string")
    try:
        # 解析 ISO 8601 时间戳
        occurred_at = datetime.fromisoformat(occurred_at_str.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid occurred_at: {occurred_at_str}") from exc

    elapsed_ms = data.get("elapsed_ms")
    if not isinstance(elapsed_ms, (int, float)):
        raise ValueError("event elapsed_ms must be a number")

    event_type = data.get("type")
    if not isinstance(event_type, str):
        raise ValueError("event type must be a string")

    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("event payload must be a dict")

    return RunEvent(
        run_id=run_id,
        parent_run_id=parent_run_id,
        sequence=sequence,
        occurred_at=occurred_at,
        elapsed_ms=float(elapsed_ms),
        type=event_type,
        payload=payload,
    )