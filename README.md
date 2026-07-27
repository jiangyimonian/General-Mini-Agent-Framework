# General Mini Agent Framework

General Mini Agent Framework 是一个轻量、可组合的 Python Agent 内核。`0.4.0`
在稳定的单 Agent 执行、上下文与显式长期记忆之上，增加隔离、确定性的多 Agent
参与者协作和独立 Judge 裁决。

框架直接使用 OpenAI 兼容的 Chat Completions API，不依赖 LangChain、LangGraph
等上层编排框架。

## 0.4.0 稳定能力

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

## 实验性模块

HTML 轨迹导出仍为实验性能力。它保留在仓库中用于后续稳定化，不保证接口或行为兼容性。

## 项目结构

```text
core/
├── agent.py          # 单 Agent 执行循环
├── context.py        # Token 计数和请求上下文策略
├── llm.py            # OpenAI 兼容模型客户端
├── tools.py          # 工具注册、Schema 和执行
├── memory.py         # 内存会话与旧长期记忆兼容接口
├── long_term_memory.py # 稳定的显式长期记忆
├── debate.py         # 稳定的多 Agent 协作
└── trace.py          # 实验性 HTML 轨迹渲染
demo/
├── reasoning.py      # 同步示例
├── reasoning_stream.py # 稳定流式示例
├── chat.py           # 0.3.0 上下文与会话记忆示例
├── long_term_memory.py # 0.3.1 持久化长期记忆示例
├── debate_demo.py
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
from core import (
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
python demo/chat.py
python demo/long_term_memory.py
python demo/debate_demo.py
```

该示例需要 `.env` 中存在有效模型密钥，不属于默认离线测试。

## 稳定 API

`0.4.0` 的稳定公共入口由 `core` 包导出：

- 模型：`ChatModel`、`StreamingChatModel`、`LLM`、`LLMConfig`、`LLMResponse`、
  `ModelRequestError`、`ToolCallDelta`、`StreamChunk`
- 工具：`tool`、`Tool`、`ToolRegistry`
- Agent：`Agent`、`AgentConfig`、`AgentResult`、`AgentStopReason`、`TraceEvent`、`StreamEvent`
- 上下文：`TokenCounter`、`ApproximateTokenCounter`、`ContextPolicy`、
  `TokenBudgetContext`、`SummarizingContext`、`ContextBudgetExceeded`
- 会话：`ConversationMemory`、`InMemoryConversation`
- 长期记忆：`MemoryNamespace`、`MemoryRecord`、`MemoryQuery`、`LongTermMemoryStore`、
  `InMemoryLongTermStore`、`ChromaMemoryStore`、`MemoryStoreError`、`MemoryRecordNotFound`
- 多 Agent：`Debate`、`DebateConfig`、`DebateRole`、`DebateRound`、`DebateTurn`、
  `DebateResult`、`DebateStopReason`、`DebateStreamEvent`、`create_debate`

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
from core import Agent, InMemoryLongTermStore, MemoryNamespace, MemoryQuery

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
`core.trace` 仍属于实验性模块。`SummarizingContext` 必须由调用方
显式提供摘要函数，不会在后台复用主模型；摘要失败时回退到确定性裁剪。

### 多 Agent 协作

`Debate` 接收有序参与者列表，并将 Judge 单独配置。参与者完成一轮后才检查调用方提供的
收敛回调；收敛或达到 `max_rounds` 后，Judge 只执行一次。每次调用都创建独立上下文，
重复使用同一个 `Debate` 实例不会混入上一次运行。

```python
from core import Debate, DebateConfig, DebateRole

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

`0.4.0` 不包含并行参与者、投票、动态角色、异步 API 或通用工作流图。

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
python -m compileall -q core demo tests
ruff check core tests demo
```

## 开发文档

- [PLAN.md](PLAN.md)：`0.4.0` 架构和稳定边界
- [ROADMAP.md](ROADMAP.md)：后续版本路线
