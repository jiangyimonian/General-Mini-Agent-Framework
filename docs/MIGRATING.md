# 从 core 迁移到 general_mini_agent

General Mini Agent Framework 0.9.0 引入 `general_mini_agent` 命名空间作为稳定公共入口。
`core` 命名空间在 0.9.0 仍可使用，但将在 1.0.0 删除。

## 迁移时间表

- **0.9.0**：`general_mini_agent` 命名空间稳定，推荐使用；`core` 命名空间弃用但仍可用
- **1.0.0**：删除 `core` 命名空间，仅保留 `general_mini_agent`

## 机械替换步骤

### 1. 更新导入语句

将所有 `from core import` 替换为 `from general_mini_agent import`：

```python
# 旧导入（将在 1.0.0 删除）
from core import Agent, LLM, LLMConfig

# 新导入
from general_mini_agent import Agent, LLM, LLMConfig
```

### 2. 更新模块路径导入

将所有 `from core.module import` 替换为 `from general_mini_agent import`：

```python
# 旧导入
from core.agent import Agent
from core.llm import LLM

# 新导入
from general_mini_agent import Agent, LLM
```

### 3. 批量替换命令

在项目根目录执行以下命令：

```bash
# Linux/macOS
find . -name "*.py" -type f -exec sed -i 's/from core import/from general_mini_agent import/g' {} +
find . -name "*.py" -type f -exec sed -i 's/from core\./from general_mini_agent./g' {} +

# Windows PowerShell
Get-ChildItem -Recurse -Filter "*.py" | ForEach-Object {
    (Get-Content $_.FullName) -replace 'from core import', 'from general_mini_agent import' | Set-Content $_.FullName
    (Get-Content $_.FullName) -replace 'from core\.', 'from general_mini_agent.' | Set-Content $_.FullName
}
```

## 兼容性保证

以下 API 在 `general_mini_agent` 中保持稳定：

### 同步模型
- `LLM`、`LLMConfig`、`LLMResponse`
- `ChatModel`、`StreamingChatModel`
- `ModelRequestError`、`ToolCallDelta`、`StreamChunk`

### 异步模型
- `AsyncLLM`
- `AsyncChatModel`、`AsyncStreamingChatModel`

### 工具
- `tool`、`Tool`、`ToolRegistry`、`ToolExecutionResult`
- `AsyncToolRegistry`
- `JSONValue`
- `ToolAuthorizationRequest`、`ToolAuthorizationDecision`、`ToolAuthorizationPolicy`

### Agent
- `Agent`、`AgentConfig`、`AgentResult`、`AgentStopReason`
- `AsyncAgent`
- `TraceEvent`、`StreamEvent`

### 上下文与记忆
- `TokenBudgetContext`、`ContextPolicy`
- `TokenCounter`、`ApproximateTokenCounter`
- `InMemoryConversation`、`ConversationMemory`
- `InMemoryLongTermStore`、`LongTermMemoryStore`
- `MemoryNamespace`、`MemoryRecord`、`MemoryQuery`

### 多 Agent 协作
- `Debate`、`DebateConfig`、`DebateRole`
- `DebateResult`、`DebateStopReason`
- `DebateStreamEvent`

### 工作流（0.8.0+）
- `Workflow`、`SequenceNode`、`ParallelNode`、`ConditionalNode`

### 新增（0.9.0）
- `providers.ProviderCapabilities`
- `config.FrameworkConfig`
- `logging.get_logger`

## 验证迁移

迁移完成后运行完整测试：

```bash
python -m pytest tests -v
python -m compileall -q general_mini_agent demo tests
ruff check general_mini_agent tests demo
```

验证新导入可用：

```python
from general_mini_agent import Agent, AsyncAgent, Workflow
from core import Agent as LegacyAgent

# 确保两者指向同一对象
assert Agent is LegacyAgent
```

## 弃用警告

在 0.9.0 中使用 `core` 命名空间不会产生警告，但建议尽快迁移。
在 1.0.0 中，`core` 命名空间将被完全删除。

## 常见问题

### Q: 是否需要立即迁移？

A: 建议在 0.9.0 发布后尽快迁移，确保在 1.0.0 发布前完成。

### Q: 迁移是否会破坏现有功能？

A: 不会。`general_mini_agent` 导出的 API 与 `core` 完全一致，只是命名空间变更。

### Q: 是否可以同时使用两个命名空间？

A: 可以，但不推荐。建议统一使用 `general_mini_agent` 命名空间。

### Q: 第三方库依赖 `core` 怎么办？

A: 请联系第三方库维护者更新依赖。General Mini Agent Framework 将在迁移期内提供 `core`
命名空间的兼容导出。

## 支持

如有迁移问题，请在 GitHub Issues 提问。