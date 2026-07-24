# General Mini Agent Framework 架构说明

## 项目目标

General Mini Agent Framework 提供结构清晰、边界明确的 Agent 基础组件。`0.2.0`
稳定单 Agent 同步工具调用和同步生成器式流式执行，后续版本再逐步稳定记忆和多 Agent 能力。

## 设计原则

1. **显式执行流程**：模型请求、工具调用、观察结果和最终答案通过结构化数据传递。
2. **实例状态隔离**：Agent 的工具、配置和执行状态不得通过进程级可变状态共享。
3. **小型模块边界**：模型、工具、执行器和实验模块分别维护。
4. **兼容标准协议**：模型层使用 OpenAI 兼容的 Chat Completions 和 function calling。
5. **失败可观察**：停止原因、工具错误和模型请求错误必须可定位且不得泄露密钥。
6. **行为优先于抽象**：只有出现真实复用需求时才增加新的协议和编排层。

## 0.2.0 稳定边界

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

流式路径稳定支持七种 `StreamEvent`、四种停止原因、按 index 聚合的多工具调用、
非法参数修正、协议错误终止和每次请求一次的 usage 累计。

## 实验性模块

以下能力保留用于实验，不属于 `0.2.0` 稳定 API：

- `core/memory.py`：滑动窗口和 ChromaDB 长期记忆
- `core/debate.py`：多 Agent 角色协作
- `core/trace.py`：HTML 轨迹渲染

实验模块可以修改接口和行为。稳定化顺序见 [ROADMAP.md](ROADMAP.md)。

## 公共接口

`core/__init__.py` 中的 `0.2.0` 稳定导出为：

- `ChatModel`、`StreamingChatModel`、`LLM`、`LLMConfig`、`LLMResponse`、
  `ModelRequestError`、`ToolCallDelta`、`StreamChunk`
- `tool`、`Tool`、`ToolRegistry`
- `Agent`、`AgentConfig`、`AgentResult`、`AgentStopReason`、`TraceEvent`、`StreamEvent`

`SlidingWindowMemory` 和 `LongTermMemory` 仅为兼容现有调用而继续导出，不构成稳定 API。

## 错误处理

- 认证失败和不可重试 HTTP 错误直接转换为脱敏模型错误。
- 超时、连接错误和临时服务端错误执行有限重试。
- 未知工具、无效参数和工具异常写入结构化轨迹，使模型可以修正或结束。
- 达到最大迭代次数时返回明确的 `stop_reason`。
- 可选依赖在首次使用实验组件时延迟加载。

## 测试策略

默认测试使用脚本化模型响应，不访问网络或真实模型服务。稳定模块至少覆盖正常路径、
无效输入、错误分类、状态隔离和停止条件。实验模块的现有测试用于防止已知回归，但不代表
其接口已进入稳定契约。

真实模型验证不属于默认 CI；运行 Demo 前需要从 `.env.example` 创建 `.env` 并配置有效密钥。
