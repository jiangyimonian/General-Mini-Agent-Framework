# General Mini Agent Framework

本文件提供仓库级开发上下文。完整规范以 `AGENTS.md` 为准。

## 项目摘要

这是一个基于 Python 的轻量级 Agent 框架，包含：

- OpenAI 兼容 LLM 客户端
- function calling 工具注册与执行
- 同步和流式 ReAct 循环
- 短期与长期记忆组件
- Solver、Critic、Judge 多 Agent 协作
- HTML 运行轨迹导出

## 修改原则

- 先阅读相关模块与测试，再修改行为。
- 保持 `core` 模块的职责边界和现有公共 API。
- 不把具体模型厂商逻辑扩散到 Agent 和工具层。
- 状态、工具和共享上下文按 Agent 或会话隔离。
- 新增行为需要测试，外部模型调用使用 Mock 验证。
- README 只记录已经实现并可运行的能力。

## 常用命令

```bash
pip install -r requirements.txt
pytest tests -v
python -m compileall -q core demo tests
```

架构说明见 `PLAN.md`，迭代计划见 `ROADMAP.md`。
