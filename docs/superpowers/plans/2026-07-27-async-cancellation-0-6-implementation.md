# 0.6.0 异步与取消实施计划

> **供 Agent 执行者使用：** 必须使用 `subagent-driven-development`（推荐）或
> `executing-plans` 逐任务实施。使用复选框（`- [ ]`）跟踪进度。

**目标：** 增加不阻塞模型 HTTP 的异步模型与单 Agent API，并为异步工具提供明确的 timeout
和协作式取消语义。

**架构：** 新建 `core/async_llm.py`、`core/async_tools.py` 和 `core/async_agent.py`，保持现有同步
模块稳定。异步实现复用同步模块的纯解析与数据契约，但拥有独立客户端和控制循环；取消始终
向上传播，timeout 作为可恢复的工具 observation 返回模型。

**技术栈：** Python 3.12+、`asyncio`、`httpx.AsyncClient`、AsyncIterator、pytest、Ruff。

## 全局约束

- 开始前 `0.5.0` 的结构化工具结果和授权协议必须已经稳定。
- 不修改 `Agent.run()`、`Agent.run_stream()`、`LLM.chat()` 和 `LLM.chat_stream()` 的契约。
- 不宣称能够强制终止已经在线程中运行的同步 Python 工具。
- `asyncio.CancelledError` 必须原样传播，不得包装成模型错误或工具错误。
- timeout、授权和工具异常使用不同错误码。
- `AsyncAgent` 的运行状态必须局部化，允许同一实例并发运行。
- `0.6.0` 不实现异步 Debate、异步 Chroma 或通用工作流。
- 测试使用 `asyncio.run()`，不新增 pytest 异步插件依赖。

---

## 文件职责

- `core/llm.py`：抽取同步/异步共用的纯响应与 SSE payload 解析函数。
- `core/async_llm.py`：异步模型协议、`AsyncLLM`、异步客户端生命周期和 SSE 读取。
- `core/async_tools.py`：async/sync callable 调度、deadline、timeout 和取消传播。
- `core/async_agent.py`：异步 ReAct 与异步流式控制循环。
- `core/__init__.py`：异步稳定导出。
- `tests/test_async_llm.py`：异步 HTTP、SSE、重试和取消。
- `tests/test_async_agent.py`：异步工具链、timeout、取消、记忆写回和并发隔离。
- `demo/reasoning_async.py`：最小异步示例。

### 任务 1：异步模型协议与纯解析复用

**接口：**

```python
@runtime_checkable
class AsyncChatModel(Protocol):
    async def chat_async(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse: ...

@runtime_checkable
class AsyncStreamingChatModel(AsyncChatModel, Protocol):
    def chat_stream_async(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamChunk]: ...
```

- [ ] **步骤 1：新建异步模型契约测试**

在 `tests/test_async_llm.py` 使用脚本化 transport，验证文本响应、工具响应和两个交错工具调用
的 SSE 解析结果与同步 `LLMResponse`/`StreamChunk` 类型一致。

- [ ] **步骤 2：运行测试并确认失败**

```powershell
python -m pytest tests/test_async_llm.py -v
```

预期：异步协议和 `AsyncLLM` 尚不存在。

- [ ] **步骤 3：抽取纯解析函数**

从 `LLM` 方法中提取不访问实例状态的响应 payload 和 SSE payload 解析 helper；先运行
`tests/test_llm.py`，确保同步解析、错误分类和多工具 index 行为完全不变。

- [ ] **步骤 4：实现异步协议与 `AsyncLLM` 基本请求**

`AsyncLLM` 接收现有 `LLMConfig`，内部持有 `httpx.AsyncClient`；请求 payload、认证头、timeout、
可重试状态码和脱敏规则与同步客户端一致。

- [ ] **步骤 5：运行同步和异步模型测试**

```powershell
python -m pytest tests/test_llm.py tests/test_async_llm.py -v
```

预期：全部通过。

- [ ] **步骤 6：提交**

```powershell
git add core/llm.py core/async_llm.py tests/test_llm.py tests/test_async_llm.py
git commit -m "feat: add asynchronous model protocols"
```

### 任务 2：异步 SSE、重试和客户端生命周期

**接口：**

```python
class AsyncLLM:
    async def chat_async(...) -> LLMResponse: ...
    def chat_stream_async(...) -> AsyncIterator[StreamChunk]: ...
    async def aclose(self) -> None: ...
    async def __aenter__(self) -> AsyncLLM: ...
    async def __aexit__(self, ...) -> None: ...
```

- [ ] **步骤 1：增加重试与取消测试**

覆盖“首次 503、第二次成功”“产生首块后错误不重试”“调用方取消时 transport 收到取消”以及
`async with AsyncLLM(...)` 退出后客户端关闭。

- [ ] **步骤 2：实现异步退避与流式边界**

使用 `await asyncio.sleep()` 退避；只有产生任何公开 chunk 前才允许重试。捕获网络和协议错误
时复用 `ModelRequestError`，但显式排除 `CancelledError`。

- [ ] **步骤 3：运行模型测试**

```powershell
python -m pytest tests/test_llm.py tests/test_async_llm.py -v
```

预期：同步与异步全部通过，取消测试观察到 `CancelledError`。

- [ ] **步骤 4：提交**

```powershell
git add core/async_llm.py tests/test_async_llm.py
git commit -m "feat: stream asynchronous model responses"
```

### 任务 3：异步工具、deadline 与协作式取消

**接口：**

```python
class AsyncToolRegistry:
    def __init__(
        self,
        tools: Iterable[Tool | Callable[..., Any]] = (),
        *,
        authorization_policy: ToolAuthorizationPolicy | None = None,
        default_timeout: float | None = None,
    ) -> None: ...

    async def execute_async(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> ToolExecutionResult: ...
```

- [ ] **步骤 1：在 `tests/test_async_agent.py` 增加工具执行测试**

覆盖 async callable 成功、async callable timeout、调用方取消、同步 callable 通过
`asyncio.to_thread()` 兼容，以及 `0.5.0` 授权拒绝发生在任务创建前。

- [ ] **步骤 2：运行工具子集并确认失败**

```powershell
python -m pytest tests/test_async_agent.py -k "tool or timeout or cancel" -v
```

- [ ] **步骤 3：实现调度规则**

先完成查找、参数绑定和授权；async callable 直接 await，sync callable 使用
`asyncio.to_thread()`。配置 timeout 时使用 `asyncio.timeout()`；timeout 返回
`ToolExecutionResult(error_code="tool_timeout")`，调用方取消原样传播。

- [ ] **步骤 4：记录同步工具限制**

测试必须证明取消等待后 Agent 不再消费结果，但不得断言后台线程已停止。文档明确同步工具
可能继续产生副作用，要求需要强取消的工具实现为 async callable 并响应取消。

- [ ] **步骤 5：提交**

```powershell
git add core/async_tools.py tests/test_async_agent.py
git commit -m "feat: execute asynchronous tools with deadlines"
```

### 任务 4：`AsyncAgent` 同步结果等价性

**接口：**

```python
class AsyncAgent:
    def __init__(
        self,
        llm: AsyncChatModel,
        tools: list[Tool | Callable[..., Any]] | None = None,
        ...,
        tool_authorization_policy: ToolAuthorizationPolicy | None = None,
        default_tool_timeout: float | None = None,
    ) -> None: ...

    async def run_async(
        self,
        user_input: str,
        *,
        memory_query: MemoryQuery | None = None,
    ) -> AgentResult: ...

    def run_stream_async(...) -> AsyncIterator[StreamEvent]: ...
```

- [ ] **步骤 1：增加异步 Agent 行为测试**

覆盖直接回答、两次工具调用、多个流式工具按 index 执行、timeout 后模型恢复、取消不写入会话、
成功原子写回和同一实例两个并发运行不共享 trace/messages。

- [ ] **步骤 2：明确长期记忆边界**

`0.6.0` 允许现有内存型 `LongTermMemoryStore` 显式检索，但文档标明同步 store 会阻塞 event loop；
Chroma 异步适配不在本版范围。不得悄悄使用线程包装外部存储。

- [ ] **步骤 3：实现两个独立异步循环**

保持与现有 Agent 相同的停止原因、usage、trace、上下文预算和成功写回规则。只共享无状态 helper，
不得通过收集全部 stream 来伪造非流式路径。

- [ ] **步骤 4：运行异步 Agent 测试**

```powershell
python -m pytest tests/test_async_agent.py -v
```

预期：全部通过。

- [ ] **步骤 5：运行核心回归测试**

```powershell
python -m pytest tests/test_agent.py tests/test_tools.py tests/test_async_agent.py -v
```

预期：同步行为无回归。

- [ ] **步骤 6：提交**

```powershell
git add core/async_agent.py tests/test_async_agent.py
git commit -m "feat: add isolated asynchronous agent runs"
```

### 任务 5：导出、示例和 0.6.0 发布

**文件：** `core/__init__.py`、`demo/reasoning_async.py`、`README.md`、`PLAN.md`、
`ROADMAP.md`、`CHANGELOG.md`、`pyproject.toml`、现有契约测试。

- [ ] **步骤 1：更新现有契约测试并确认失败**

要求导出 `AsyncChatModel`、`AsyncStreamingChatModel`、`AsyncLLM`、`AsyncToolRegistry`、
`AsyncAgent`；版本为 `0.6.0`；README 必须出现同步工具取消限制。

- [ ] **步骤 2：实现离线可检查的异步 Demo**

Demo 仍从 `.env` 读取真实模型配置，但入口必须使用 `asyncio.run(main())` 和
`async with AsyncLLM(...)`，并展示 async tool timeout 配置。

- [ ] **步骤 3：更新文档和版本**

ROADMAP 删除异步模型、Agent 和工具 timeout/cancel 已完成项，保留异步 Debate、异步长期记忆
和编排。CHANGELOG 不声称能够杀死同步线程工具。

- [ ] **步骤 4：运行一次完整发布验证**

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
git add core/__init__.py demo/reasoning_async.py README.md PLAN.md ROADMAP.md CHANGELOG.md pyproject.toml tests/test_docs_contract.py tests/test_package_metadata.py
git commit -m "feat: release asynchronous agents in 0.6.0"
```

## 验收标准

- `AsyncLLM` 的文本、工具、SSE、usage、重试和错误分类与同步客户端契约一致。
- 异步 HTTP 和 async callable 执行期间不阻塞 event loop。
- async 工具超过 deadline 返回 `tool_timeout` observation，模型可以继续推理。
- `CancelledError` 从模型、工具、Agent 和异步流原样传播。
- 取消、timeout、模型错误和工具异常具有不同可观察语义。
- 取消或放弃的异步流不写入会话记忆。
- 同一 `AsyncAgent` 的并发运行拥有独立 messages、trace、usage 和上下文预算。
- 同步 callable 的后台线程限制在 API 文档和 Demo 中明确说明。
- 现有全部同步测试保持通过，发行包能导入所有异步稳定符号。
