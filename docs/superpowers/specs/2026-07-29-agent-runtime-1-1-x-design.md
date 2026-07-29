# General Mini Agent Framework 1.1.x Agent 产品化设计

## 状态

本设计于 2026-07-29 经逐节确认。技术方案采用“统一回合协议，保留同步、流式和异步执行器”。下一份实施计划只覆盖 `1.1.0`，后续 `1.1.x` 版本分别设计、实施和验收。

## 背景

项目当前已经提供模型调用、工具注册、同步与异步 Agent、流式输出、记忆、上下文策略、事件、工作流和轨迹导出，但这些能力尚未形成一个可供 CLI 稳定复用的 Agent Runtime。

当前最关键的问题不是缺少 CLI，而是 Agent 内部执行协议不够稳定：

- 同步、流式和异步路径分别维护循环，边界行为可能漂移；
- 同步路径在一轮多个工具调用时，会把一条 assistant 回合拆成多条消息并与 tool result 交错；
- 非流式路径没有完整使用 `finish_reason`，截断响应可能被视为成功；
- 默认提示词同时要求文本 ReAct 格式和原生 `tool_calls`，两套协议互相干扰；
- 空响应通过伪造 assistant 内容继续，可能掩盖模型协议错误；
- 现有脚本模型大多宽松接受消息，无法模拟真实 API 对工具消息配对的严格约束；
- 文档和 CI 中仍有已经删除的 `core` 命名空间引用。

本设计参考 `D:\github\learn-claude-code` 的 `s01_agent_loop` 和 `s02_tool_use`：模型决定是否调用工具，Harness 完整记录模型回合、执行工具并反馈结果，直到模型不再调用工具。第一阶段保留这一核心循环，不提前引入 Claude Code 的复杂状态机、并行调度或上下文压缩。

## 版本路线

所有产品化工作在 `1.1.x` 系列内完成：

| 版本 | 目标 | 可交付结果 |
|---|---|---|
| `1.1.0` | 稳定 Agent Harness | 自定义模型和工具可以稳定完成真实工具循环 |
| `1.1.1` | 项目工具集 | Python 调用方可以组装最小 Coding Agent |
| `1.1.2` | 权限与安全边界 | 上层界面可以安全驱动写文件和命令工具 |
| `1.1.3` | 即装即用 CLI | 用户安装并配置 API 后可在项目目录运行 `gmaf` |
| `1.1.4` | 长任务与会话能力 | CLI 支持恢复、压缩、计划和轨迹输出 |

这些版本号被项目用作连续产品化里程碑。虽然 SemVer 通常把 `1.1.1` 视为仅包含兼容修复的补丁版本，本项目明确允许 `1.1.x` 增加向后兼容能力。整个 `1.1.x` 系列不得删除公开 API；破坏性调整留到未来 `2.0.0`。

## 目标

### `1.1.x` 总体目标

- 从“可嵌入的框架组件”演进为“安装后配置 API 即可使用的项目 Agent”；
- 让 CLI、权限、项目工具和会话能力建立在同一套 Agent 协议上；
- 保持模型传输、工具执行、授权交互和用户界面之间的职责边界；
- 默认支持 OpenAI-compatible API，但不把 Agent Runtime 绑定到具体供应商；
- 每个版本都可独立安装、离线测试和回归验证。

### `1.1.0` 目标

- 建立同步、流式和异步路径共同遵守的标准回合协议；
- 生成合法、完整且顺序确定的 assistant/tool 消息链；
- 统一终止状态、错误分类、usage 和迭代计数语义；
- 保证单次运行及并发运行之间的消息、工具、trace 和上下文隔离；
- 使用严格离线模型替身发现真实 API 会拒绝的协议错误；
- 保持现有公共入口兼容，并修复文档、CI 和命名空间契约。

## 非目标

`1.1.0` 不包含：

- 内置文件、搜索、编辑或命令工具；
- CLI、交互式终端或项目配置文件；
- 工具并行执行；
- 新的权限确认界面；
- 自动上下文摘要或会话恢复；
- Provider 适配器的大规模重构；
- 后台任务、子 Agent 或工作树隔离；
- 重新设计 workflow、debate 或长期记忆。

这些能力分别属于后续 `1.1.x` 版本。`1.1.0` 不得以“为以后预留”为理由加入未被当前协议使用的抽象。

## 方案比较与决策

### 方案 A：直接修补三套循环

分别修复 `Agent.run()`、`Agent.run_stream()` 和 `AsyncAgent`。该方案改动少，但三套实现继续复制消息组装和终止判断，以后仍会漂移。

### 方案 B：统一回合协议，保留执行器

抽出无 I/O 的标准回合、消息组装和终止判断。同步、流式和异步执行器继续负责各自的 I/O，但消费同一协议。

### 方案 C：完整事件驱动 Runtime

把模型、工具、记忆、权限、重试和上下文全部重构成统一状态机。长期扩展性高，但超出第一版范围，回归风险也最大。

### 决策

采用方案 B。它保留教学版 Agent 循环的可读性，同时消除协议逻辑重复。方案 C 只有在 `1.1.x` 完成后、现有边界被实际需求证明不足时才重新评估。

## 设计原则

1. 原生工具调用是唯一流程协议，文本中的 `Action:` 或 `Final Answer:` 不参与循环控制。
2. 一次模型响应构成一条完整 assistant 回合，不因工具数量拆分。
3. 每个工具调用必须有且仅有一个对应结果，失败也必须返回结果。
4. 协议层只做纯数据转换，不访问网络、不执行工具、不读写记忆。
5. 执行器拥有本次运行状态；Agent 实例只持有配置和依赖。
6. 工具错误默认可恢复，模型协议错误和传输错误才终止运行。
7. canonical messages 是事实记录，context policy 只能生成请求视图。
8. 流式是传输方式，不应改变最终回合语义。
9. 第一版顺序执行工具，先保证确定性和协议正确性。
10. 文档只描述已经发布的能力，未完成版本保留在路线图和设计文档。

## 总体架构

```text
User Input
    |
    v
Agent / AsyncAgent lifecycle
    |
    +--> memory and context preparation
    |
    v
LLM / AsyncLLM transport
    |
    v
AssistantTurn
    |
    +--> classify terminal turn
    |
    +--> append one canonical assistant message
    |
    v
ToolRegistry / AsyncToolRegistry
    |
    v
ToolOutcome[]
    |
    +--> append one result per tool call
    +--> trace and public events
    |
    `--> next model iteration
```

模型层负责请求和解析；协议层负责规范化和消息关系；执行器负责循环与生命周期；工具注册表负责授权、校验和执行；记忆、事件和 trace 位于循环外围。

## 模块边界

建议形成以下结构：

```text
general_mini_agent/
├── agent.py              同步 Agent 公共入口和生命周期
├── async_agent.py        异步 Agent 公共入口和生命周期
├── agent_protocol.py     内部回合模型、消息组装和终止判断
├── llm.py                同步模型传输和响应解析
├── async_llm.py          异步模型传输和流解析
├── tools.py              同步工具注册、授权、校验和执行
├── async_tools.py        异步工具执行、超时和取消
├── context.py            请求上下文预算和安全裁剪
├── memory.py             对话记忆
└── events.py             运行事件
```

`agent_protocol.py` 是内部模块，不从包根目录导出。它不得导入具体 `LLM`、网络客户端、记忆存储或工具实现。允许依赖公共数据类型和标准库。

`AgentStopReason` 的规范定义迁移到 `agent_protocol.py`，`agent.py` 和包根目录继续按原路径导入并重新导出，保证调用方无需迁移。这一安排避免 `agent_protocol.py` 反向导入 `agent.py` 形成循环依赖。

## 标准回合模型

内部使用不可变数据对象表达完整模型回合：

```python
@dataclass(frozen=True)
class AssistantTurn:
    content: str | None
    tool_calls: tuple[ToolCall, ...]
    finish_reason: str | None
    usage: dict[str, int]


@dataclass(frozen=True)
class ToolOutcome:
    call: ToolCall
    result: ToolExecutionResult


@dataclass(frozen=True)
class TurnDecision:
    action: Literal["continue", "complete", "stop_error"]
    stop_reason: AgentStopReason | None = None
    error_code: str | None = None
    message: str | None = None
```

不可变对象防止消息、trace、hooks 和事件共享可变字典后互相污染。对外继续使用现有 `AgentResult`、trace 字典和流事件结构。

协议模块提供以下纯函数或等价接口：

```python
normalize_response(response: LLMResponse) -> AssistantTurn
append_assistant_turn(messages, turn) -> None
append_tool_outcomes(messages, outcomes) -> None
classify_turn(turn) -> TurnDecision
build_tool_trace(iteration, turn, outcomes) -> list[TraceEvent]
```

流式路径使用 `StreamingTurnAccumulator` 收集文本、工具增量、结束原因和 usage，结束后生成同一种 `AssistantTurn`。

## ToolCall 数据约定

框架需要同时保留原始参数和解析结果。`ToolCall` 扩展为兼容结构：

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] | None
    raw_arguments: str = ""
    argument_error: str | None = None
```

新增字段有默认值，现有按前三个字段构造的代码保持兼容。

同步响应类型同时向后兼容地增加结束原因：

```python
@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] | None
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    finish_reason: str = ""
```

字段放在已有默认字段之后，现有位置参数和关键字构造继续有效。内置 `LLM` 和 `AsyncLLM` 从 OpenAI-compatible `choices[0].finish_reason` 填充该字段；第三方 `ChatModel` 可以继续不提供结束原因。

`normalize_response()` 将空字符串结束原因规范化为 `None`，但不会把供应商返回的未知非空原因改写成 `stop`。

参数规则：

- 合法 JSON 对象同时保存原始字符串和解析字典；
- 空字符串规范化为原始 `{}` 和空字典；
- 合法 JSON 但顶层不是对象时标记 `invalid_arguments`；
- 非法 JSON 保留原始字符串，`arguments` 为 `None`；
- 参数错误不能丢失整个模型回合，也不能执行目标函数；
- 错误信息只包含必要上下文，不回显不受限的长参数。

## Canonical Message 协议

一次包含多个工具调用的模型响应必须记录为一条 assistant 消息：

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_1",
      "type": "function",
      "function": {"name": "first", "arguments": "{}"}
    },
    {
      "id": "call_2",
      "type": "function",
      "function": {"name": "second", "arguments": "{}"}
    }
  ]
}
```

工具执行后按原始调用顺序追加结果：

```text
assistant(call_1, call_2)
tool(call_1)
tool(call_2)
```

不得生成以下交错结构：

```text
assistant(call_1)
tool(call_1)
assistant(call_2)
tool(call_2)
```

协议约束：

- assistant 同时返回文本和工具调用时，两者都保留；
- 该文本不是最终答案，必须先完成工具回合；
- 每个工具调用 ID 必须唯一且非空；
- 每个工具调用都必须产生一个 tool message，工具失败也不例外；
- 工具消息不得脱离来源 assistant 回合；
- 参数写回消息时优先使用模型原始 JSON，不能因重新序列化改变失败现场；
- 框架不得伪造模型未返回的 assistant 内容。

## 核心循环

规范循环保持简单：

```python
for iteration in range(max_iterations):
    request_messages = prepare_request(canonical_messages)
    turn = call_model(request_messages)
    append_assistant_turn(canonical_messages, turn)

    decision = classify_turn(turn)
    if decision.action == "continue":
        outcomes = execute_tools_in_order(turn.tool_calls)
        append_tool_outcomes(canonical_messages, outcomes)
        continue

    if decision.action == "complete":
        return completed_result(turn)

    return stopped_result(decision)

return max_iterations_result()
```

一次模型请求算一次 iteration；一轮中工具数量不增加 iteration。达到上限后不额外请求模型生成总结。

## 终止判断

继续循环主要依据实际存在的完整工具调用，而不是单独依赖 `finish_reason`。

这里的“完整工具调用”指能够建立消息关系的 index、非空 ID 和非空名称已经齐全。参数 JSON 无效仍然构成一个可反馈错误的工具调用，不会执行目标函数；缺少调用身份则是模型协议错误。

| 模型结果 | 决策 | Stop reason |
|---|---|---|
| 存在完整 `tool_calls` | 执行工具并继续 | 无 |
| 无工具，`stop`，有文本 | 正常返回文本 | `completed` |
| 无工具，`length` | 终止，不提交记忆 | `incomplete` |
| 无工具，`content_filter` | 终止，不提交记忆 | `incomplete` |
| `tool_calls`，但没有调用 | 协议错误 | `model_error` |
| 无文本、无工具、`stop` | 空响应协议错误 | `model_error` |
| 未知的非空结束原因且无工具 | 保守终止 | `incomplete` |
| 缺失结束原因、无工具但有文本 | 兼容旧 `ChatModel`，正常返回 | `completed` |
| 缺失结束原因、无文本且无工具 | 空响应协议错误 | `model_error` |
| 模型传输失败 | 终止 | `model_error` |
| 达到循环上限 | 终止 | `max_iterations` |

保持现有 `AgentStopReason` 公共取值：

```python
Literal[
    "completed",
    "max_iterations",
    "model_error",
    "incomplete",
    "context_budget_exceeded",
    "memory_error",
]
```

更具体的原因写入 trace `error_code`，包括 `model_request_failed`、`stream_protocol_error`、`invalid_model_response`、`missing_tool_calls` 和 `empty_model_response`。

缺失结束原因的兼容分支只服务于没有该字段的旧 `ChatModel`。内置模型客户端必须保留服务端返回的结束原因，因此真实 API 的 `length` 或 `content_filter` 不会落入兼容完成分支。

## 工具执行协议

每个调用依次经过：

```text
参数解析
  -> 授权策略
  -> 工具查找
  -> 参数校验
  -> 执行
  -> 结果序列化
  -> ToolExecutionResult
```

以下工具错误均作为 tool result 反馈给模型，默认不终止 Agent：

- `unknown_tool`；
- `invalid_arguments`；
- `permission_denied`；
- `authorization_error`；
- `execution_failed`；
- `serialization_failed`；
- 异步工具超时。

若参数 JSON 无效，assistant 原始调用仍进入 canonical messages，但目标函数不执行。框架生成对应的 `invalid_arguments` 结果，让模型下一轮修正。

本版多工具顺序执行。前一个工具失败不阻止本轮其他调用，确保每个调用都有结果。并行执行要等 `1.1.1` 的工具风险和并发属性有明确模型后再单独设计。

## 同步执行路径

`Agent.run()` 负责：

1. 创建局部 messages、trace、usage、iteration 和 emitter；
2. 读取一次长期记忆并建立初始消息；
3. 每轮通过 context policy 创建请求视图；
4. 调用 `llm.chat()` 并规范化为 `AssistantTurn`；
5. 使用共享协议追加消息、判断终止或执行工具；
6. 正常完成后调用 final hook 并提交短期记忆；
7. 发出唯一终止事件并返回 `AgentResult`。

Agent 实例不保存某次调用的中间 messages、trace 或 usage。

## 同步流式路径

`Agent.run_stream()` 分两阶段处理一轮响应。

接收阶段：

- 文本 delta 立即产生现有文本流事件；
- 工具 delta 只进入累积器，不提前执行；
- usage delta 作为本请求累计快照处理；
- finish reason 记录为本轮元数据。

完成阶段：

- 累积器生成完整 `AssistantTurn`；
- 追加一条完整 assistant 消息；
- 执行全部工具并逐个发出工具事件；
- 追加完整 tool results 后进入下一轮。

第一版不实现“模型仍在生成时提前启动工具”。消费者提前关闭生成器时，不执行尚未开始的工具、不提交记忆，也不伪造 `done`。

## 异步执行路径

`AsyncAgent` 使用相同协议函数，但模型和工具调用使用异步 I/O。异步工具直接等待；同步工具继续由现有线程机制承载。多工具仍按顺序 `await`，不使用 `asyncio.gather()`。

取消继续传播 `CancelledError`：

- 不转换成普通成功结果；
- 不继续调用工具；
- 不提交记忆；
- 不发出正常完成事件；
- 无法真正停止的同步工具即使迟到返回，也不能写回已取消运行。

若当前异步流式接口已经公开，则必须满足相同协议；本版不为尚未公开的异步流式能力增加新公共入口。

## 三路径等价性

相同逻辑脚本在同步、同步流式和适用的异步路径中必须得到相同的：

- canonical assistant/tool 消息顺序；
- 工具执行顺序；
- 最终内容和 stop reason；
- iteration 数；
- usage 汇总；
- trace 语义；
- 记忆提交条件。

流式路径允许额外产生文本增量事件，但完整回合不得不同。

## 默认 System Prompt

默认提示词改为原生工具调用导向，不要求公开思维链或文本动作协议：

```text
你是一个能够使用工具完成任务的 AI 助手。

根据用户目标判断是否需要调用工具：
- 需要外部信息或执行操作时，使用提供的工具。
- 可以在一轮中调用多个互不依赖的工具。
- 必须根据工具返回结果继续处理，不要猜测工具结果。
- 工具失败时，分析错误并尝试修正，或说明无法继续的原因。
- 获得足够信息后，直接给出最终答案。
```

用户显式传入 `system_prompt` 时完全使用用户内容，不暗中追加默认规则。底层 Agent 不假设自己一定是 Coding Agent。

为兼容历史模型输出，最终展示文本暂时继续清理 `[FINAL]` 和 `Final Answer:` 前缀，但这些标记不参与流程判断。移除兼容逻辑属于未来破坏性版本。

## 消息所有权与上下文

每次运行维护两种消息：

```text
canonical_messages
    本次运行的完整协议事实记录

request_messages
    根据预算处理后实际发送给模型的副本
```

context policy 不得直接修改 canonical messages。裁剪的最小单位是逻辑消息组：

- 普通用户消息为一个组；
- 普通 assistant 回答为一个组；
- `assistant(tool_calls) + 全部 tool results` 是不可拆分组。

每次模型调用前执行：

```text
复制规范历史
  -> 检查工具组完整性
  -> 应用 context policy
  -> 再次验证协议
  -> 发送模型
```

若预算无法同时容纳 system prompt、当前用户目标和最近一个完整工具组，则返回 `context_budget_exceeded`，不得发送结构不完整的请求。

`1.1.0` 不生成自动摘要，只建立配对安全边界。摘要和自动压缩属于 `1.1.4`。

## 记忆语义

长期记忆只在首次模型调用前检索一次。没有显式 `MemoryQuery` 时不得访问长期存储。Agent 不自动把每次答案写入长期记忆。

短期对话记忆只在正常完成后提交：

```python
[
    {"role": "user", "content": original_user_input},
    {"role": "assistant", "content": final_answer},
]
```

以下情况不得提交：

- `max_iterations`；
- `model_error`；
- `incomplete`；
- `context_budget_exceeded`；
- `memory_error`；
- 流被提前关闭；
- 异步运行被取消；
- final hook 失败。

工具调用和工具结果属于本次 trace，不默认写入对话记忆。完整会话恢复由 `1.1.4` 的 Session Store 负责。

## Usage 与迭代计数

每次模型请求的 usage 累加到 `AgentResult.usage`：

- 非流式响应每个请求累加一次；
- 流式响应中的 usage 被视为同一请求的累计快照，使用最后一个有效值；
- 已确认 usage 后发生模型错误时保留该 usage；
- 工具执行不计入模型 token usage；
- 缺失字段不补造数据。

一次模型请求算一次 iteration。一轮中执行多个工具仍只算一个 iteration。达到上限后不再发起额外总结请求。

## 错误处理

### 模型传输错误

HTTP、网络和超时重试由模型层负责。重试耗尽后，Agent 返回 `model_error`，不在 Agent 循环内重复同一请求。错误信息不得包含 API Key、Authorization Header 或原始敏感响应正文。

### 模型协议错误

工具调用身份缺失或冲突、空响应、结束原因和内容严重不一致等情况返回 `model_error`，并在 trace 中记录明确错误码。协议错误不得伪装成工具错误。

### 工具错误

工具错误转换成结构化结果并反馈给模型。只有无法建立合法 assistant/tool 关系时才终止整个运行。

### Context 与 Memory 错误

上下文超限发生在模型请求前，不追加 assistant 消息。长期记忆读取失败时维持 fail-closed，返回 `memory_error`。成功运行后的记忆写入失败保留当前显式异常语义，不伪装成模型错误。

### Hook 错误

`on_tool_call` 在工具执行和 trace 建立后调用；`on_final` 只在准备正常完成时调用。Hook 收到的数据使用副本，不能修改内部协议记录。Hook 异常继续传播，且 final hook 失败时不提交记忆。

## Trace 与事件

现有 trace 字典和公开流事件保持兼容。每个工具 trace 至少包含：

- iteration；
- 工具调用 index；
- tool call ID；
- 工具名；
- 解析参数，失败时为 `None`；
- raw arguments；
- observation；
- error code。

事件约束：

- 一次完成的运行只有一个终止结果；
- 一个工具调用对应一个 observation；
- `on_final` 只对应 `completed`；
- 流式 `done` 是正常流的最后一个公开事件；
- 提前关闭的流不伪造 `done`；
- error 和 trace 不得泄露密钥。

本版不要求新增公开 `model_completed` 事件。若内部需要该边界，应保持私有，避免扩大公共 API。

## 测试设计

全部默认测试离线运行，不请求真实模型服务。

### 宽松脚本模型

保留现有脚本模型，用于直接回答、单工具、多轮工具、工具恢复、最大迭代和 usage 等行为测试。

### 严格协议模型

新增严格模型替身，每次请求都验证：

- 一轮工具调用只对应一条 assistant 消息；
- 每个 tool message 有来源调用；
- 每个工具调用都有结果；
- tool result 不早于 assistant 调用；
- 调用 ID 唯一；
- 上下文未拆散工具组；
- 工具 arguments 是 JSON 字符串。

该替身用于发现宽松 Mock 无法暴露、但真实 OpenAI-compatible API 会拒绝的消息结构。

### 流式脚本模型

覆盖：

- ID、名称和参数分散在多个 chunk；
- 多工具 chunk 交错到达并按 index 还原；
- 文本和工具调用同时存在；
- 有完整调用但 finish reason 缺失；
- 声称工具结束但没有调用；
- 工具 ID 或名称冲突；
- 参数 JSON 不完整；
- usage 累计快照；
- 消费者提前关闭。

### 行为矩阵

| 场景 | 预期 |
|---|---|
| 直接文本 | `completed`，不执行工具 |
| 单工具后回答 | 合法配对，执行一次 |
| 一轮多工具 | 一条 assistant，多条顺序结果 |
| 文本加工具 | 保存文本，执行工具，不提前完成 |
| 未知工具 | `unknown_tool`，模型可恢复 |
| 参数类型错误 | `invalid_arguments` |
| 非法 JSON 参数 | 不执行，反馈参数错误 |
| 工具异常 | `execution_failed`，Agent 可继续 |
| 权限拒绝 | `permission_denied`，不执行 |
| 结果不可序列化 | `serialization_failed` |
| `length` | `incomplete`，不写记忆 |
| `content_filter` | `incomplete`，不写记忆 |
| 空响应 | `model_error` |
| 声称工具调用但无调用 | `model_error` |
| 达到上限 | `max_iterations` |
| 模型请求失败 | 脱敏的 `model_error` |
| 上下文拆散工具组 | 请求前拒绝或保留完整组 |
| 流提前关闭 | 不执行后续工具，不写记忆 |
| 异步取消 | 传播取消，不写记忆 |
| 同实例连续运行 | 状态不串联 |
| 同异步实例并发运行 | 状态隔离 |

### 三路径契约测试

使用同一逻辑脚本驱动同步、同步流式和异步路径，比较规范消息、工具顺序、最终内容、stop reason、iterations、usage、trace 和记忆提交内容。

### 手工真实 API 冒烟

提供显式开关控制的手动冒烟测试或脚本：

```text
GMAF_RUN_LIVE_TESTS=1
  -> 创建 LLM
  -> 注册简单 calculator
  -> 完成一次真实工具循环
```

没有配置时自动跳过；限制 token；不记录密钥和完整请求头；初期只承诺一个 OpenAI-compatible 服务。它不属于默认 CI。

## `1.1.0` 文件变更边界

预计涉及：

- 新增 `general_mini_agent/agent_protocol.py`；
- 修改 `general_mini_agent/agent.py`；
- 修改 `general_mini_agent/async_agent.py`；
- 按需要修改 `general_mini_agent/llm.py` 和 `async_llm.py` 以保留原始工具参数；
- 修改 `general_mini_agent/context.py` 以保护工具消息组；
- 增加或调整 Agent、LLM、context 和 async tests；
- 修正 `.github/workflows/ci.yml`、README、`docs/RELEASING.md` 中的旧命名空间；
- 更新 `CHANGELOG.md`、`ROADMAP.md` 和版本元数据。

`workflow.py`、`debate.py`、长期记忆存储实现和 trace renderer 只有在契约测试证明受影响时才做最小适配，不进行无关重构。

## 公共兼容性

保持：

- `Agent(...)`、`run()` 和 `run_stream()`；
- `AsyncAgent(...)` 现有入口；
- `AgentResult` 和 `AgentConfig`；
- `ToolRegistry`、`Tool` 和 `@tool`；
- 自定义 system prompt、hooks、memory 和 context policy；
- 现有包根目录稳定导出。

有意修正并记录到 changelog 的行为：

- 多工具消息改为标准协议；
- 空响应不再伪造消息重试；
- `length` 和 `content_filter` 不再报告成功；
- 默认提示词不再要求文本 ReAct；
- 工具参数解析失败可反馈给模型；
- trace 补齐调用 ID、index 和原始参数；
- 多工具始终按原始顺序执行。

## 后续版本边界

### `1.1.1` 项目工具集

新增 `read_file`、`list_files`/`glob_files`、`search_text`、`write_file`、`edit_file` 和 `run_command`，共享显式 `ToolRuntimeContext`。路径必须位于 workspace；读取和输出有上限；命令有超时；编辑要求旧文本唯一匹配；Windows 和 POSIX 行为均有测试。

`1.1.1` 不自动向任何 Agent 注册这些工具。只读工具可由调用方显式选用；`write_file`、`edit_file` 和 `run_command` 还要求构造工具上下文时显式开启 mutation/execute 能力，默认关闭。`1.1.2` 再把这些静态能力开关扩展成面向 CLI 的结构化确认流程。

### `1.1.2` 权限与安全

在授权协议中定义 `allow`、`deny` 和 `ask`。工具声明 `read`、`write`、`execute`、`external` 风险类别。权限请求以结构化事件交给上层，不在框架里直接调用 `input()`。安全依赖路径和能力边界，不依赖简单危险字符串黑名单。

### `1.1.3` CLI

增加 `gmaf` console script，提供 `--version`、`doctor`、`init`、单次任务和 `chat`。默认 workspace 为当前目录；配置顺序为命令行、项目配置、用户配置、`GMAF_*` 环境变量、非敏感默认值。CLI 复用已有 Agent、工具和权限，不重新实现循环。

### `1.1.4` 长任务与会话

增加会话保存与恢复、清空与压缩命令、自动上下文压缩、任务计划、结构化运行记录和 trace 导出。严格分离 Conversation Memory、Session Store 和 Trace Store，任何存储都不得写入 API Key。

## `1.1.0` 验收标准

1. 同步、流式和异步路径通过统一协议矩阵；
2. 多工具回合使用一条 assistant 消息和完整结果集合；
3. 非正常结束不写记忆、不报告 `completed`；
4. 空响应和协议异常产生明确、脱敏错误；
5. 上下文处理不拆散 assistant/tool 消息组；
6. 当前公开入口没有未说明的破坏性变更；
7. 默认离线测试全部通过；
8. 源码、demo 和 tests 可以完成字节码编译；
9. 包能够构建并在干净环境安装；
10. README、CI 和发布文档不再引用已删除的 `core` 包；
11. 完成人工真实 API 工具循环，未执行时必须在发布记录中明确说明；
12. `CHANGELOG.md` 记录多工具、空响应、截断响应和默认提示词变化。

## 实施拆分原则

下一份 implementation plan 只覆盖 `1.1.0`，按照测试驱动顺序拆分：先建立严格协议测试，再引入纯协议层，然后迁移同步、流式和异步执行器，最后处理上下文、文档、版本和发布验证。

`1.1.1` 至 `1.1.4` 每个版本都必须单独完成设计确认、实施计划和验收，不允许在 `1.1.0` 实施中提前混入。
