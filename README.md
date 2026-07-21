# General Mini Agent Framework

General Mini Agent Framework 是一个轻量级 Python Agent 实验框架。项目围绕 ReAct 执行循环组织模型调用、工具调用、上下文记忆、多 Agent 协作和运行轨迹导出，适合用于学习 Agent 运行机制、验证工具协议以及构建小型 Agent 应用。

框架直接调用 OpenAI 兼容的 Chat Completions API，不依赖 LangChain、LangGraph 等上层编排框架。

## 当前能力

- 同步与 SSE 流式模型调用
- OpenAI 兼容的 function calling 数据解析
- 基于装饰器的工具注册与 JSON Schema 生成
- 带最大迭代限制的 ReAct 执行循环
- 滑动窗口上下文与 ChromaDB 长期记忆组件
- Solver、Critic、Judge 多 Agent 协作流程
- Agent 与 Debate 轨迹的自包含 HTML 导出
- 工具调用和最终答案钩子

## 项目结构

```text
General-Mini-Agent-Framework/
├── core/
│   ├── agent.py          # ReAct 执行循环
│   ├── debate.py         # 多 Agent 协作编排
│   ├── llm.py            # 同步与流式 LLM 客户端
│   ├── memory.py         # 短期和长期记忆
│   ├── tools.py          # 工具注册与 Schema 生成
│   └── trace.py          # HTML 轨迹渲染
├── demo/
│   ├── chat.py           # 交互式终端
│   ├── debate_demo.py    # 多 Agent 协作示例
│   ├── export_demo.py    # HTML 导出示例
│   ├── reasoning.py      # 同步推理示例
│   └── reasoning_stream.py
├── tests/                # 核心模块单元测试
├── .env.example          # 环境变量示例
└── requirements.txt
```

## 环境要求

- Python 3.12 或兼容版本
- 一个支持 OpenAI Chat Completions 格式的模型服务

安装依赖：

```bash
pip install -r requirements.txt
```

创建本地配置：

```powershell
Copy-Item .env.example .env
```

```bash
cp .env.example .env
```

在 `.env` 中设置模型服务：

```dotenv
DEEPSEEK_API_KEY=sk-your-key
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

`LLM_BASE_URL` 和 `LLM_MODEL` 为可选配置。也可以在代码中直接构造 `LLMConfig`，接入其他兼容服务。

## 快速开始

运行同步推理示例：

```bash
python demo/reasoning.py
```

运行流式推理：

```bash
python demo/reasoning_stream.py
```

启动交互式终端：

```bash
python demo/chat.py
```

运行多 Agent 协作示例：

```bash
python demo/debate_demo.py
```

导出 HTML 轨迹：

```bash
python demo/export_demo.py
python demo/export_demo.py debate
```

## 基础用法

```python
from core.agent import Agent
from core.llm import LLM, LLMConfig
from core.tools import tool


@tool(description="计算两个整数之和")
def add(a: int, b: int) -> int:
    return a + b


llm = LLM(
    LLMConfig(
        api_key="sk-your-key",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )
)

agent = Agent(llm=llm, tools=[add], max_iterations=6)
result = agent.run("请计算 17 + 25")

print(result.content)
print(result.trace)
print(result.usage)
```

流式执行会产生结构化事件：

```python
for event in agent.run_stream("请计算 17 + 25"):
    if event["type"] == "thought_chunk":
        print(event["text"], end="", flush=True)
    elif event["type"] == "done":
        print(event["content"])
```

## 核心模块

### LLM 客户端

`core.llm.LLM` 使用 `httpx` 请求 `/chat/completions`，负责：

- 构造同步和流式请求
- 解析文本、工具调用和 Token 用量
- 对部分临时性 HTTP 错误执行指数退避重试
- 将响应转换为 `LLMResponse`、`ToolCall` 和 `StreamChunk`

### 工具系统

`@tool` 会读取函数签名和类型注解，生成 function calling 所需的 JSON Schema。`Tool.execute()` 统一将执行结果转换为字符串，并把工具异常转换为可供 Agent 继续处理的观察结果。

### Agent 循环

`core.agent.Agent` 在每轮执行中完成以下流程：

```text
用户输入 -> 模型响应 -> 工具调用 -> 工具结果 -> 模型响应 -> 最终答案
```

执行结果通过 `AgentResult` 返回，其中包含最终文本、轨迹、Token 用量和迭代次数。

### 记忆组件

- `SlidingWindowMemory`：保存固定窗口内的消息。
- `LongTermMemory`：通过 ChromaDB 持久化文本并执行语义检索。

### 多 Agent 协作

`core.debate.Debate` 提供 Solver、Critic、Judge 三种角色。角色通过共享上下文交换结果，并由 Judge 输出最终结论。

### 轨迹导出

`core.trace` 可以将 `AgentResult` 或 `DebateResult` 渲染为独立 HTML 文件，用于查看工具调用、观察结果、最终答案和 Token 统计。

## 测试

```bash
pytest tests -v
```

当前测试覆盖同步响应解析、基础 ReAct 循环、工具注册和滑动窗口记忆。流式执行、多 Agent 协作、HTML 渲染和长期记忆的测试将在后续版本补充。

## 开发文档

- [PLAN.md](PLAN.md)：架构边界与开发原则
- [ROADMAP.md](ROADMAP.md)：后续迭代路线

## 当前边界

项目目前定位为小型实验框架，重点是保持执行路径清晰。生产环境通常还需要补充异步接口、并发隔离、工具权限控制、完整可观测性、配置校验和更全面的自动化测试。
