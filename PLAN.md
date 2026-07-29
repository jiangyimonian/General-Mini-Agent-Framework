# General Mini Agent Framework 架构说明

## 项目目标

General Mini Agent Framework 提供结构清晰、边界明确的 Agent 基础组件。`1.0.0`
删除 `core` 命名空间，冻结公共 API，仅保留 `general_mini_agent` 作为稳定入口。

## 设计原则

1. **显式执行流程**：模型请求、工具调用、观察结果和最终答案通过结构化数据传递。
2. **实例状态隔离**：Agent 的工具、配置和执行状态不得通过进程级可变状态共享。
3. **小型模块边界**：模型、工具、执行器和实验模块分别维护。
4. **兼容标准协议**：模型层使用 OpenAI 兼容的 Chat Completions 和 function calling。
5. **失败可观察**：停止原因、工具错误和模型请求错误必须可定位且不得泄露密钥。
6. **行为优先于抽象**：只有出现真实复用需求时才增加新的协议和编排层。

## 1.0.0 稳定边界

`1.0.0` 包含并保持 `0.9.0` 的全部同步、流式、异步、事件、trace 和工作流契约。

### `general_mini_agent/__init__.py`

唯一稳定公共 API 入口，导出所有公共组件。

### `general_mini_agent/providers.py`

负责模型能力适配：

- `ProviderCapabilities` 自动检测模型服务商（OpenAI、DeepSeek、Claude 等）
- 适配工具调用的 JSON Schema 差异
- 适配流式响应的 chunk 结构差异
- 提供统一的工具调用和响应接口

### `general_mini_agent/config.py`

负责统一配置：

- `FrameworkConfig` 框架级配置入口
- 日志级别、安全日志开关等全局配置
- 配置验证和默认值

### `general_mini_agent/logging.py`

负责安全日志：

- 自动脱敏 API Key、Authorization header 等敏感信息
- 提供 `get_logger()` 工厂函数
- 兼容标准 logging 模块

### `general_mini_agent/events.py`

负责运行上下文与事件 envelope：

- `RunContext` 持有唯一 `run_id` 和父运行关系
- `RunEvent` 统一事件 envelope，包含序号、时间戳和耗时
- `EventSink` 协议定义事件 sink 接口
- `EventCollector` 内存收集器，线程安全，支持不可变快照
- `RunEventEmitter` 事件发射器，管理序号和时钟，支持父子关系

### `general_mini_agent/workflow.py`

负责可组合的工作流节点：

- `WorkflowNode` 协议定义 `run(value, run_context, emitter)` 异步方法
- `Workflow` 工作流入口，持有根节点和可选事件 sink
- `NodeResult` 不可变节点结果，包含 value、run_id 和可选 error
- `SequenceNode` 串行节点，依次执行子节点，传递前一节点输出
- `ParallelNode` 并行节点，有限并发执行，结果按声明顺序排列
- `ConditionalNode` 条件节点，根据 predicate 选择分支

### `general_mini_agent/workflow_adapters.py`

负责 Agent 和 Debate 到工作流节点的适配：

- `AgentNode` 包装同步 `Agent`，要求字符串输入
- `AsyncAgentNode` 包装 `AsyncAgent`，要求字符串输入
- `DebateNode` 包装 `Debate`，要求字符串输入

### `general_mini_agent/trace_json.py`

负责版本化 JSON trace 导出和导入：

- `TraceDocument` 版本化 trace 文档，`schema_version` 固定为 1
- `trace_to_json()` 导出为 JSON 字符串，确定性序列化
- `trace_from_json()` 从 JSON 字符串导入，严格校验
- `export_trace_json()` 导出到文件，UTF-8 编码

### `general_mini_agent/context.py`

负责构造发送给模型的受限上下文视图：

- `TokenCounter` 允许替换默认近似估算器
- `TokenBudgetContext` 要求显式配置上下文窗口和输出预留
- 系统提示词、当前轮次和上一完整轮次不可被普通裁剪移除

### `general_mini_agent/llm.py`

负责模型服务通信和协议转换：

- 配置模型地址、密钥、模型名称、超时和重试
- 发送同步 Chat Completions 请求
- 解析 OpenAI 兼容 SSE 流、usage-only payload 和多个工具调用片段

### `general_mini_agent/tools.py`

负责 Python 函数与模型工具协议之间的转换：

- 使用 `@tool` 附加工具元数据
- 根据函数签名生成 JSON Schema
- 通过 `ToolRegistry` 提供实例级注册和查询

### `general_mini_agent/agent.py`

负责单 Agent 同步和流式执行循环：

- `Agent.run()` 同步控制循环
- `Agent.run_stream()` 流式事件生成器

### `general_mini_agent/memory.py`

`ConversationMemory` 定义快照读取、批量追加和清空契约。

### `general_mini_agent/long_term_memory.py`

定义稳定的长期记忆契约：

- `MemoryNamespace`、`MemoryRecord`、`MemoryQuery`
- `LongTermMemoryStore` 协议
- `InMemoryLongTermStore` 离线实现
- `ChromaMemoryStore` ChromaDB 持久化

### `general_mini_agent/debate.py`

负责多 Agent 同步和流式协作：

- 参与者按配置顺序完成每一轮
- Judge 与普通参与者分离
- `max_rounds` 限制真实参与轮次

## 实验性模块

以下能力保留用于实验，不属于稳定 API：

- `SlidingWindowMemory` 和 ChromaDB `LongTermMemory`

## 公共接口

`general_mini_agent/__init__.py` 导出：

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
- `Workflow`、`WorkflowNode`、`WorkflowResult`、`NodeResult`、`WorkflowStopReason`
- `SequenceNode`、`ParallelNode`、`ParallelErrorPolicy`、`ConditionalNode`
- `AgentNode`、`AsyncAgentNode`、`DebateNode`

## 错误处理

- 认证失败和不可重试 HTTP 错误直接转换为脱敏模型错误。
- 超时、连接错误和临时服务端错误执行有限重试。
- 未知工具、无效参数和工具异常写入结构化轨迹。
- 达到最大迭代次数时返回明确的 `stop_reason`。
- 受保护上下文无法满足预算时在模型请求前返回 `context_budget_exceeded`。
- 长期记忆检索失败时在模型请求前返回脱敏的 `memory_error`。

## 测试策略

默认测试使用脚本化模型响应，不访问网络或真实模型服务。稳定模块至少覆盖正常路径、
无效输入、错误分类、状态隔离和停止条件。