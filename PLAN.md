# General Mini Agent Framework 架构说明

## 项目目标

General Mini Agent Framework 提供结构清晰、边界明确的 Agent 基础组件。`0.7.0`
在稳定的同步、流式和异步执行之上，增加统一运行标识、事件 envelope 和版本化 JSON trace。

## 设计原则

1. **显式执行流程**：模型请求、工具调用、观察结果和最终答案通过结构化数据传递。
2. **实例状态隔离**：Agent 的工具、配置和执行状态不得通过进程级可变状态共享。
3. **小型模块边界**：模型、工具、执行器和实验模块分别维护。
4. **兼容标准协议**：模型层使用 OpenAI 兼容的 Chat Completions 和 function calling。
5. **失败可观察**：停止原因、工具错误和模型请求错误必须可定位且不得泄露密钥。
6. **行为优先于抽象**：只有出现真实复用需求时才增加新的协议和编排层。

## 0.7.0 稳定边界

`0.7.0` 包含并保持 `0.6.0` 的全部同步、流式和异步契约。

### `core/events.py`

负责运行上下文与事件 envelope：

- `RunContext` 持有唯一 `run_id` 和父运行关系
- `RunEvent` 统一事件 envelope，包含序号、时间戳和耗时
- `EventSink` 协议定义事件 sink 接口
- `EventCollector` 内存收集器，线程安全，支持不可变快照
- `RunEventEmitter` 事件发射器，管理序号和时钟，支持父子关系

事件层不拥有业务状态，只在状态变化边界发出事件。序号从 1 严格递增，耗时来自
monotonic clock。sink 异常原样传播，不转换为模型错误。

### `core/trace_json.py`

负责版本化 JSON trace 导出和导入：

- `TraceDocument` 版本化 trace 文档，`schema_version` 固定为 1
- `trace_to_json()` 导出为 JSON 字符串，确定性序列化
- `trace_from_json()` 从 JSON 字符串导入，严格校验
- `export_trace_json()` 导出到文件，UTF-8 编码

JSON 使用 `ensure_ascii=False`、`sort_keys=True`、`allow_nan=False`。导入只接受
`schema_version == 1`，拒绝非法结构。模型错误已脱敏，不包含认证头或 API Key。

### 继承自 0.6.0 的模块

`0.5.0` 包含并保持 `0.4.1` 的全部模型、工具、Agent、上下文和记忆契约。

### `core/context.py`

负责构造发送给模型的受限上下文视图：

- `TokenCounter` 允许替换默认近似估算器
- `TokenBudgetContext` 要求显式配置上下文窗口和输出预留
- 系统提示词、当前轮次和上一完整轮次不可被普通裁剪移除
- 对话轮次以及 assistant tool call 与 tool result 不会被拆分
- 每次模型请求都重新计算消息和工具 Schema
- `SummarizingContext` 使用调用方显式提供的摘要函数，失败时回退到确定性裁剪

上下文策略不修改 Agent 工作消息或会话存储。默认估算器不绑定模型厂商，也不宣称
与服务商 tokenizer 精确一致。

### `core/llm.py`

负责模型服务通信和协议转换：

- 配置模型地址、密钥、模型名称、超时和重试
- 发送同步 Chat Completions 请求
- 解析 OpenAI 兼容 SSE 流、usage-only payload 和多个工具调用片段
- 解析文本、工具调用和 Token 用量
- 将请求和流式协议错误转换为脱敏的 `ModelRequestError`

模型客户端不执行工具，也不管理 Agent 状态。`ChatModel` 保持同步调用契约，
`StreamingChatModel` 额外定义 `chat_stream()`。

### `core/tools.py`

负责 Python 函数与模型工具协议之间的转换：

- 使用 `@tool` 附加工具元数据
- 根据函数签名生成 JSON Schema
- 通过 `ToolRegistry` 提供实例级注册和查询
- 校验参数并返回结构化工具执行结果
- 结构化结果保留合法 JSON 值，确定性序列化为 `content`
- 授权策略在参数绑定后、工具执行前完成检查

`ToolExecutionResult.value` 保留合法 JSON 值（`dict`、`list`、`int`、`float`、
`bool`、`None`），`content` 使用紧凑确定性 JSON。字符串结果保持原样。
非法 JSON 值返回 `serialization_failed`。

`ToolAuthorizationPolicy` 协议定义 `authorize(request)` 方法。策略拒绝返回
`permission_denied`，策略异常返回 `authorization_error`，两者均为 fail-closed。
未知工具和无效参数不触发授权检查。

工具模块不决定调用时机，不使用进程级可变注册表。

### `core/agent.py`

负责单 Agent 同步和流式执行循环：

```text
构建请求上下文
  -> 请求模型
  -> 执行工具或返回最终答案
  -> 记录结构化轨迹
  -> 返回 AgentResult
```

`Agent.run()` 保留 `0.1.0` 同步控制循环；`Agent.run_stream()` 使用独立流式控制循环。
两条路径只共享工具注册执行、usage 累计、trace 和 hook 等有边界的 helper，不互相重写。

流式路径稳定支持七种 `StreamEvent`、五种停止原因、按 index 聚合的多工具调用、
非法参数修正、协议错误终止和每次请求一次的 usage 累计。

`0.3.0` 增加 `context_budget_exceeded` 停止原因。配置 `context_policy` 后，同步和流式
循环都在每次模型请求前生成预算视图。配置可写 `ConversationMemory` 后，只有成功完成
才原子写入用户输入和最终回复；其他终态和未完整消费的流均不写入。

### `core/memory.py`

`ConversationMemory` 定义快照读取、批量追加和清空契约。`InMemoryConversation` 对输入与
输出执行深复制，先校验整个批次再写入，并保持实例状态隔离。上下文裁剪属于
`core/context.py`，不会破坏存储中的完整会话历史。

### `core/long_term_memory.py`

定义稳定的 `MemoryNamespace`、`MemoryRecord`、`MemoryQuery` 和 `LongTermMemoryStore`
契约。默认读写使用 `user_id + conversation_id + agent_id` 完整命名空间，宽作用域只允许
显式查询和清理，更新与删除始终要求记录 ID 和完整归属命名空间。

`InMemoryLongTermStore` 提供确定性的离线实现；`ChromaMemoryStore` 延迟加载可选依赖，
并负责 Embedding、索引和持久化。Agent 只在调用方传入 `memory_query` 时检索一次，不会
自动写入。检索失败在模型访问前映射为 `memory_error`，检索文本作为有界历史参考数据，
不能替代系统规则。

### `core/debate.py`

负责多 Agent 同步和流式协作：

- 参与者按配置顺序完成每一轮，Judge 与普通参与者分离
- `max_rounds` 限制真实参与轮次，显式回调只在完整轮次后判断收敛
- 收敛或轮次耗尽后只调用一次 Judge
- 每次运行创建独立上下文、轮次记录和 usage 统计
- 非 `completed` 角色结果在确定边界停止后续角色
- 同步和流式路径保持相同的角色顺序、收敛转换和停止语义

`Debate` 不直接调用模型客户端或执行工具，也不自动访问长期记忆。`0.4.1` 不提供并行、
投票、动态角色、异步接口或通用工作流图。

## 实验性模块

以下能力保留用于实验，不属于 `0.4.1` 稳定 API：

- `core/memory.py` 中的 `SlidingWindowMemory` 和 ChromaDB `LongTermMemory`
- `core/trace.py`：HTML 轨迹渲染

实验模块可以修改接口和行为。稳定化顺序见 [ROADMAP.md](ROADMAP.md)。

## 公共接口

`core/__init__.py` 中的 `0.7.0` 稳定导出为：

- `ChatModel`、`StreamingChatModel`、`LLM`、`LLMConfig`、`LLMResponse`、
  `ModelRequestError`、`ToolCallDelta`、`StreamChunk`
- `tool`、`Tool`、`ToolRegistry`、`ToolExecutionResult`、`JSONValue`、
  `ToolAuthorizationRequest`、`ToolAuthorizationDecision`、`ToolAuthorizationPolicy`
- `Agent`、`AgentConfig`、`AgentResult`、`AgentStopReason`、`TraceEvent`、`StreamEvent`
- `TokenCounter`、`ApproximateTokenCounter`、`ContextPolicy`、`TokenBudgetContext`、
  `SummarizingContext`、`ContextBudgetExceeded`
- `ConversationMemory`、`InMemoryConversation`
- `MemoryNamespace`、`MemoryRecord`、`MemoryQuery`、`LongTermMemoryStore`
- `InMemoryLongTermStore`、`ChromaMemoryStore`、`MemoryStoreError`、`MemoryRecordNotFound`
- `Debate`、`DebateConfig`、`DebateRole`、`DebateRound`、`DebateTurn`、`DebateResult`
- `DebateStopReason`、`DebateStreamEvent`、`ConvergenceCheck`、`create_debate`
- `RunContext`、`RunEvent`、`EventSink`、`EventCollector`、`RunEventEmitter`
- `TraceDocument`、`trace_to_json`、`trace_from_json`、`export_trace_json`

`SlidingWindowMemory` 和 `LongTermMemory` 仅为兼容现有调用而继续导出，不构成稳定 API。

## 错误处理

- 认证失败和不可重试 HTTP 错误直接转换为脱敏模型错误。
- 超时、连接错误和临时服务端错误执行有限重试。
- 未知工具、无效参数和工具异常写入结构化轨迹，使模型可以修正或结束。
- 达到最大迭代次数时返回明确的 `stop_reason`。
- 受保护上下文无法满足预算时在模型请求前返回 `context_budget_exceeded`。
- 长期记忆检索失败时在模型请求前返回脱敏的 `memory_error`。
- 多 Agent 参与者或 Judge 非正常结束时返回对应的 Debate 停止原因并停止后续角色。
- 摘要失败回退到确定性裁剪，不改变原始会话历史。
- 可选依赖在首次使用实验组件时延迟加载。

## 测试策略

默认测试使用脚本化模型响应，不访问网络或真实模型服务。稳定模块至少覆盖正常路径、
无效输入、错误分类、状态隔离和停止条件。实验模块的测试只用于防止已知回归。

上下文与写回测试额外覆盖原子工具边界、受保护轮次、流式中断、请求级重算和状态隔离。
长期记忆测试覆盖命名空间、显式宽作用域、精确过滤、适配器边界和只读 Agent 检索。
多 Agent 测试覆盖多轮、收敛、Judge 分离、角色失败、同步/流式一致性和重复运行隔离。
真实模型验证不属于默认 CI；运行 Demo 前需要从 `.env.example` 创建 `.env` 并配置有效密钥。
