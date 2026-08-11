# General Mini Agent Framework

轻量、可组合的 Python Agent 运行库，直接使用 OpenAI-compatible Chat Completions API。
当前版本 `1.9.0`，不依赖 LangChain 或 LangGraph。

## 能力

- 同步、流式和异步 LLM/Agent 调用
- ReAct 工具调用循环与 JSON Schema 工具注册
- 文件读写、搜索和受控命令执行项目工具
- 短期会话、上下文预算、自动压缩和可选长期记忆（ChromaDB）
- 权限策略、重试、限流、取消传播和结构化运行事件
- 顺序/并行/条件/循环工作流
- Solver/Critic/Judge 多 Agent Debate
- JSON/HTML 运行轨迹导出
- `gmaf` CLI：`init`、`doctor`、`run`、`chat`、`sessions`、`delete`

## 安装

```bash
python -m pip install .
```

可选长期记忆：

```bash
python -m pip install ".[memory]"
```

## 配置

复制 `.gmaf.toml.example` 为 `.gmaf.toml`，填写模型配置；或使用环境变量：

```bash
GMAF_API_KEY=your-api-key
GMAF_BASE_URL=https://api.openai.com/v1
GMAF_MODEL=gpt-4o-mini
```

CLI 示例：

```bash
gmaf init
gmaf doctor
gmaf run "总结当前项目结构"
gmaf chat
```

## Python 示例

```python
from general_mini_agent import Agent, LLM, LLMConfig, tool
from general_mini_agent.config import FrameworkConfig

@tool(description="计算两个整数的和")
def add(a: int, b: int) -> int:
    return a + b

config = FrameworkConfig.load()
llm = LLM(LLMConfig(
    api_key=config.api_key,
    base_url=config.base_url,
    model=config.model,
    timeout=config.timeout,
    max_retries=config.max_retries,
))
agent = Agent(llm=llm, tools=[add])
result = agent.run("计算 2 + 2")
print(result.content)
```

不应对不可信输入开放命令执行工具；项目工具的命令守卫提供工作目录、环境变量、超时和输出限制，但不是完整安全沙箱。

## 包结构

正式运行包为 `general_mini_agent/`。测试、示例和设计文档保留在本地开发环境，不包含在当前最小远程仓库中。
