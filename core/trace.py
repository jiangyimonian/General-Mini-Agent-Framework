"""
Trace → HTML 渲染器 — 将 Agent 推理轨迹导出为可交互的 HTML 页面。

使用:
    from core.agent import Agent
    from core.trace import render_html

    agent = Agent(llm=llm, tools=[...])
    result = agent.run("what is 2+2?")

    html = render_html(result, question="what is 2+2?")
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .events import RunEvent
from .trace_json import TraceDocument


# ─── 稳定 API：TraceDocument → HTML ────────────────────────────────────────


def trace_to_html(
    document: TraceDocument,
    *,
    title: str = "Agent Trace",
) -> str:
    """将 TraceDocument 渲染为自包含 HTML 页面。

    Args:
        document: TraceDocument 实例（schema_version 必须为 1）
        title: 页面标题

    Returns:
        自包含的 HTML 字符串
    """
    if document.schema_version != 1:
        raise ValueError(f"unsupported schema_version: {document.schema_version}")

    # 安全嵌入 JSON，转义特殊字符
    events_json = _safe_json_script(document.events)
    root_run_id_json = json.dumps(document.root_run_id, ensure_ascii=False)

    return _TRACE_HTML_TEMPLATE.format(
        title=title,
        root_run_id=root_run_id_json,
        events_data=events_json,
    )


def export_trace_html(
    document: TraceDocument,
    path: str | Path,
    *,
    title: str = "Agent Trace",
) -> None:
    """将 TraceDocument 导出为 HTML 文件。

    Args:
        document: TraceDocument 实例
        path: 输出文件路径
        title: 页面标题
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    html = trace_to_html(document, title=title)
    path.write_text(html, encoding="utf-8")


def _safe_json_script(data: Any) -> str:
    """生成安全的 JSON 数据，可嵌入 <script> 标签。

    转义规则：
    - < → \\u003c
    - > → \\u003e
    - & → \\u0026
    - 行分隔符 \\u2028 和段落分隔符 \\u2029
    """
    # 使用 dataclass 的 asdict 进行转换
    from dataclasses import asdict, is_dataclass

    def to_jsonable(obj: Any) -> Any:
        if isinstance(obj, (str, int, float, bool, type(None))):
            return obj
        if is_dataclass(obj):
            return {k: to_jsonable(v) for k, v in asdict(obj).items()}
        if isinstance(obj, dict):
            return {k: to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [to_jsonable(item) for item in obj]
        return str(obj)

    json_str = json.dumps(to_jsonable(data), ensure_ascii=False, indent=2)
    # JSON 安全转义
    return (
        json_str.replace("\\", "\\\\")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )


_TRACE_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{
    --bg: #0f1117;
    --card: #1a1d2e;
    --border: #2a2d3e;
    --text: #e1e1e1;
    --dim: #6b7280;
    --accent: #6366f1;
    --green: #22c55e;
    --yellow: #eab308;
    --cyan: #06b6d4;
    --red: #ef4444;
    --font: 'Segoe UI', system-ui, -apple-system, sans-serif;
    --mono: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    line-height: 1.6;
    padding: 2rem;
    max-width: 900px;
    margin: 0 auto;
}}
.header {{
    text-align: center;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border);
}}
.header h1 {{ font-size: 1.5rem; color: var(--accent); margin-bottom: .5rem; }}
.run-id {{ font-size: .75rem; color: var(--dim); font-family: var(--mono); }}

/* Filters */
.filters {{
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    padding: 1rem;
    background: var(--card);
    border-radius: 8px;
    margin-bottom: 1rem;
    align-items: center;
}}
.filter-group {{
    display: flex;
    align-items: center;
    gap: .5rem;
}}
.filter-group label {{
    font-size: .75rem;
    color: var(--dim);
}}
.filter-group select {{
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 4px;
    padding: .25rem .5rem;
    font-size: .8rem;
}}
.filter-group select:focus {{
    outline: 2px solid var(--accent);
    outline-offset: 1px;
}}
.btn-reset {{
    background: var(--border);
    color: var(--text);
    border: none;
    border-radius: 4px;
    padding: .25rem .75rem;
    font-size: .8rem;
    cursor: pointer;
}}
.btn-reset:hover {{ background: var(--accent); }}
.result-count {{ font-size: .8rem; color: var(--dim); margin-left: auto; }}

/* Events */
.events {{ margin-top: 1rem; }}
.event {{
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: .5rem;
    overflow: hidden;
}}
.event-header {{
    display: flex;
    align-items: center;
    gap: .5rem;
    padding: .5rem .75rem;
    background: var(--card);
    cursor: pointer;
}}
.event-type {{
    font-size: .75rem;
    font-weight: 600;
    padding: .2rem .5rem;
    border-radius: 4px;
}}
.event-type.run_started {{ background: var(--accent); color: #fff; }}
.event-type.run_finished {{ background: var(--green); color: #fff; }}
.event-type.model_request_finished {{ background: var(--cyan); color: #000; }}
.event-type.tool_finished {{ background: var(--yellow); color: #000; }}
.event-type.run_finished.error {{ background: var(--red); color: #fff; }}
.event-seq {{ font-size: .7rem; color: var(--dim); }}
.event-elapsed {{ font-size: .7rem; color: var(--dim); margin-left: auto; }}
.event-body {{
    display: none;
    padding: .75rem;
    font-size: .85rem;
    border-top: 1px solid var(--border);
    background: rgba(0,0,0,.2);
}}
.event.open .event-body {{ display: block; }}
.event-body pre {{
    font-family: var(--mono);
    font-size: .8rem;
    overflow-x: auto;
    white-space: pre-wrap;
}}
.event.hidden {{ display: none; }}

/* Stats */
.stats {{
    display: flex;
    gap: 1rem;
    justify-content: center;
    padding: 1rem;
    background: var(--card);
    border-radius: 12px;
    border: 1px solid var(--border);
    margin-top: 2rem;
    flex-wrap: wrap;
}}
.stat {{ text-align: center; }}
.stat-value {{ font-size: 1.2rem; font-weight: 700; color: var(--accent); }}
.stat-label {{ font-size: .7rem; text-transform: uppercase; color: var(--dim); }}
</style>
</head>
<body>

<div class="header">
    <h1>🔍 Agent Trace</h1>
    <div class="run-id">Run: <span id="run-id"></span></div>
</div>

<div class="filters" role="search" aria-label="Filter events">
    <div class="filter-group">
        <label for="filter-type">Event Type</label>
        <select id="filter-type">
            <option value="">All</option>
        </select>
    </div>
    <div class="filter-group">
        <label for="filter-run">Run ID</label>
        <select id="filter-run">
            <option value="">All</option>
        </select>
    </div>
    <div class="filter-group">
        <label for="filter-stop">Stop Reason</label>
        <select id="filter-stop">
            <option value="">All</option>
        </select>
    </div>
    <div class="filter-group">
        <label for="filter-error">Errors Only</label>
        <select id="filter-error">
            <option value="">All</option>
            <option value="error">Errors</option>
        </select>
    </div>
    <button class="btn-reset" onclick="resetFilters()">Reset</button>
    <div class="result-count" aria-live="polite"><span id="visible-count">0</span> / <span id="total-count">0</span> events</div>
</div>

<div id="events" class="events"></div>

<div class="stats">
    <div class="stat">
        <div class="stat-value" id="event-count">-</div>
        <div class="stat-label">Events</div>
    </div>
    <div class="stat">
        <div class="stat-value" id="total-elapsed">-</div>
        <div class="stat-label">Total Elapsed (ms)</div>
    </div>
</div>

<script>
const EVENTS = {events_data};
const ROOT_RUN_ID = {root_run_id};

document.getElementById('run-id').textContent = ROOT_RUN_ID;
document.getElementById('total-count').textContent = EVENTS.length;
document.getElementById('event-count').textContent = EVENTS.length;

let totalElapsed = 0;
EVENTS.forEach(e => {{
    if (e.elapsed_ms > totalElapsed) totalElapsed = e.elapsed_ms;
}});
document.getElementById('total-elapsed').textContent = totalElapsed.toFixed(1);

// Build filter options from data
const typeSet = new Set();
const runSet = new Set();
const stopSet = new Set();

EVENTS.forEach(e => {{
    typeSet.add(e.type);
    if (e.run_id) runSet.add(e.run_id);
    if (e.payload && e.payload.stop_reason) stopSet.add(e.payload.stop_reason);
}});

function populateSelect(id, values) {{
    const sel = document.getElementById(id);
    values.forEach(v => {{
        const opt = document.createElement('option');
        opt.value = v;
        opt.textContent = v;
        sel.appendChild(opt);
    }});
}}

populateSelect('filter-type', Array.from(typeSet).sort());
populateSelect('filter-run', Array.from(runSet).sort());
populateSelect('filter-stop', Array.from(stopSet).sort());

// Render events
const eventsEl = document.getElementById('events');

EVENTS.forEach(event => {{
    const stopReason = event.payload && event.payload.stop_reason ? event.payload.stop_reason : '';
    const hasError = event.payload && (event.payload.error || stopReason === 'error' || stopReason === 'model_error');
    const typeClass = event.type + (hasError ? ' error' : '');

    const div = document.createElement('div');
    div.className = 'event open';
    div.setAttribute('data-event-type', event.type);
    div.setAttribute('data-run-id', event.run_id || '');
    div.setAttribute('data-stop-reason', stopReason);
    div.setAttribute('data-error', hasError ? 'true' : 'false');

    div.innerHTML = `
        <div class="event-header" onclick="this.parentElement.classList.toggle('open')">
            <span class="event-type ${{typeClass}}">${{event.type}}</span>
            <span class="event-seq">#${{event.sequence}}</span>
            <span class="event-elapsed">${{event.elapsed_ms.toFixed(1)}}ms</span>
        </div>
        <div class="event-body">
            <pre>${{JSON.stringify(event.payload, null, 2)}}</pre>
        </div>
    `;
    eventsEl.appendChild(div);
}});

// Filter logic
function applyFilters() {{
    const typeVal = document.getElementById('filter-type').value;
    const runVal = document.getElementById('filter-run').value;
    const stopVal = document.getElementById('filter-stop').value;
    const errorVal = document.getElementById('filter-error').value;

    const allEvents = document.querySelectorAll('.event');
    let visible = 0;

    allEvents.forEach(el => {{
        const match = true
            && (!typeVal || el.getAttribute('data-event-type') === typeVal)
            && (!runVal || el.getAttribute('data-run-id') === runVal)
            && (!stopVal || el.getAttribute('data-stop-reason') === stopVal)
            && (!errorVal || errorVal === 'error' && el.getAttribute('data-error') === 'true');

        el.classList.toggle('hidden', !match);
        if (match) visible++;
    }});

    document.getElementById('visible-count').textContent = visible;
}}

document.getElementById('filter-type').addEventListener('change', applyFilters);
document.getElementById('filter-run').addEventListener('change', applyFilters);
document.getElementById('filter-stop').addEventListener('change', applyFilters);
document.getElementById('filter-error').addEventListener('change', applyFilters);

function resetFilters() {{
    document.getElementById('filter-type').value = '';
    document.getElementById('filter-run').value = '';
    document.getElementById('filter-stop').value = '';
    document.getElementById('filter-error').value = '';
    applyFilters();
}}

applyFilters();
</script>
</body>
</html>
"""


# ─── 旧 API（兼容包装，带 DeprecationWarning）──────────────────────────────


def render_html(
    result: Any,
    *,
    question: str = "",
    title: str = "General Mini Agent Framework - Agent Trace",
) -> str:
    """将 AgentResult（或包含 trace 的对象）渲染为自包含 HTML 页面。

    Args:
        result: AgentResult 实例，或任何有 .trace, .content, .usage, .iterations 的对象
        question: 用户问题
        title: 页面标题
    """
    trace = getattr(result, "trace", [])
    content = getattr(result, "content", "")
    usage = getattr(result, "usage", {})
    iterations = getattr(result, "iterations", 0)

    trace_json = json.dumps(trace, ensure_ascii=False)

    return HTML_TEMPLATE.format(
        title=title,
        question=json.dumps(question, ensure_ascii=False),
        answer=json.dumps(content, ensure_ascii=False),
        usage_json=json.dumps(usage, ensure_ascii=False),
        iterations=iterations,
        trace_data=trace_json,
    )


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{
    --bg: #0f1117;
    --card: #1a1d2e;
    --border: #2a2d3e;
    --text: #e1e1e1;
    --dim: #6b7280;
    --accent: #6366f1;
    --green: #22c55e;
    --yellow: #eab308;
    --cyan: #06b6d4;
    --red: #ef4444;
    --font: 'Segoe UI', system-ui, -apple-system, sans-serif;
    --mono: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    line-height: 1.6;
    padding: 2rem;
    max-width: 900px;
    margin: 0 auto;
}}
.header {{
    text-align: center;
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
}}
.header h1 {{ font-size: 1.5rem; color: var(--accent); margin-bottom: .5rem; }}
.question-box {{
    background: linear-gradient(135deg, #1e1b4b 0%, #1a1d2e 100%);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 2rem;
}}
.question-box .label {{
    font-size: .75rem;
    text-transform: uppercase;
    color: var(--accent);
    margin-bottom: .5rem;
}}
.question-box .text {{ font-size: 1.1rem; }}

/* Round */
.round {{
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 1rem;
    overflow: hidden;
    transition: all .2s;
}}
.round:hover {{ border-color: var(--accent); }}
.round-header {{
    display: flex;
    align-items: center;
    gap: .75rem;
    padding: .75rem 1rem;
    background: var(--card);
    cursor: pointer;
    user-select: none;
}}
.round-num {{
    background: var(--accent);
    color: #fff;
    width: 28px; height: 28px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: .8rem;
    font-weight: 600;
    flex-shrink: 0;
}}
.round-summary {{ flex:1; font-size: .85rem; color: var(--dim); }}
.round-arrow {{ transition: transform .2s; font-size: .75rem; }}
.round.open .round-arrow {{ transform: rotate(180deg); }}
.round-body {{ display: none; padding: 1rem 1rem 1rem 3rem; }}
.round.open .round-body {{ display: block; }}

/* Steps */
.step {{ margin-bottom: 1rem; padding-left: 1rem; border-left: 2px solid var(--border); }}
.step.thought {{ border-left-color: var(--cyan); }}
.step.tool   {{ border-left-color: var(--yellow); }}
.step.result {{ border-left-color: var(--green); }}
.step.error  {{ border-left-color: var(--red); }}
.step-label {{
    font-size: .7rem;
    text-transform: uppercase;
    letter-spacing: .05em;
    margin-bottom: .3rem;
}}
.step.thought .step-label {{ color: var(--cyan); }}
.step.tool   .step-label {{ color: var(--yellow); }}
.step.result .step-label {{ color: var(--green); }}
.step.error  .step-label {{ color: var(--red); }}
.step-content {{ font-size: .9rem; }}
pre.args {{
    background: var(--card);
    border-radius: 6px;
    padding: .5rem .75rem;
    font-family: var(--mono);
    font-size: .8rem;
    overflow-x: auto;
    margin-top: .3rem;
}}

/* Final */
.final {{
    background: linear-gradient(135deg, #064e3b 0%, #1a1d2e 100%);
    border: 1px solid var(--green);
    border-radius: 12px;
    padding: 1.5rem;
    margin: 2rem 0;
}}
.final-label {{
    font-size: .75rem;
    text-transform: uppercase;
    color: var(--green);
    margin-bottom: .5rem;
}}

/* Stats */
.stats {{
    display: flex;
    gap: 1.5rem;
    justify-content: center;
    padding: 1rem;
    background: var(--card);
    border-radius: 12px;
    border: 1px solid var(--border);
}}
.stat {{ text-align: center; }}
.stat-value {{ font-size: 1.3rem; font-weight: 700; color: var(--accent); }}
.stat-label {{ font-size: .7rem; text-transform: uppercase; color: var(--dim); margin-top: .2rem; }}
</style>
</head>
<body>

<div class="header">
    <h1>🔍 General Mini Agent Framework</h1>
</div>

<div class="question-box">
    <div class="label">问题</div>
    <div class="text" id="question"></div>
</div>

<div id="rounds"></div>

<div class="final">
    <div class="final-label">✅ 最终答案</div>
    <div id="answer"></div>
</div>

<div class="stats">
    <div class="stat">
        <div class="stat-value" id="iterations">-</div>
        <div class="stat-label">迭代轮数</div>
    </div>
    <div class="stat">
        <div class="stat-value" id="total-tokens">-</div>
        <div class="stat-label">Token 用量</div>
    </div>
    <div class="stat">
        <div class="stat-value" id="prompt-tokens">-</div>
        <div class="stat-label">Prompt Tokens</div>
    </div>
    <div class="stat">
        <div class="stat-value" id="completion-tokens">-</div>
        <div class="stat-label">Completion Tokens</div>
    </div>
</div>

<script>
const TRACE = {trace_data};
const QUESTION = {question};
const ANSWER = {answer};
const USAGE = {usage_json};
const ITERATIONS = {iterations};

document.getElementById('question').textContent = QUESTION;
document.getElementById('answer').textContent = ANSWER;
document.getElementById('iterations').textContent = ITERATIONS;
const totalTokens = USAGE.total_tokens || 0;
const promptTokens = USAGE.prompt_tokens || 0;
const completionTokens = USAGE.completion_tokens || 0;
document.getElementById('total-tokens').textContent = totalTokens.toLocaleString();
document.getElementById('prompt-tokens').textContent = promptTokens.toLocaleString();
document.getElementById('completion-tokens').textContent = completionTokens.toLocaleString();

const roundsEl = document.getElementById('rounds');
const rounds = new Map();

// Build rounds from trace
for (const step of TRACE) {{
    const iter = step.iteration || 0;
    if (!rounds.has(iter)) rounds.set(iter, []);
    rounds.get(iter).push(step);
}}

for (const [num, steps] of rounds) {{
    const roundDiv = document.createElement('div');
    roundDiv.className = 'round open';

    // Summary
    const thoughts = steps.filter(s => s.thought).length;
    const tools = steps.filter(s => s.tool).map(s => s.tool);
    const hasFinal = steps.some(s => s.final_answer);

    roundDiv.innerHTML = `
        <div class="round-header" onclick="this.parentElement.classList.toggle('open')">
            <div class="round-num">${{num + 1}}</div>
            <div class="round-summary">
                ${{hasFinal ? '🎯 最终答案' : '💭 ' + thoughts + ' 次思考'}}
                ${{tools.length ? ' · 🔧 ' + tools.join(', ') : ''}}
            </div>
            <div class="round-arrow">▼</div>
        </div>
        <div class="round-body"></div>
    `;

    const body = roundDiv.querySelector('.round-body');

    for (const step of steps) {{
        if (step.thought && !step.final_answer) {{
            const div = document.createElement('div');
            div.className = 'step thought';
            div.innerHTML = (
                `<div class="step-label">💭 思考</div>` +
                `<div class="step-content">${{escapeHtml(step.thought)}}</div>`
            );
            body.appendChild(div);
        }}
        if (step.tool) {{
            const div = document.createElement('div');
            div.className = 'step tool';
            div.innerHTML = `
                <div class="step-label">🔧 工具调用: ${{escapeHtml(step.tool)}}</div>
                <pre class="args">${{JSON.stringify(step.arguments, null, 2)}}</pre>
            `;
            body.appendChild(div);
        }}
        if (step.observation) {{
            const div = document.createElement('div');
            div.className = 'step result';
            div.innerHTML = (
                `<div class="step-label">📤 结果</div>` +
                `<div class="step-content">${{escapeHtml(String(step.observation))}}</div>`
            );
            body.appendChild(div);
        }}
        if (step.final_answer) {{
            const div = document.createElement('div');
            div.className = 'step result';
            div.innerHTML = (
                `<div class="step-label">🎯 得出答案</div>` +
                `<div class="step-content">${{escapeHtml(String(step.final_answer))}}</div>`
            );
            body.appendChild(div);
        }}
    }}

    roundsEl.appendChild(roundDiv);
}}

function escapeHtml(str) {{
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}}
</script>
</body>
</html>
"""


def debate_to_html(
    debate_result: Any,
    *,
    question: str = "",
    title: str = "General Mini Agent Framework - Debate Trace",
) -> str:
    """将 DebateResult 渲染为自包含 HTML 页面。

    Args:
        debate_result: DebateResult 实例
        question: 辩论问题
        title: 页面标题
    """
    rounds = getattr(debate_result, "rounds", [])
    judge_turn = getattr(debate_result, "judge_turn", None)
    verdict = getattr(debate_result, "verdict", "")
    total_usage = getattr(debate_result, "total_usage", {})
    rounds_data = [asdict(round_) if is_dataclass(round_) else round_ for round_ in rounds]
    judge_data = asdict(judge_turn) if is_dataclass(judge_turn) else judge_turn

    return DEBATE_HTML_TEMPLATE.format(
        title=title,
        question=json.dumps(question, ensure_ascii=False),
        verdict=json.dumps(verdict, ensure_ascii=False),
        usage_json=json.dumps(total_usage, ensure_ascii=False),
        rounds_data=json.dumps(rounds_data, ensure_ascii=False),
        judge_data=json.dumps(judge_data, ensure_ascii=False),
    )


DEBATE_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
:root {{
    --bg: #0f1117;
    --card: #1a1d2e;
    --border: #2a2d3e;
    --text: #e1e1e1;
    --dim: #6b7280;
    --accent: #6366f1;
    --green: #22c55e;
    --yellow: #eab308;
    --cyan: #06b6d4;
    --pink: #ec4899;
    --font: 'Segoe UI', system-ui, -apple-system, sans-serif;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    line-height: 1.6;
    padding: 2rem;
    max-width: 960px;
    margin: 0 auto;
}}
.header {{
    text-align: center;
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
}}
.header h1 {{ font-size: 1.5rem; color: var(--accent); margin-bottom: .5rem; }}
.question-box {{
    background: linear-gradient(135deg, #1e1b4b 0%, #1a1d2e 100%);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    margin-bottom: 2rem;
}}

/* Rounds */
.round {{
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 2rem;
    overflow: hidden;
}}
.round-title {{
    padding: 0.75rem 1.25rem;
    background: var(--card);
    font-weight: 600;
    font-size: 0.9rem;
    color: var(--accent);
    border-bottom: 1px solid var(--border);
}}

/* Role cards */
.role-card {{
    margin: 1rem;
    padding: 1rem 1.25rem;
    border-radius: 8px;
    border-left: 3px solid;
}}
.role-card.Solver {{ border-color: var(--cyan); background: rgba(6,182,212,.05); }}
.role-card.Critic {{ border-color: var(--yellow); background: rgba(234,179,8,.05); }}
.role-card.Judge  {{ border-color: var(--green); background: rgba(34,197,94,.05); }}
.role-name {{
    font-weight: 700;
    font-size: 0.85rem;
    margin-bottom: 0.5rem;
}}
.role-card.Solver .role-name {{ color: var(--cyan); }}
.role-card.Critic .role-name {{ color: var(--yellow); }}
.role-card.Judge  .role-name {{ color: var(--green); }}
.role-content {{
    font-size: 0.88rem;
    white-space: pre-wrap;
    max-height: 400px;
    overflow-y: auto;
}}

/* Verdict */
.verdict {{
    background: linear-gradient(135deg, #064e3b 0%, #1a1d2e 100%);
    border: 2px solid var(--green);
    border-radius: 12px;
    padding: 1.5rem;
    margin: 2rem 0;
}}
.verdict-label {{
    font-size: 0.75rem;
    color: var(--green);
    text-transform: uppercase;
    margin-bottom: 0.5rem;
}}

/* Stats */
.stats {{
    display: flex; gap: 1.5rem; justify-content: center;
    padding: 1rem; background: var(--card);
    border-radius: 12px; border: 1px solid var(--border);
}}
.stat {{ text-align: center; }}
.stat-value {{ font-size: 1.3rem; font-weight: 700; color: var(--accent); }}
.stat-label {{ font-size: 0.7rem; text-transform: uppercase; color: var(--dim); }}
</style>
</head>
<body>
<div class="header"><h1>⚔️ General Mini Agent Framework</h1></div>
<div class="question-box">
    <div style="font-size:.7rem;color:var(--dim);text-transform:uppercase;margin-bottom:.3rem">
        辩论问题
    </div>
    <div style="font-size:1.1rem" id="question"></div>
</div>
<div id="rounds"></div>
<div class="verdict">
    <div class="verdict-label">📋 最终裁决</div>
    <div id="verdict"></div>
</div>
<div class="stats">
    <div class="stat">
        <div class="stat-value" id="total-tokens">-</div>
        <div class="stat-label">Total Tokens</div>
    </div>
    <div class="stat">
        <div class="stat-value" id="prompt-tokens">-</div>
        <div class="stat-label">Prompt</div>
    </div>
    <div class="stat">
        <div class="stat-value" id="completion-tokens">-</div>
        <div class="stat-label">Completion</div>
    </div>
</div>
<script>
const ROUNDS = {rounds_data};
const JUDGE = {judge_data};
const QUESTION = {question};
const VERDICT = {verdict};
const USAGE = {usage_json};

document.getElementById('question').textContent = QUESTION;
document.getElementById('verdict').textContent = VERDICT;
const totalTokens = USAGE.total_tokens || 0;
const promptTokens = USAGE.prompt_tokens || 0;
const completionTokens = USAGE.completion_tokens || 0;
document.getElementById('total-tokens').textContent = totalTokens.toLocaleString();
document.getElementById('prompt-tokens').textContent = promptTokens.toLocaleString();
document.getElementById('completion-tokens').textContent = completionTokens.toLocaleString();

const roundsEl = document.getElementById('rounds');
for (const round of ROUNDS) {{
    const div = document.createElement('div');
    div.className = 'round';
    div.innerHTML = (
        `<div class="round-title">第 ${{round.number}} 轮</div>` +
        '<div class="role-cards"></div>'
    );
    const cards = div.querySelector('.role-cards');
    for (const resp of (round.turns || [])) {{
        const card = document.createElement('div');
        card.className = `role-card ${{resp.role}}`;
        card.innerHTML = (
            `<div class="role-name">${{resp.role}}</div>` +
            `<div class="role-content">${{resp.content}}</div>`
        );
        cards.appendChild(card);
    }}
    roundsEl.appendChild(div);
}}
</script>
</body>
</html>
"""


# ─── 导出工具函数 ──────────────────────────────────────────


def export_trace(result: Any, path: str, *, question: str = "", title: str = "") -> None:
    """便捷函数：直接导出 Agent 推理轨迹为 HTML 文件。

    Usage:
        from core.trace import export_trace
        result = agent.run("...")
        export_trace(result, "output/trace.html", question="...")
    """
    import os as _os
    _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
    html = render_html(
        result,
        question=question,
        title=title or "General Mini Agent Framework - Agent Trace",
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def export_debate(result: Any, path: str, *, question: str = "", title: str = "") -> None:
    """便捷函数：直接导出辩论结果为 HTML 文件。"""
    import os as _os
    _os.makedirs(_os.path.dirname(path) or ".", exist_ok=True)
    html = debate_to_html(
        result,
        question=question,
        title=title or "General Mini Agent Framework - Debate Trace",
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
