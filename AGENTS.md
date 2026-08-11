# General Mini Agent Framework

## 项目定位

General Mini Agent Framework 是一个轻量级 Python Agent 框架。当前代码提供模型调用、工具注册、ReAct 循环、记忆组件、多 Agent 协作和 HTML 轨迹导出。

本仓库是最小运行库。开发时优先保持核心流程清晰，并通过与改动风险匹配的验证约束行为。

## 技术栈

| 技术 | 用途 |
|---|---|
| Python 3.12 | 开发语言 |
| httpx | OpenAI 兼容模型 API 客户端 |
| ChromaDB | 可选长期记忆存储 |
核心协议不应绑定特定模型厂商。

## 目录职责

```text
general_mini_agent/  框架运行包
pyproject.toml       安装和打包配置
```

核心模块：

- `general_mini_agent/llm.py`：模型请求与响应解析
- `general_mini_agent/tools.py`：工具注册、Schema 和执行
- `general_mini_agent/agent.py`：单 Agent 执行循环
- `general_mini_agent/memory.py`：短期记忆
- `general_mini_agent/long_term_memory.py`：长期记忆
- `general_mini_agent/debate.py`：多 Agent 角色协作
- `general_mini_agent/workflow.py`：工作流编排
- `general_mini_agent/trace.py`：运行轨迹渲染

## 开发约束

1. 保持模块边界，不在模型客户端中执行工具或管理业务状态。
2. 保持现有公共 API，除非任务明确要求破坏性变更。
3. 新功能同时覆盖同步和流式路径，或明确说明只支持其中一种。
4. Agent 实例之间的状态、工具和上下文必须可隔离。
5. 外部服务调用需要超时、错误分类和可测试的替代实现。
6. 可选依赖继续使用延迟加载。
7. 不在源码、文档或测试中写入真实 API Key。
8. 修改行为时执行与风险匹配的验证；如本地维护测试，应同步更新。
9. 文档只描述当前真实存在的能力。

## 编码风格

- 使用类型注解表达公共接口。
- 数据载体优先使用 dataclass 或明确的结构化类型。
- 注释说明设计原因，不重复代码行为。
- 保持函数职责单一，避免为预期需求提前增加抽象。
- 错误信息应包含可定位上下文，但不得泄露密钥。

## 验证命令

```bash
python -m compileall -q general_mini_agent
python -m pip install .
python -c "import general_mini_agent; print(general_mini_agent.__version__)"
```

## 开发优先级

1. 状态管理和工具隔离正确性
2. 同步、流式、异步和多 Agent 路径一致性
3. 项目打包和可复现运行环境
4. 长期记忆、复杂编排和可观测性
