# General Mini Agent Framework

General Mini Agent Framework 是一个轻量、可组合的 Python Agent 内核。`0.1.0`
稳定支持 OpenAI 兼容模型上的单 Agent 同步工具调用，并提供实例隔离和结构化运行轨迹。

框架直接使用 OpenAI 兼容的 Chat Completions API，不依赖 LangChain、LangGraph
等上层编排框架。

## 0.1.0 稳定能力

- OpenAI 兼容 Chat Completions 客户端
- Python 函数到 JSON Schema 的工具定义
- 单 Agent 同步工具调用与 ReAct 循环
- Agent 实例级工具隔离
- 结构化执行结果、轨迹和明确的停止原因
- 模型请求超时、有限重试和脱敏错误

## 实验性模块

流式、多 Agent、记忆和 HTML 轨迹导出不属于 0.1.0 稳定 API。它们保留在仓库中用于实验，
不保证接口或行为兼容性。

## 项目结构

```text
core/
├── agent.py          # 单 Agent 执行循环
├── llm.py            # OpenAI 兼容模型客户端
├── tools.py          # 工具注册、Schema 和执行
├── memory.py         # 实验性记忆组件
├── debate.py         # 实验性多 Agent 协作
└── trace.py          # 实验性 HTML 轨迹渲染
demo/
├── reasoning.py      # 0.1.0 同步示例
├── reasoning_stream.py
├── chat.py
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
```

`LLM_BASE_URL` 和 `LLM_MODEL` 为可选配置。也可以直接构造 `LLMConfig`，接入其他
OpenAI 兼容服务。

## 快速开始

```python
from core import Agent, LLM, LLMConfig, tool


@tool(description="计算两个整数的和")
def add(a: int, b: int) -> int:
    return a + b


agent = Agent(
    llm=LLM(LLMConfig(api_key="<your-api-key>", model="<your-model>")),
    tools=[add],
)
result = agent.run("计算 17 + 25")
print(result.content)
```

仓库中的稳定示例：

```bash
python demo/reasoning.py
```

该示例需要 `.env` 中存在有效模型密钥，不属于默认离线测试。

## 稳定 API

`0.1.0` 的稳定公共入口由 `core` 包导出：

- 模型：`ChatModel`、`LLM`、`LLMConfig`、`LLMResponse`、`ModelRequestError`
- 工具：`tool`、`Tool`、`ToolRegistry`
- Agent：`Agent`、`AgentConfig`、`AgentResult`、`AgentStopReason`、`TraceEvent`

`StreamChunk`、`SlidingWindowMemory` 和 `LongTermMemory` 目前仅保留兼容导出，不属于
`0.1.0` 稳定 API。`core.debate` 与 `core.trace` 同样属于实验性模块。

## 实验性示例

以下入口可以用于试验现有实现，但其接口和行为可能在后续版本调整：

```bash
python demo/reasoning_stream.py
python demo/chat.py
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

- [PLAN.md](PLAN.md)：`0.1.0` 架构和稳定边界
- [ROADMAP.md](ROADMAP.md)：后续版本路线
