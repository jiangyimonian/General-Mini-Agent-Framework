# General Mini Agent Framework

General Mini Agent Framework 是一个轻量、可组合的 Python Agent 内核。`1.2.0`
在 `1.1.5` 的循环节点基础之上，增加了异步 Debate 能力。

框架直接使用 OpenAI 兼容的 Chat Completions API，不依赖 LangChain、LangGraph
等上层编排框架。

## 1.2.0 稳定能力

### 异步 Debate

提供异步多 Agent 协作能力：

- `AsyncDebate` - 异步执行角色顺序，支持非阻塞和流式输出
- `AsyncDebateRole` - 异步参与者配置
- `AsyncDebateConfig` - 异步 Debate 配置
- `AsyncDebateNode` - 工作流集成适配器
- 顺序模式下，后一个角色可读取同轮前序发言
- 每次调用独立，实例可复用，状态隔离

```python
from general_mini_agent import AsyncDebate, AsyncDebateRole, create_async_debate

# 方式 1：直接构造
debate = AsyncDebate(
    participants=[
        AsyncDebateRole("Solver", solver_agent, "提出解决方案。\n{role_context}"),
        AsyncDebateRole("Critic", critic_agent, "审查已有方案。\n{role_context}"),
    ],
    judge=AsyncDebateRole("Judge", judge_agent, "给出最终裁决。\n{role_context}"),
    config=AsyncDebateConfig(max_rounds=2),
)

# 方式 2：使用便捷工厂
debate = create_async_debate(solver_agent, critic_agent, judge_agent, max_rounds=2)

# 非阻塞运行
result = await debate.run_async("比较两个实现方案")
print(result.verdict)

# 流式运行
async for event in debate.run_stream_async("比较两个实现方案"):
    if event["type"] == "speaker":
        print(f"{event['role']} 正在发言...")
    elif event["type"] == "debate_done":
        print(f"最终结论: {event['verdict']}")
```

异步 Demo（离线无网络）：
```bash
python demo/async_debate_demo.py
```

## 1.1.5 稳定能力

### 循环节点

支持条件循环执行工作流节点：

- `LoopNode` - 重复执行 body 直到 should_stop 返回 True
- 支持最大迭代次数限制，防止无限循环
- 完整的事件追踪

```python
from general_mini_agent import LoopNode, Workflow, SequenceNode

# 创建循环节点：从 0 开始递增直到 >= 5
loop = LoopNode(
    body=IncrementNode(),  # 需要实现的自定义节点
    should_stop=lambda v: v >= 5,
    max_iterations=100,
)

workflow = Workflow(root=loop)
result = await workflow.run(0)  # 最终返回 5
```

## 1.1.4 稳定能力

### 会话管理

支持持久化会话历史，自动保存和加载：

- `gmaf chat --session my-chat` - 使用指定会话（自动保存）
- `gmaf sessions` - 列出所有会话
- `gmaf delete my-chat` - 删除会话
- 会话存储位置: `~/.config/gmaf/sessions/` (Windows: `%APPDATA%/gmaf/sessions/`)

```bash
# 使用会话聊天
gmaf chat --session my-chat

# 列出所有会话
gmaf sessions

# 删除会话
gmaf delete my-chat
```

### 自动上下文压缩

当对话历史过长时自动压缩以节省 Token：

- `SimpleTruncationStrategy` - 简单截断（保留系统消息和最近的消息）
- `SummarizationStrategy` - 摘要压缩（可自定义摘要生成）
- `AutoCompressingConversation` - 自动压缩的对话记忆
- `CompressingContextPolicy` - 可感知压缩的上下文策略

```python
from general_mini_agent import SimpleTruncationStrategy, AutoCompressingConversation

# 创建策略
strategy = SimpleTruncationStrategy(keep_recent=20)

# 使用自动压缩对话记忆
conv = AutoCompressingConversation(compression_strategy=strategy)
```

## 1.1.3 稳定能力

### 即装即用 CLI

提供 `gmaf` 命令行工具，支持：

- `gmaf --version` - 显示版本
- `gmaf doctor` - 检查环境和配置
- `gmaf init` - 初始化项目配置
- `gmaf run [任务]` - 运行单次任务
- `gmaf chat` - 交互式聊天

配置优先级：命令行 > 项目配置 (./.gmaf.toml) > 用户配置 (~/.config/gmaf/config.toml) > 环境变量 (GMAF_*) > 默认值

```bash
# 初始化项目
gmaf init

# 检查配置
gmaf doctor

# 交互式聊天
gmaf chat

# 运行单次任务
gmaf run "读取当前目录的文件列表"
```

## 1.1.2 稳定能力

### 权限与安全边界

提供可组合的权限策略框架，支持细粒度控制工具调用：

- `AllowAllPolicy`：允许所有调用
- `DenyAllPolicy`：拒绝所有调用
- `AskPolicy`：请求用户批准
- `RiskBasedPolicy`：基于风险类别（read/write/execute/external）配置
- `ToolAllowlistPolicy` / `ToolBlocklistPolicy`：工具名白名单/黑名单
- `CompositePolicy`：组合多个策略
- `ConditionalPolicy`：条件路由策略
- `ProjectToolBoundaryPolicy`：项目工具路径边界检查

```python
from general_mini_agent import (
    Agent,
    ToolRuntimeContext,
    create_project_tools,
    create_project_tool_policy,
    RiskBasedPolicy,
    PermissionPolicyToAuthorizationAdapter,
)

# 创建风险策略：允许读，拒绝写和执行
risk_policy = RiskBasedPolicy(read="allow", write="deny", execute="deny")

# 为项目工具创建完整策略（边界检查 + 风险策略）
policy = create_project_tool_policy(context, base_policy=risk_policy)

# 适配器桥接到旧授权协议
agent = Agent(
    llm=llm,
    tools=create_project_tools(context),
    tool_authorization_policy=PermissionPolicyToAuthorizationAdapter(
        policy,
        risk_category="read",
    ),
)
```

### 结构化权限请求事件

- `ToolPermissionRequest`：包含工具名、参数、风险类别、上下文
- `PermissionPolicyToAuthorizationAdapter` 支持可选的事件发射器
- 权限请求和响应事件可被外部监听器捕获和处理

## 1.1.1 稳定能力

### 项目工具集

提供安全的文件操作和命令执行工具，需显式配置权限：

- 读取工具：`read_file`、`list_files`、`glob_files`、`search_text`（默认启用）
- 写入工具：`write_file`、`edit_file`（需显式启用 `allow_write=True`）
- 命令工具：`run_command`（需显式启用 `allow_execute=True`）
- 所有路径限制在 `workspace` 目录内，防止越权访问
- 可配置文件大小限制、搜索结果上限、命令超时等

```python
from pathlib import Path
from general_mini_agent import Agent, ToolRuntimeContext, create_project_tools

# 创建工具上下文
context = ToolRuntimeContext(
    workspace=Path("./my_project"),
    allow_write=True,      # 启用写入
    allow_execute=True,    # 启用命令执行
)

# 为 Agent 注册项目工具
agent = Agent(
    llm=llm,
    tools=create_project_tools(context),
    memory=InMemoryConversation(),
)
```

## 1.1.0 稳定能力

### 原生工具调用协议

- 一次模型响应构成一条完整 assistant 回合，多工具调用不拆分消息
- 工具按原始声明顺序执行，每个调用都有对应结果
- 文本与工具调用可同时存在，文本保留但不提前终止
- 参数解析失败返回 `invalid_arguments`，模型可修正重试

### 三路径协议等价

同步、流式和异步路径产生相同的：
- canonical assistant/tool 消息顺序
- 工具执行顺序和结果
- 最终内容、stop reason 和 iteration 数
- usage 汇总和 trace 语义

### 终止状态语义

- `completed`：正常完成，写入对话记忆
- `max_iterations`：达到迭代上限，不写记忆
- `model_error`：模型传输或协议错误，脱敏返回
- `incomplete`：`length` 或 `content_filter` 截断，不写记忆
- `context_budget_exceeded`：上下文超限，请求前拒绝
- `memory_error`：长期记忆读取失败

### 命名空间

`general_mini_agent` 是唯一的稳定公共入口：

```python
from general_mini_agent import Agent, AsyncAgent, Workflow
```

### 模型能力适配器

`ProviderCapabilities` 自动检测模型服务商并适配差异：

- 检测 OpenAI、DeepSeek、Claude 等服务商
- 适配工具调用的 JSON Schema 差异
- 适配流式响应的 chunk 结构差异
- 提供统一的工具调用和响应接口

```python
from general_mini_agent import LLM, LLMConfig
from general_mini_agent.providers import ProviderCapabilities

llm = LLM(LLMConfig(
    api_key="<your-api-key>",
    model="deepseek-chat",
    base_url="https://api.deepseek.com/v1",
))
# 自动检测并适配 DeepSeek 的工具调用格式
```

### 统一配置（0.9.0 新增）

`FrameworkConfig` 提供统一的配置入口：

```python
from general_mini_agent.config import FrameworkConfig

config = FrameworkConfig(
    log_level="INFO",
    enable_safe_logging=True,  # 脱敏敏感信息
)
```

### 安全日志（0.9.0 新增）

安全日志自动脱敏 API Key、Authorization header 等敏感信息：

```python
from general_mini_agent.logging import get_logger

logger = get_logger(__name__)
logger.info("API call", extra={"api_key": "sk-xxx"})  # 自动脱敏
```

### 同步 API（继承自 0.5.0）

- OpenAI 兼容 Chat Completions 客户端
- Python 函数到 JSON Schema 的工具定义
- 单 Agent 同步工具调用与 ReAct 循环
- `LLM.chat_stream()` 的 OpenAI 兼容 SSE 解析
- `Agent.run_stream()` 的同步生成器事件接口
- 多个流式工具调用按 index 聚合并顺序执行
- 流式请求错误、协议错误、usage 和结束原因分类
- Agent 实例级工具隔离
- 结构化执行结果、轨迹和明确的停止原因
- 模型请求超时、有限重试和脱敏错误
- 请求级 Token 预算和可插拔计数器
- 按完整对话轮次和工具调用边界裁剪历史
- 同步与流式成功结果自动写入隔离的内存会话
- 可选的请求级历史摘要策略
- 按用户、会话和 Agent 隔离的长期记忆契约
- 确定性的内存存储和可选的 ChromaDB 持久化适配器
- `Agent.run()` 与 `Agent.run_stream()` 的显式检索和 `memory_error` 终态
- 有序多 Agent 参与者轮次和独立 Judge 最终裁决
- 真正生效的 `max_rounds` 与显式收敛回调
- `Debate.run()` 与 `Debate.run_stream()` 的运行隔离和确定性失败边界
- 结构化工具结果：合法 JSON 值保留在 `value`，确定性紧凑序列化为 `content`
- 实例级工具授权策略：fail-closed，拒绝或异常时不调用工具函数

### 异步 API（0.6.0 新增）

- `AsyncLLM` 异步模型客户端，支持 `async with` 生命周期
- `AsyncAgent.run_async()` 异步 ReAct 循环
- `AsyncAgent.run_stream_async()` 异步流式事件生成器
- `AsyncToolRegistry` 异步工具执行，支持 timeout 和取消传播
- 异步 callable 直接 await，同步 callable 通过 `asyncio.to_thread()` 执行
- 工具 timeout 返回 `tool_timeout` observation，模型可继续推理
- `CancelledError` 从模型、工具、Agent 原样传播
- 取消或未完整消费的流不写入会话记忆
- 同一 `AsyncAgent` 实例可并发运行，状态隔离

### 同步工具取消限制

同步 Python 函数通过 `asyncio.to_thread()` 在后台线程执行。取消只会停止等待，
**不会强制终止后台线程**。同步工具可能继续执行并产生副作用。需要响应取消的工具
应实现为 `async def` 并使用 `asyncio.sleep()` 或其他可取消的等待操作。

### 可观测运行（0.7.0 新增）

- `RunContext` 运行上下文，持有唯一 `run_id` 和父运行关系
- `RunEvent` 统一事件 envelope，包含序号、时间戳和耗时
- `EventCollector` 内存事件收集器，支持不可变快照
- `RunEventEmitter` 事件发射器，支持父子运行关系
- `TraceDocument` 版本化 trace 文档，`schema_version` 固定为 1
- `trace_to_json()` / `trace_from_json()` JSON 编解码，确定性导出
- `export_trace_json()` 导出到文件，UTF-8 编码
- sink 异常原样传播，不转换为模型错误
- 现有 `StreamEvent` 和 `DebateStreamEvent` 保持兼容
- 模型错误自动脱敏，不包含 Authorization header 或 API Key

### HTML 报告（0.7.1 新增）

- `trace_to_html()` / `export_trace_html()` TraceDocument 渲染为自包含 HTML
- `compare_traces_to_html()` 双运行对比报告
- 事件类型、run ID、停止原因、错误过滤
- 无外部资源，断网可用
- XSS 安全转义

### 离线 Demo

```bash
python demo/offline.py
```

输出：
- `output/offline-agent.json` / `.html` — 单 Agent 轨迹
- `output/offline-debate.json` / `.html` — Debate 轨迹

不读取 `.env`，不访问网络。

### 工作流节点（0.8.0 新增）

提供可组合、可取消、可观察的串行、有限并行和条件路由节点：

- `Workflow`：工作流入口，持有根节点和事件 sink
- `SequenceNode`：串行节点，依次执行子节点，传递前一节点输出
- `ParallelNode`：并行节点，并发执行子节点，结果按声明顺序排列
- `ConditionalNode`：条件节点，根据 predicate 选择分支

工作流示例：

```bash
python demo/workflow_demo.py
```

```python
from general_mini_agent import Workflow, SequenceNode, ParallelNode, ConditionalNode

# 并行生成两个候选
parallel = ParallelNode(
    [GenerateNode(), GenerateNode()],
    max_concurrency=2,
)

# 条件选择
conditional = ConditionalNode(
    predicate=lambda v: len(v) > 0,
    when_true=SelectBestNode(),
    when_false=NoCandidateNode(),
)

# 串行组合
workflow = Workflow(root=SequenceNode([parallel, conditional]))
result = await workflow.run("start")
```

工作流实例不保存运行结果，重复/并发运行完全隔离。并行节点有正整数并发上限。
不包含循环、持久化、队列或分布式执行。

## 项目结构

```text
general_mini_agent/
├── agent.py          # 单 Agent 执行循环
├── async_agent.py    # 异步单 Agent 执行循环
├── async_debate.py   # 异步多 Agent 协作
├── context.py        # Token 计数和请求上下文策略
├── llm.py            # OpenAI 兼容模型客户端
├── async_llm.py      # 异步模型客户端
├── tools.py          # 工具注册、Schema 和执行
├── async_tools.py    # 异步工具执行
├── tools_project.py  # 项目工具：文件操作与命令执行
├── memory.py         # 内存会话与旧长期记忆兼容接口
├── long_term_memory.py # 稳定的显式长期记忆
├── debate.py         # 稳定的多 Agent 协作
├── events.py         # 运行上下文与事件 envelope
├── trace_json.py     # 版本化 JSON trace 导出
├── trace.py          # HTML 报告渲染
├── workflow.py       # 工作流节点
├── workflow_adapters.py # Agent/Debate 适配器
├── providers.py      # 模型能力适配器
├── config.py         # 统一配置
├── logging.py        # 安全日志
demo/
├── reasoning.py      # 同步示例
├── reasoning_stream.py # 稳定流式示例
├── reasoning_async.py # 稳定异步示例
├── chat.py           # 0.3.0 上下文与会话记忆示例
├── long_term_memory.py # 0.3.1 持久化长期记忆示例
├── offline.py        # 离线 Demo（无网络）
├── workflow_demo.py  # 工作流 Demo
├── scripted_models.py # 脚本化模型
├── debate_demo.py    # 同步多 Agent Demo
├── async_debate_demo.py # 异步多 Agent Demo
└── export_demo.py
tests/                # 离线自动化测试
```

## 安装

环境要求：Python 3.12 或更高版本，以及一个 OpenAI Chat Completions 兼容模型服务。

安装运行依赖：

```bash
python -m pip install .
```

安装开发依赖：

```bash
python -m pip install ".[dev]"
```

运行 Demo 还需要：

```bash
python -m pip install ".[demo]"
```

长期记忆 Demo 需要可选的 ChromaDB：

```bash
python -m pip install ".[memory]"
```

从 `.env.example` 创建 `.env`，并配置模型服务：

```dotenv
DEEPSEEK_API_KEY=your-api-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_CONTEXT_WINDOW=65536
LLM_RESERVED_OUTPUT_TOKENS=4096
```

`LLM_CONTEXT_WINDOW` 必须按所用模型配置；框架不会根据模型名称猜测容量。Chat Demo
默认预留 `4096` Token 给模型输出。也可以直接构造 `LLMConfig` 接入其他 OpenAI 兼容服务。

## 快速开始

```python
from general_mini_agent import (
    Agent,
    InMemoryConversation,
    LLM,
    LLMConfig,
    TokenBudgetContext,
    tool,
)


@tool(description="计算两个整数的和")
def add(a: int, b: int) -> int:
    return a + b


agent = Agent(
    llm=LLM(LLMConfig(api_key="<your-api-key>", model="<your-model>")),
    tools=[add],
    memory=InMemoryConversation(),
    context_policy=TokenBudgetContext(
        context_window=65536,
        reserved_output_tokens=4096,
    ),
)
result = agent.run("计算 17 + 25")
print(result.content)
```

仓库中的稳定示例：

```bash
python demo/reasoning.py
python demo/reasoning_stream.py
python demo/reasoning_async.py
python demo/chat.py
python demo/long_term_memory.py
python demo/debate_demo.py
python demo/async_debate_demo.py
```

该示例需要 `.env` 中存在有效模型密钥，不属于默认离线测试。

## 稳定 API

`1.2.0` 的稳定公共入口由 `general_mini_agent` 包导出：

- 同步模型：`ChatModel`、`StreamingChatModel`、`LLM`、`LLMConfig`、`LLMResponse`、
  `ModelRequestError`、`ToolCallDelta`、`StreamChunk`
- 异步模型：`AsyncChatModel`、`AsyncStreamingChatModel`、`AsyncLLM`
- 工具：`tool`、`Tool`、`ToolRegistry`、`ToolExecutionResult`、`JSONValue`、
  `ToolAuthorizationRequest`、`ToolAuthorizationDecision`、`ToolAuthorizationPolicy`
- 项目工具：`ToolRuntimeContext`、`create_project_tools`
- 异步工具：`AsyncToolRegistry`
- 同步 Agent：`Agent`、`AgentConfig`、`AgentResult`、`AgentStopReason`、`TraceEvent`、`StreamEvent`
- 异步 Agent：`AsyncAgent`
- 上下文：`TokenCounter`、`ApproximateTokenCounter`、`ContextPolicy`、
  `TokenBudgetContext`、`SummarizingContext`、`ContextBudgetExceeded`
- 会话：`ConversationMemory`、`InMemoryConversation`
- 长期记忆：`MemoryNamespace`、`MemoryRecord`、`MemoryQuery`、`LongTermMemoryStore`、
  `InMemoryLongTermStore`、`ChromaMemoryStore`、`MemoryStoreError`、`MemoryRecordNotFound`
- 多 Agent：`Debate`、`DebateConfig`、`DebateRole`、`DebateRound`、`DebateTurn`、
  `DebateResult`、`DebateStopReason`、`DebateStreamEvent`、`create_debate`
- 异步多 Agent：`AsyncDebate`、`AsyncDebateConfig`、`AsyncDebateRole`、`create_async_debate`
- 工作流：`Workflow`、`WorkflowNode`、`NodeResult`、`WorkflowResult`、`WorkflowStopReason`、
  `SequenceNode`、`ParallelNode`、`ConditionalNode`、`LoopNode`
- 工作流适配器：`AgentNode`、`AsyncAgentNode`、`DebateNode`、`AsyncDebateNode`

`StreamEvent` 包含 `iteration_start`、`thought_chunk`、`tool_call`、`observation`、
`final_answer`、`model_error` 和 `done` 七种事件。`done.stop_reason` 为 `completed`、
`max_iterations`、`model_error`、`incomplete`、`context_budget_exceeded` 或 `memory_error`。

`TokenBudgetContext` 在每次模型请求前计算系统消息、对话、当前工具消息和工具 Schema。
它默认使用确定性的近似计数，不保证与服务商 tokenizer 完全一致；需要精确计数时可注入
自定义 `TokenCounter`。裁剪不会拆散完整轮次或工具调用链，并始终保护系统提示词、当前
轮次和上一完整轮次。受保护内容仍超限时，请求在访问模型前停止。

自定义计数器只需实现 `count()`：

```python
import json


class ConservativeCounter:
    def count(self, messages, *, tools=None):
        payload = {"messages": list(messages), "tools": list(tools or [])}
        characters = len(json.dumps(payload, ensure_ascii=False))
        return max(1, (characters + 2) // 3)


policy = TokenBudgetContext(
    context_window=65536,
    reserved_output_tokens=4096,
    token_counter=ConservativeCounter(),
)
```

`InMemoryConversation` 只在 Agent 成功完成后原子写入一组 `user + assistant` 消息。
模型错误、上下文超限、迭代耗尽、流式中断和不完整输出均不会写入历史。

### 显式长期记忆

长期记忆使用 `user_id + conversation_id + agent_id` 命名空间。写入与检索都由调用方显式
触发；Agent 不会自动写入长期记忆。默认检索仅匹配完整命名空间，跨会话或跨 Agent 的
读取必须显式选择更宽作用域。

```python
from general_mini_agent import Agent, InMemoryLongTermStore, MemoryNamespace, MemoryQuery

namespace = MemoryNamespace("user-1", "conversation-1", "assistant")
long_term_memory = InMemoryLongTermStore()
long_term_memory.store("用户偏好简洁的 Python 示例", namespace)

agent = Agent(llm=model, long_term_memory=long_term_memory)
result = agent.run(
    "给我一个示例",
    memory_query=MemoryQuery("Python 偏好", namespace),
)
```

检索结果按相关性顺序作为有界的 system 参考块加入当前请求，并明确标注为历史数据而非
系统指令。记录内容不会被截断；如果没有完整记录能放入 `max_context_tokens`，请求在访问
模型前以 `context_budget_exceeded` 停止。`ChromaMemoryStore` 负责 Embedding 和索引，
ChromaDB 仍是首次操作时才加载的可选依赖。

长期记忆不包含自动记忆选择、自动写入、异步存储、复杂元数据表达式、重排序或分数归一化。

`SlidingWindowMemory` 和 `LongTermMemory` 仅保留兼容导出，不属于稳定 API。
`general_mini_agent.trace` 仍属于实验性模块。`SummarizingContext` 必须由调用方
显式提供摘要函数，不会在后台复用主模型；摘要失败时回退到确定性裁剪。

**弃用说明**：`core` 命名空间在 0.9.0 仍可使用，但将在 1.0.0 删除。请迁移到
`general_mini_agent` 命名空间。详见 [docs/MIGRATING.md](docs/MIGRATING.md)。

### 结构化工具结果

工具函数返回字符串时，`content` 保持原样传递给模型。返回合法 JSON 值（`dict`、`list`、
`int`、`float`、`bool`、`None`）时，`ToolExecutionResult.value` 保留原始值，`content`
使用确定性紧凑 JSON 序列化：

```python
from general_mini_agent import ToolExecutionResult, tool

@tool
def fetch() -> dict:
    return {"items": [1, True, None], "status": "ok"}

# 执行后 result.content == '{"items":[1,true,null],"status":"ok"}'
# result.value == {"items": [1, True, None], "status": "ok"}
```

序列化使用 `json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))`。
非字符串键、`NaN`、`Infinity` 和不可序列化对象返回 `serialization_failed` 错误码，
不会退回 `repr()` 或暴露内存地址。

### 工具授权

`ToolAuthorizationPolicy` 协议在参数绑定成功后、工具函数执行前完成授权检查。
策略拒绝返回 `permission_denied`，策略异常返回 `authorization_error`，两者均为
fail-closed：工具函数不会被调用。

```python
from general_mini_agent import Agent, ToolAuthorizationDecision, ToolAuthorizationRequest

class AllowSafeOnly:
    def authorize(self, request: ToolAuthorizationRequest):
        if request.name == "safe_query":
            return ToolAuthorizationDecision(allowed=True)
        return ToolAuthorizationDecision(allowed=False, reason="unsafe")

agent = Agent(
    llm=model,
    tools=[safe_query, dangerous_action],
    tool_authorization_policy=AllowSafeOnly(),
)
```

授权策略属于 Agent 实例，不使用进程级全局注册表。未知工具和无效参数不会触发授权检查。

### 多 Agent 协作

`Debate` 接收有序参与者列表，并将 Judge 单独配置。参与者完成一轮后才检查调用方提供的
收敛回调；收敛或达到 `max_rounds` 后，Judge 只执行一次。每次调用都创建独立上下文，
重复使用同一个 `Debate` 实例不会混入上一次运行。

```python
from general_mini_agent import Debate, DebateConfig, DebateRole

debate = Debate(
    participants=[
        DebateRole("Solver", solver_agent, "提出解决方案。\n{role_context}"),
        DebateRole("Critic", critic_agent, "审查已有方案。\n{role_context}"),
    ],
    judge=DebateRole("Judge", judge_agent, "给出最终裁决。\n{role_context}"),
    config=DebateConfig(max_rounds=2),
)
result = debate.run("比较两个实现方案")
print(result.verdict)
```

参与者失败、Judge 失败和缺少 Judge 分别返回 `participant_error`、`judge_error` 和
`no_judge`。`Debate.run_stream()` 使用 Debate 级轮次、发言者、Agent 包装事件和单一
`debate_done` 终态，执行顺序与同步路径一致。

`0.5.0` 不包含并行参与者、投票、动态角色、异步 API 或通用工作流图。

## 多 Agent 与轨迹示例

多 Agent Demo 使用稳定接口；HTML 导出仍是实验性展示：

```bash
python demo/debate_demo.py
python demo/export_demo.py
python demo/export_demo.py debate
```

## 验证

默认验证全部离线运行，不需要真实 API Key：

```bash
python -m pytest tests -v
python -m compileall -q general_mini_agent demo tests
ruff check general_mini_agent tests demo
```

## 开发文档

- [PLAN.md](PLAN.md)：`0.4.1` 架构和稳定边界
- [ROADMAP.md](ROADMAP.md)：后续版本路线
