# General Mini Agent Framework

General Mini Agent Framework 是一个轻量、可组合的 Python Agent 内核。`1.9.0`
新增受控命令执行，为项目工具提供可移植的子进程守卫。

框架直接使用 OpenAI 兼容的 Chat Completions API，不依赖 LangChain、LangGraph
等上层编排框架。

## 1.9.0 稳定能力

### 受控命令执行

为项目工具的命令执行提供 Phase 1 子进程守卫：

- `SandboxConfig` - 沙箱配置（默认禁用，保持向后兼容）
- `CommandSandbox` - 受控命令执行器
- `SandboxResult` - 结构化执行结果
- 工作目录边界：拒绝将 `cwd` 设置到配置根目录之外
- 环境变量过滤：仅传递白名单内的环境变量
- 超时清理：超时后终止进程组或进程树
- 有界输出捕获：持续排空 stdout/stderr，但只保留配置上限内的内容
- fail-closed：请求当前后端不支持的网络隔离时，不启动命令

```python
from pathlib import Path
from general_mini_agent import (
    ToolRuntimeContext,
    create_project_tools,
    SandboxConfig,
)

# 创建带子进程守卫的工具上下文
context = ToolRuntimeContext(
    workspace=Path("./my_project"),
    allow_execute=True,
    sandbox_config=SandboxConfig(
        enabled=True,
        # Phase 1 不提供网络隔离；必须显式接受网络可用
        network_policy="allow",
        timeout_seconds=60.0,      # 60秒超时
        max_output_bytes=1024 * 1024,  # 1MB 输出上限
        env_allowlist=["PATH", "HOME"],  # 仅传递指定环境变量
    ),
)

# run_command 会自动使用受控子进程后端
tools = create_project_tools(context)
```

**平台支持**：

| 平台 | 执行机制 | 已实现的守卫 |
|------|----------|------|
| Linux | subprocess + process group | cwd、环境、超时、输出捕获 |
| Windows | subprocess + process group/taskkill | cwd、环境、超时、输出捕获 |
| macOS | subprocess + process group | cwd、环境、超时、输出捕获 |

**安全边界**：

- **授权 vs 执行守卫**：通过带授权策略的 `ToolRegistry` 调用时，授权检查先于命令执行
- **网络策略**：`network_policy="deny"` 在 Phase 1 中返回
  `network_isolation_unavailable`，不会降级执行
- **向后兼容**：`sandbox_config=None` 或 `enabled=False` 保持现有行为
- **非安全沙箱**：Phase 1 不限制命令访问工作目录外的文件，也不提供网络、CPU 或内存隔离；
  不应使用它运行不受信任的代码

## 1.4.0-1.8.0 稳定能力

- `1.8.0`：`RateLimitPolicy` 与 `RateLimiter` 提供同步、异步令牌桶限流和超时语义
- `1.7.0`：`WorkflowConfig`、`GraphFrozenError` 和受限动态节点扩展工作流能力
- `1.6.0`：`RetryPolicy` 与 `execute_with_retry()` 提供可注入时钟的显式异步重试
- `1.5.0`：延迟加载的 `AsyncChromaMemoryStore` 提供可选持久化异步记忆
- `1.4.0`：`AsyncLongTermMemoryStore` 与 `AsyncInMemoryLongTermStore` 提供异步长期记忆协议

具体变更、兼容性和设计约束见 [CHANGELOG.md](CHANGELOG.md)。

## 1.3.0 稳定能力

### 并行异步 Debate

在异步 Debate 基础上新增并行参与者模式：

- `participant_execution="parallel"` 显式启用并行回合
- 并行参与者只读取已完成轮次，不读取同轮其他参与者的回答
- 结果按声明顺序归档，确保确定性
- 流式事件复用：每个 `agent_event` 标识发起角色
- 完整的失败归集和取消传播

```python
from general_mini_agent import create_async_debate

# 创建并行辩论（显式启用并行模式）
debate = create_async_debate(
    solver_agent,
    critic_agent,
    judge_agent,
    max_rounds=2,
    participant_execution="parallel",  # 显式启用并行执行
)

result = await debate.run_async("分析两个方案")
print(result.verdict)
```

**并行模式行为说明：**
- 并行参与者不读取同轮其他参与者的回答
- Judge 接收所有参与者的完整回答
- `"sequential"` 模式（默认）保持同轮可见性：后一个角色可读取前序发言
- 升级从 `1.2.x` 保持兼容：默认行为不变

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

`FrameworkConfig.load()` 读取项目配置、用户配置和 `GMAF_*` 环境变量：

```python
from pathlib import Path

from general_mini_agent.config import FrameworkConfig

config = FrameworkConfig.load()
print(config.model, config.base_url, config.timeout)

# 显式参数优先级最高，可覆盖文件和环境变量
config = FrameworkConfig.load(
    model="deepseek-chat",
    project_config=Path(".gmaf.toml"),
)
```

配置优先级从高到低为：

1. `FrameworkConfig.load()` 的显式参数
2. 项目配置文件 `./.gmaf.toml`
3. 用户配置文件：Linux/macOS 为 `~/.config/gmaf/config.toml`，Windows 为 `%APPDATA%/gmaf/config.toml`
4. `GMAF_*` 环境变量
5. 内置默认值

项目配置文件示例（不要提交真实密钥）：

仓库同时提供不含密钥的 [`.gmaf.toml.example`](.gmaf.toml.example)，可以复制为
`.gmaf.toml` 后再填写本地配置。

```toml
# .gmaf.toml
api_key = "your-api-key"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
timeout = 60.0
max_retries = 2
provider = "openai-compatible"
# context_window = 65536
# reserved_output_tokens = 4096
```

也可以使用环境变量：

```bash
# Linux/macOS
export GMAF_API_KEY=your-api-key
export GMAF_BASE_URL=https://api.openai.com/v1
export GMAF_MODEL=gpt-4o-mini

# Windows PowerShell
$env:GMAF_API_KEY = "your-api-key"
$env:GMAF_BASE_URL = "https://api.openai.com/v1"
$env:GMAF_MODEL = "gpt-4o-mini"
```

CLI 用户可以运行 `gmaf init` 生成 `.gmaf.toml` 模板，再运行 `gmaf doctor -v`
检查配置。CLI 的 `run` 和 `chat` 会自动调用 `FrameworkConfig.load()`。

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
- `LoopNode`：循环节点，重复执行直到条件满足

**动态节点（1.7.0 新增）**：

```python
from general_mini_agent import Workflow, WorkflowConfig, SequenceNode

# 配置动态节点边界
config = WorkflowConfig(
    max_nodes=100,  # 最大节点数
    max_depth=10,   # 最大深度
)

workflow = Workflow(
    root=SequenceNode([...]),
    config=config,
)
result = await workflow.run("start")

# 动态添加节点（运行时请求）
# workflow.add_node(node, name, dynamic_state, emitter)
```

**设计约束**：
- 默认最大节点数：100（含静态节点）
- 默认最大深度：10 层
- 重复节点名称被拒绝
- 工作流完成或取消后图被冻结
- 两次运行不共享动态添加

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

上面的 `.env` 变量由 Demo 使用；CLI 和 `FrameworkConfig` 使用的是 `.gmaf.toml`
以及 `GMAF_*` 环境变量，两套配置名称不要混用。

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

`1.9.0` 的稳定公共入口由 `general_mini_agent` 包导出：

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
- 异步长期记忆：`AsyncLongTermMemoryStore`、`AsyncInMemoryLongTermStore`、`AsyncChromaMemoryStore`
- 重试策略：`RetryPolicy`、`execute_with_retry`
- 速率限制：`RateLimitPolicy`、`RateLimiter`
- 命令执行守卫：`SandboxConfig`、`SandboxResult`、`CommandSandbox`、
  `is_sandbox_available`、`get_platform_info`
- 多 Agent：`Debate`、`DebateConfig`、`DebateRole`、`DebateRound`、`DebateTurn`、
  `DebateResult`、`DebateStopReason`、`DebateStreamEvent`、`create_debate`
- 异步多 Agent：`AsyncDebate`、`AsyncDebateConfig`、`AsyncDebateRole`、`create_async_debate`
- 工作流：`Workflow`、`WorkflowConfig`、`WorkflowNode`、`NodeResult`、`WorkflowResult`、
  `WorkflowStopReason`、`SequenceNode`、`ParallelNode`、`ConditionalNode`、`LoopNode`、`GraphFrozenError`
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

**同步存储示例**：

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

**异步存储示例（1.4.0 新增）**：

```python
from general_mini_agent import AsyncAgent, AsyncInMemoryLongTermStore, MemoryNamespace, MemoryQuery

namespace = MemoryNamespace("user-1", "conversation-1", "assistant")
long_term_memory = AsyncInMemoryLongTermStore()
await long_term_memory.store("用户偏好简洁的 Python 示例", namespace)

agent = AsyncAgent(llm=async_model, long_term_memory=long_term_memory)
result = await agent.run_async(
    "给我一个示例",
    memory_query=MemoryQuery("Python 偏好", namespace),
)
```

`AsyncAgent` 同时支持同步和异步存储（向后兼容）。使用 `AsyncLongTermMemoryStore` 
时查询操作不会阻塞事件循环。

**异步 ChromaDB 示例（1.5.0 新增）**：

```python
from general_mini_agent import AsyncAgent, AsyncChromaMemoryStore, MemoryNamespace, MemoryQuery

# 使用持久化异步存储
long_term_memory = AsyncChromaMemoryStore(
    persist_dir="~/.agent_memory",
    collection_name="my_agent_memory",
)

namespace = MemoryNamespace("user-1", "conversation-1", "assistant")
await long_term_memory.store("用户偏好简洁的 Python 示例", namespace)

agent = AsyncAgent(llm=async_model, long_term_memory=long_term_memory)
result = await agent.run_async(
    "给我一个示例",
    memory_query=MemoryQuery("Python 偏好", namespace),
)
```

安装 ChromaDB 支持：`pip install ".[memory]"`

检索结果按相关性顺序作为有界的 system 参考块加入当前请求，并明确标注为历史数据而非
系统指令。记录内容不会被截断；如果没有完整记录能放入 `max_context_tokens`，请求在访问
模型前以 `context_budget_exceeded` 停止。`ChromaMemoryStore` 负责 Embedding 和索引，
ChromaDB 仍是首次操作时才加载的可选依赖。

长期记忆不包含自动记忆选择、自动写入、复杂元数据表达式、重排序或分数归一化。

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

### 重试策略（1.6.0 新增）

`RetryPolicy` 为模型请求和记忆读取提供显式、可配置的重试策略：

```python
from general_mini_agent import RetryPolicy, execute_with_retry

# 配置重试策略
policy = RetryPolicy(
    max_attempts=3,           # 最大尝试次数
    initial_delay_seconds=0.5, # 初始延迟
    max_delay_seconds=30.0,    # 最大延迟上限
    multiplier=2.0,            # 指数退避乘数
)

# 执行带重试的异步操作
success, error = await execute_with_retry(
    operation=lambda: model.chat_async(messages),
    policy=policy,
    on_retry=lambda attempt, error, delay: print(f"Retry {attempt}: {error}"),
)
```

**错误分类**：
- **可重试**：超时、连接错误、429 速率限制、5xx 服务器错误
- **不可重试**：401 认证错误、403 授权错误、400 验证错误、404 未找到
- **永不捕获**：`CancelledError` 直接传播

**设计原则**：
- 重试永不重复有副作用的操作（工具执行、记忆写入、流式模型输出）
- 仅对幂等读取操作（记忆 get/query）应用重试策略
- 测试可注入休眠函数，无需等待真实时钟

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
