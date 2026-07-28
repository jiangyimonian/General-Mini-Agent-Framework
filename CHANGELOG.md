# 变更日志

本项目的所有重要变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.7.0] - 2026-07-28

### 新增

- 运行上下文：`RunContext` 持有唯一 `run_id` 和父运行关系
- 事件 envelope：`RunEvent` 包含序号、时间戳、耗时和 payload
- 事件收集器：`EventCollector` 内存收集器，线程安全，支持不可变快照
- 事件发射器：`RunEventEmitter` 管理序号和时钟，支持父子关系
- 版本化 JSON trace：`TraceDocument`、`trace_to_json()`、`trace_from_json()`、`export_trace_json()`
- Agent 和 Debate 发射 `run_started` / `run_finished` 事件
- Debate 参与者和 Judge 拥有独立子 run ID，正确指向父 run ID
- 模型错误自动脱敏，不包含 Authorization header 或 API Key
- `AgentResult` 和 `DebateResult` 新增 `run_id` 字段

### 变更

- 版本号更新为 0.7.0
- PLAN.md 新增 events.py 和 trace_json.py 模块说明
- ROADMAP.md 移除已稳定的可观测性条目

## [0.6.0] - 2026-07-28

### 新增

- 异步模型协议：`AsyncChatModel`、`AsyncStreamingChatModel`、`AsyncLLM`
- `AsyncLLM` 支持 `async with` 生命周期管理、异步重试和 SSE 流式响应
- 异步工具注册与执行：`AsyncToolRegistry`、`execute_async()`
- 工具 timeout 配置：超过 deadline 返回 `tool_timeout` observation
- `CancelledError` 从模型、工具、Agent 原样传播
- 异步 Agent：`AsyncAgent.run_async()` 和 `run_stream_async()`
- `demo/reasoning_async.py` 异步示例

### 变更

- 同步 callable 通过 `asyncio.to_thread()` 在后台线程执行
- 取消等待不会终止后台线程，同步工具可能继续产生副作用
- 版本号更新为 0.6.0

## [0.5.0] - 2026-07-27

### 新增

- 结构化工具执行结果：`ToolExecutionResult.value` 保留合法 JSON 值，`content` 使用确定性紧凑序列化
- 实例级工具授权策略：`ToolAuthorizationPolicy` 协议、`ToolAuthorizationRequest` 和 `ToolAuthorizationDecision`
- `Agent` 构造器支持 `tool_authorization_policy` 参数，策略注入注册表
- `JSONValue` 类型别名、`permission_denied` 和 `authorization_error` 错误码
- fail-closed 授权语义：策略拒绝或异常时工具函数不被调用

### 变更

- 字符串工具结果保持原样传递给模型，不再 JSON 序列化
- 合法 JSON 工具结果使用 `json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":"))` 生成确定性 `content`
- ROADMAP 删除已稳定的能力条目

## [0.4.1] - 2026-07-27

### 新增

- 新增 `release` 可选依赖，包含 `build` 与 `twine` 用于发行包构建和检查
- 新增中文 `CHANGELOG.md` 记录版本变更
- 新增 `docs/RELEASING.md` 发布手册，记录维护者验证与打 tag 步骤
- 新增 CI 双版本测试矩阵（Python 3.12、3.13）
- 新增 CI 发行验证 job，执行构建、元数据检查和 wheel 安装冒烟

### 变更

- 统一文档中的测试命令为 `python -m pytest tests -v`
- CI 将 lint、字节码编译和发行包验证分离为独立 job，避免重复执行

## [0.4.0] - 2026-07-XX

### 新增

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