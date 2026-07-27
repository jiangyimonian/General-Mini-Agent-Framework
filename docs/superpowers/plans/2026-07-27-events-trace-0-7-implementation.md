# 0.7.0 事件与 Trace 实施计划

> **供 Agent 执行者使用：** 必须使用 `subagent-driven-development`（推荐）或
> `executing-plans` 逐任务实施。使用复选框（`- [ ]`）跟踪进度。

**目标：** 为同步、流式、异步和 Debate 运行增加统一 run ID、父子关系、事件 envelope、耗时
摘要和版本化 JSON trace，同时保持现有公开流式事件兼容。

**架构：** 新建 `core/events.py` 管理运行上下文与事件 sink，新建 `core/trace_json.py` 管理纯数据
trace 文档和 JSON 编解码。Agent/Debate 继续拥有业务状态，只在状态变化边界发出事件；现有
`StreamEvent` 与 `DebateStreamEvent` 不改形状，由适配层包装到统一 envelope。

**技术栈：** Python 3.12+、dataclass、Protocol、UUID、UTC datetime、`time.monotonic_ns()`、JSON。

## 全局约束

- 开始前 `0.6.0` 的同步、流式和异步终态语义必须稳定。
- 统一事件为新增 API，不删除或改写既有 StreamEvent 字段。
- 每次公开运行默认生成唯一 `run_id`；子运行必须携带 `parent_run_id`。
- 事件序号在单次运行内从 1 严格递增，不跨运行共享计数器。
- wall-clock 时间只用于展示，耗时使用 monotonic clock 计算。
- 默认事件不得记录认证头、API Key、完整请求 header 或异常对象。
- sink 异常按调用方集成错误原样传播，不转换为模型错误；未完成运行不得写回记忆。
- JSON schema 必须包含整数 `schema_version = 1`。

---

## 文件职责

- `core/events.py`：`RunContext`、`RunEvent`、`EventSink`、运行 ID/时钟注入与发射器。
- `core/trace_json.py`：`TraceDocument`、JSON 安全校验、导出和导入。
- `core/agent.py`、`core/async_agent.py`：Agent 事件边界与 `run_id` 结果字段。
- `core/debate.py`：Debate 父运行与参与者/Judge 子运行关联。
- `core/llm.py`、`core/async_llm.py`：脱敏模型请求摘要和耗时数据来源。
- `tests/test_events.py`：ID、序号、时钟、sink 错误和 JSON 往返。
- 现有 Agent/Debate 测试：兼容性和父子关联。

### 任务 1：运行上下文与事件 envelope

**接口：**

```python
@dataclass(frozen=True)
class RunContext:
    run_id: str
    parent_run_id: str | None
    started_at: datetime

@dataclass(frozen=True)
class RunEvent:
    run_id: str
    parent_run_id: str | None
    sequence: int
    occurred_at: datetime
    elapsed_ms: float
    type: str
    payload: dict[str, JSONValue]

class EventSink(Protocol):
    def emit(self, event: RunEvent) -> None: ...

class EventCollector:
    def emit(self, event: RunEvent) -> None: ...
    def snapshot(self) -> tuple[RunEvent, ...]: ...
```

- [ ] **步骤 1：编写事件单元测试**

使用固定 ID factory、UTC clock 和 monotonic clock，断言两个 emitter 的序号均从 1 开始，
同一 emitter 严格递增，payload 被防御性复制，负耗时被拒绝。

- [ ] **步骤 2：运行测试并确认失败**

```powershell
python -m pytest tests/test_events.py -v
```

- [ ] **步骤 3：实现 `RunEventEmitter`**

构造器接受可注入 `id_factory`、`utc_now`、`monotonic_ns` 和可选 sink。`child()` 创建新的
run ID 并把当前 run ID 作为 parent；所有计数器和开始时间属于 emitter 实例。实现线程安全的
`EventCollector`，其 `snapshot()` 返回不可变快照，供 JSON 导出和 Demo 使用。

- [ ] **步骤 4：定义 sink 错误语义**

不捕获 sink 的编程异常；调用方能看到原异常。事件对象在调用 sink 前完全构造，sink 不得获得
可修改的内部 payload 引用。

- [ ] **步骤 5：运行并提交**

```powershell
python -m pytest tests/test_events.py -v
git add core/events.py tests/test_events.py
git commit -m "feat: define isolated run events"
```

### 任务 2：Agent 同步、流式和异步事件适配

**接口变更：**

```python
@dataclass
class AgentResult:
    ...
    run_id: str = ""

Agent(..., event_sink: EventSink | None = None)
AsyncAgent(..., event_sink: EventSink | None = None)

run(..., run_context: RunContext | None = None) -> AgentResult
run_async(..., run_context: RunContext | None = None) -> AgentResult
```

- [ ] **步骤 1：增加兼容和事件顺序测试**

对同一脚本分别执行同步、流式和异步 Agent，断言既有公开事件内容不变，统一 sink 收到
`run_started -> model_request_started -> model_request_finished -> tool_finished/final -> run_finished`，
且所有事件共享一个 run ID。

- [ ] **步骤 2：增加 sink 失败测试**

让 sink 在模型请求前和工具完成后分别抛错。断言原异常传播，后续模型/工具不再调用，且会话
记忆没有部分写回。

- [ ] **步骤 3：在控制流真实边界发射事件**

不得从完成后的 trace 反推事件。模型摘要只包含 endpoint、model、消息数量、工具数量、usage、
状态码、错误码和耗时；默认不包含消息正文和工具参数。

- [ ] **步骤 4：保持现有事件兼容**

`run_stream()` 和 `run_stream_async()` 继续 yield 原 `StreamEvent`。统一 `RunEvent` 只发给 sink；
调用方需要 envelope 时使用后续 JSON trace 或自定义 sink。

- [ ] **步骤 5：运行并提交**

```powershell
python -m pytest tests/test_agent.py tests/test_async_agent.py tests/test_events.py -v
git add core/agent.py core/async_agent.py tests/test_agent.py tests/test_async_agent.py tests/test_events.py
git commit -m "feat: emit agent lifecycle events"
```

### 任务 3：Debate 父子运行关系

**接口变更：**

```python
@dataclass
class DebateResult:
    ...
    run_id: str = ""

Debate(..., event_sink: EventSink | None = None)
Debate.run(question: str, *, run_context: RunContext | None = None) -> DebateResult
```

- [ ] **步骤 1：增加父子关系测试**

两参与者、两轮、一个 Judge 的运行应产生一个 Debate run ID 和五个不同 Agent 子 run ID。
每个子事件的 `parent_run_id` 等于 Debate run ID；重复运行不得复用任何 ID。

- [ ] **步骤 2：实现显式上下文传递**

Debate 为每次角色调用创建 child context 并传入 Agent，不从 AgentResult 猜测关系。同步与流式
角色顺序、失败短路和 Judge 边界保持不变。

- [ ] **步骤 3：运行并提交**

```powershell
python -m pytest tests/test_debate.py tests/test_events.py -v
git add core/debate.py tests/test_debate.py tests/test_events.py
git commit -m "feat: link debate and agent runs"
```

### 任务 4：版本化 JSON trace

**接口：**

```python
@dataclass(frozen=True)
class TraceDocument:
    schema_version: int
    root_run_id: str
    events: tuple[RunEvent, ...]

def trace_to_json(document: TraceDocument, *, indent: int | None = 2) -> str: ...
def trace_from_json(payload: str) -> TraceDocument: ...
def export_trace_json(document: TraceDocument, path: str | Path) -> None: ...
```

- [ ] **步骤 1：增加 JSON 往返和拒绝测试**

固定事件文档导出后再导入应结构相等；重复导出字节一致。拒绝未知 schema version、重复或倒序
sequence、非 UTC 时间、NaN、异常对象和与 root 无关的事件。

- [ ] **步骤 2：增加脱敏测试**

输入含 `Authorization: Bearer sk-secret` 的模型错误，导出文本不得包含 `sk-secret`、Bearer 值
或原始 header。

- [ ] **步骤 3：实现纯数据编解码**

JSON 使用 UTF-8、`ensure_ascii=False`、`sort_keys=True` 和 `allow_nan=False`。导入只接受明确
字段和 `schema_version == 1`，不得实例化任意类。

- [ ] **步骤 4：运行并提交**

```powershell
python -m pytest tests/test_events.py -v
git add core/trace_json.py tests/test_events.py
git commit -m "feat: export versioned JSON traces"
```

### 任务 5：稳定导出、文档和 0.7.0 发布

**文件：** `core/__init__.py`、`demo/export_demo.py`、`README.md`、`PLAN.md`、`ROADMAP.md`、
`CHANGELOG.md`、`pyproject.toml` 和现有契约测试。

- [ ] **步骤 1：先更新现有契约测试**

要求版本 `0.7.0`，导出全部事件/JSON 类型，README 说明现有 StreamEvent 未破坏、sink 异常传播、
schema version 和默认脱敏字段。

- [ ] **步骤 2：更新 Demo**

Demo 使用内存 sink 收集事件并导出 `.json`；不得访问新的外部服务，也不得把 API Key 写入文件。

- [ ] **步骤 3：更新文档和版本**

PLAN 记录事件层不拥有业务状态；ROADMAP 移除统一事件、run ID、耗时摘要和 JSON trace；HTML
过滤/对比仍保留为后续。版本提升到 `0.7.0`。

- [ ] **步骤 4：执行一次完整发布验证**

```powershell
python -m pytest tests -v
python -m compileall -q core demo tests
ruff check core tests demo
python -m build
python -m twine check dist/*
git diff --check
```

- [ ] **步骤 5：提交发布**

```powershell
git add core/__init__.py demo/export_demo.py README.md PLAN.md ROADMAP.md CHANGELOG.md pyproject.toml tests/test_docs_contract.py tests/test_package_metadata.py
git commit -m "feat: release observable runs in 0.7.0"
```

## 验收标准

- 每次 Agent 或 Debate 运行获得非空唯一 run ID，重复和并发运行不复用状态。
- 同一运行事件序号从 1 严格递增；耗时来自 monotonic clock 且不为负。
- Debate 参与者和 Judge 具有独立子 run ID，并正确指向 Debate 父 run ID。
- 现有 StreamEvent 和 DebateStreamEvent 的字段、顺序和终态保持兼容。
- sink 异常原样传播，不被误报为模型错误，失败运行不写入完整会话。
- JSON trace `schema_version` 为 1，可确定性往返，并拒绝非法结构和未知版本。
- 导出不包含认证头、API Key、异常对象或默认消息正文。
- README、PLAN、ROADMAP、Demo、稳定导出和发行元数据与实现一致。
