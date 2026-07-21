# General Mini Agent Framework

## 项目定位

General Mini Agent Framework 是一个轻量级 Python Agent 框架。当前代码提供模型调用、工具注册、ReAct 循环、记忆组件、多 Agent 协作和 HTML 轨迹导出。

本仓库将作为后续扩展和工程化的代码基线。开发时优先保持核心流程清晰，并通过测试约束行为。

## 技术栈

| 技术 | 用途 |
|---|---|
| Python 3.12 | 开发语言 |
| httpx | OpenAI 兼容模型 API 客户端 |
| ChromaDB | 可选长期记忆存储 |
| python-dotenv | Demo 环境变量加载 |
| pytest | 自动化测试 |

默认配置使用 DeepSeek 的 OpenAI 兼容接口，但核心协议不应绑定特定模型厂商。

## 目录职责

```text
core/     框架实现
demo/     可运行示例
tests/    单元测试
docs/     设计和开发文档
```

核心模块：

- `core/llm.py`：模型请求与响应解析
- `core/tools.py`：工具注册、Schema 和执行
- `core/agent.py`：单 Agent 执行循环
- `core/memory.py`：短期与长期记忆
- `core/debate.py`：多 Agent 角色协作
- `core/trace.py`：运行轨迹渲染

## 开发约束

1. 保持模块边界，不在模型客户端中执行工具或管理业务状态。
2. 保持现有公共 API，除非任务明确要求破坏性变更。
3. 新功能同时覆盖同步和流式路径，或明确说明只支持其中一种。
4. Agent 实例之间的状态、工具和上下文必须可隔离。
5. 外部服务调用需要超时、错误分类和可测试的替代实现。
6. 可选依赖继续使用延迟加载。
7. 不在源码、文档或测试中写入真实 API Key。
8. 修改行为时添加与风险匹配的测试。
9. 文档只描述当前真实存在的能力，规划内容写入 `ROADMAP.md`。

## 编码风格

- 使用类型注解表达公共接口。
- 数据载体优先使用 dataclass 或明确的结构化类型。
- 注释说明设计原因，不重复代码行为。
- 保持函数职责单一，避免为预期需求提前增加抽象。
- 错误信息应包含可定位上下文，但不得泄露密钥。

## 验证命令

```bash
pytest tests -v
python -m compileall -q core demo tests
```

需要真实模型服务的 Demo 不属于默认离线测试。运行前从 `.env.example` 创建 `.env` 并配置有效密钥。

## 开发优先级

1. 状态管理和工具隔离正确性
2. 流式、多 Agent 与长期记忆测试
3. 项目打包和可复现开发环境
4. 异步接口、复杂编排和可观测性

详细架构见 `PLAN.md`，后续路线见 `ROADMAP.md`。
