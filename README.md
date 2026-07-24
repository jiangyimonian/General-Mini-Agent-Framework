# General Mini Agent Framework

General Mini Agent Framework 是一个轻量、可组合的 Python Agent 内核。`0.3.0`
在稳定的单 Agent 同步与流式执行之上，增加显式上下文预算、确定性历史裁剪和成功
对话自动写回。

框架直接使用 OpenAI 兼容的 Chat Completions API，不依赖 LangChain、LangGraph
等上层编排框架。

## 0.3.0 稳定能力

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

## 实验性模块

长期向量记忆、多 Agent 和 HTML 轨迹导出仍为实验性能力。它们保留在仓库中用于后续
稳定化，不保证接口或行为兼容性。

## 项目结构

```text
core/
├── agent.py          # 单 Agent 执行循环
├── context.py        # Token 计数和请求上下文策略
├── llm.py            # OpenAI 兼容模型客户端
├── tools.py          # 工具注册、Schema 和执行
├── memory.py         # 内存会话与实验性长期记忆
├── debate.py         # 实验性多 Agent 协作
└── trace.py          # 实验性 HTML 轨迹渲染
demo/
├── reasoning.py      # 同步示例
├── reasoning_stream.py # 稳定流式示例
├── chat.py           # 0.3.0 上下文与记忆示例
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
```

该示例需要 `.env` 中存在有效模型密钥，不属于默认离线测试。

## 稳定 API

`0.3.0` 的稳定公共入口由 `core` 包导出：

- 模型：`ChatModel`、`StreamingChatModel`、`LLM`、`LLMConfig`、`LLMResponse`、
  `ModelRequestError`、`ToolCallDelta`、`StreamChunk`
- 工具：`tool`、`Tool`、`ToolRegistry`
- Agent：`Agent`、`AgentConfig`、`AgentResult`、`AgentStopReason`、`TraceEvent`、`StreamEvent`
- 上下文：`TokenCounter`、`ApproximateTokenCounter`、`ContextPolicy`、
  `TokenBudgetContext`、`SummarizingContext`、`ContextBudgetExceeded`
- 会话：`ConversationMemory`、`InMemoryConversation`

`StreamEvent` 包含 `iteration_start`、`thought_chunk`、`tool_call`、`observation`、
`final_answer`、`model_error` 和 `done` 七种事件。`done.stop_reason` 为 `completed`、
`max_iterations`、`model_error`、`incomplete` 或 `context_budget_exceeded`。

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

`SlidingWindowMemory` 和 `LongTermMemory` 仅保留兼容导出，不属于稳定 API。
`core.debate` 与 `core.trace` 同样属于实验性模块。`SummarizingContext` 必须由调用方
显式提供摘要函数，不会在后台复用主模型；摘要失败时回退到确定性裁剪。

## 实验性示例

以下入口可以用于试验现有实现，但其接口和行为可能在后续版本调整：

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

- [PLAN.md](PLAN.md)：`0.3.0` 架构和稳定边界
- [ROADMAP.md](ROADMAP.md)：后续版本路线
