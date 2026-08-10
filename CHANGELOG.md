# 变更日志

本项目的所有重要变更都将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.9.0] - 2026-08-10

### 新增

- **受控命令执行**：`SandboxConfig`、`SandboxResult`、`CommandSandbox` 提供可移植的子进程守卫
- `ToolRuntimeContext.sandbox_config`: 可选沙箱配置，默认禁用（保持向后兼容）
- 工作目录逃逸防护：拒绝将 `cwd` 设置到配置根目录之外
- 环境变量过滤：仅传递白名单内的环境变量
- 超时强制终止：超时后清理进程组或进程树
- 有界输出捕获：持续排空 stdout/stderr，保留内容不超过配置上限
- 平台信息查询：`is_sandbox_available()`、`get_platform_info()`
- fail-closed：请求未实现的网络隔离时返回错误且不执行命令

### 变更

- 版本号更新为 1.9.0
- `SandboxConfig`、`SandboxResult`、`CommandSandbox` 导出为公共 API

### 设计原则

- 默认禁用执行守卫，保持现有行为
- 通过授权策略调用时，权限检查先于命令执行
- Phase 1 使用 subprocess，提供 cwd、环境、超时和输出捕获守卫
- Phase 1 不是不受信任代码的安全边界；文件系统、网络和资源隔离保留到后续版本

## [1.8.0] - 2026-08-07

### 新增

- **速率限制策略**: `RateLimitPolicy` 和 `RateLimiter` 实现请求治理
- `RateLimitPolicy(requests_per_minute, burst)`: 配置每分钟请求数和突发容量
- `RateLimiter.try_acquire()`: 非阻塞尝试获取令牌
- `RateLimiter.acquire_sync()`: 同步阻塞获取令牌
- `RateLimiter.acquire_async()`: 异步阻塞获取令牌
- 支持超时配置：`acquire_sync(timeout=...)` 和 `acquire_async(timeout=...)`
- 使用令牌桶算法，支持突发请求

### 变更

- 版本号更新为 1.8.0
- `RateLimitPolicy` 和 `RateLimiter` 导出为公共 API
- 默认不启用速率限制，现有代码无需修改

### 设计原则

- 速率限制仅对配置的 LLM 实例生效
- 使用单调时钟，不依赖系统时间
- 异步取消正确传播

## [1.7.0] - 2026-08-07

### 新增

- **动态工作流节点**: 支持运行时受限的图扩展
- `WorkflowConfig`: 配置最大节点数和深度
- `GraphFrozenError`: 当尝试修改已冻结的图时抛出
- `Workflow.add_node()`: 请求动态添加节点
- 新增事件类型：
  - `node_addition_requested`: 节点请求添加
  - `node_addition_accepted`: 节点添加成功
  - `node_addition_rejected`: 节点添加被拒绝
  - `graph_frozen`: 图被冻结

### 变更

- 版本号更新为 1.7.0
- `WorkflowConfig` 和 `GraphFrozenError` 导出为公共 API

### 设计约束

- 默认最大节点数：100（含静态节点）
- 默认最大深度：10 层
- 重复节点名称被拒绝
- 工作流完成或取消后图被冻结
- 两次运行不共享动态添加

## [1.6.0] - 2026-08-07

### 新增

- **显式重试策略**: `RetryPolicy` 配置类，支持指数退避和最大尝试次数
- `execute_with_retry()` 异步助手函数，用于执行带重试的操作
- 可注入休眠函数，支持确定性测试（无需等待真实时钟）
- 结构化错误分类：
  - 可重试：超时、连接错误、429 速率限制、5xx 服务器错误
  - 不可重试：401 认证错误、403 授权错误、400 验证错误、404 未找到
- `CancelledError` 永不捕获，直接传播
- `on_retry` 回调，用于可观测性

### 变更

- 版本号更新为 1.6.0
- `RetryPolicy` 和 `execute_with_retry` 导出为公共 API

### 设计原则

- 重试永不重复有副作用的操作（工具、记忆写入、流式模型输出）
- 仅对幂等读取操作（记忆 get/query）应用重试策略
- 测试可注入休眠函数，无需等待真实时钟

## [1.5.0] - 2026-08-07

### 新增

- **异步 ChromaDB 适配器**: `AsyncChromaMemoryStore` 提供可选的持久化异步记忆存储
- 延迟加载：ChromaDB 仅在首次使用时导入，不影响包导入
- 可注入客户端工厂：测试时可通过 `client_factory` 参数注入假客户端
- 所有操作通过 `asyncio.to_thread()` 执行，不阻塞事件循环
- 支持超时配置：`default_timeout` 参数控制操作超时
- 失败映射为 `MemoryStoreError(operation, backend="chroma")`，不暴露后端异常文本

### 变更

- 版本号更新为 1.5.0
- `AsyncChromaMemoryStore` 导出为公共 API

### 兼容性

- ChromaDB 仍为可选依赖：`pip install ".[memory]"`
- 核心包可在没有 ChromaDB 的情况下正常导入和使用

## [1.4.0] - 2026-08-07

### 新增

- **异步长期记忆协议**: 新增 `AsyncLongTermMemoryStore` 协议，允许 `AsyncAgent` 非阻塞检索长期记忆
- `AsyncInMemoryLongTermStore` - 进程内异步记忆存储，与 `InMemoryLongTermStore` 具有相同值语义
- `AsyncAgent.long_term_memory` 现在接受 `AsyncLongTermMemoryStore | LongTermMemoryStore | None`
- 异步存储使用 `asyncio.Lock` 保护记录修改，返回防御性副本
- 所有六个存储操作（store、get、query、update、delete、clear）均为 awaitable
- 命名空间隔离、确定性行为，不改变同步存储行为

### 变更

- `AsyncAgent._initial_messages()` 使用 `inspect.iscoroutinefunction()` 检测异步存储，自动 await 异步 query
- 同步存储在异步上下文中仍可用（向后兼容），但会阻塞事件循环
- 版本号更新为 1.4.0

### 兼容性

- 完全向后兼容：现有使用同步 `LongTermMemoryStore` 的代码无需修改
- ChromaDB 异步适配器将在 1.5.0 版本提供

## [1.3.1] - 2026-08-07

### 修复

- **并行回合异常处理**: 修复 `_run_parallel_round()` 中 `asyncio.gather()` 使用 `return_exceptions=False` 导致的问题。当一个参与者抛出异常时，现在会捕获异常并创建错误 turn，而不是导致整个回合失败。其他参与者继续正常执行。
- 并行参与者异常现在返回 `model_error` stop_reason 和结构化错误消息

### 新增

- 压力测试套件 `tests/test_async_debate_stress.py`：
  - 大量并行参与者测试（10 个参与者）
  - 提前取消的资源清理测试
  - 流式提前取消测试
  - 参与者异常隔离测试

## [1.3.0] - 2026-08-07

### 新增

- `AsyncParticipantExecution` - 并行执行模式类型（`"sequential"` | `"parallel"`）
- `AsyncDebateConfig.participant_execution` - 显式启用并行回合
- 并行参与者只读取已完成轮次，不读取同轮其他参与者的回答
- 结果按声明顺序归档，确保确定性输出
- 流式事件复用：使用 `asyncio.Queue` 传递事件，每个 `agent_event` 标识发起角色
- 完整的失败归集：并行回合中一个失败时保留所有 turn
- 取消传播：取消正确传播到所有并行参与者
- 并行 Demo：`demo/async_debate_demo.py` 新增示例 4

### 变更

- 版本号更新为 1.3.0
- README 更新并行模式文档

### 兼容性

- 升级从 `1.2.x` 保持兼容：默认 `participant_execution="sequential"`
- 现有代码无需修改，显式传入 `"parallel"` 才启用并行模式

## [1.2.1] - 2026-08-06

### 修复

- **AsyncDebate 并发安全问题**: 移除了实例变量 `_last_turn`，改用调用方提供的单元素列表容器来暂存 async generator 的返回值，避免同一 AsyncDebate 实例并发调用时的状态竞态问题。

## [1.2.0] - 2026-08-06

### 新增

- `AsyncDebate` - 异步多 Agent 协作组件
- `AsyncDebateRole` - 异步参与者配置
- `AsyncDebateConfig` - 异步 Debate 配置
- `AsyncDebateStreamEvent` - 异步流式事件类型
- `AsyncDebateNode` - 工作流集成适配器
- `create_async_debate()` - 便捷工厂函数
- 非阻塞执行：`AsyncDebate.run_async()` 异步非阻塞
- 流式输出：`AsyncDebate.run_stream_async()` 异步流式
- 顺序模式下，后一个角色可读取同轮前序发言
- 每次调用独立，实例可复用，状态隔离
- 离线 Demo：`demo/async_debate_demo.py`

### 变更

- 版本号更新为 1.2.0
- README 更新异步 Debate 使用文档

## [1.1.5] - 2026-08-06

### 新增

- `LoopNode` - 循环执行 body 直到 should_stop 返回 True
- 支持最大迭代次数限制，防止无限循环
- 完整的事件追踪：`loop_started`、`loop_iteration_started`、`loop_iteration_finished`、`loop_finished`

### 变更

- 版本号更新为 1.1.5
- ROADMAP.md 移除已稳定的循环节点条目

## [1.1.4] - 2026-08-06

### 新增

- 会话持久化：`save_session()`、`load_session()`、`list_sessions()`、`delete_session()`
- 会话元数据：`SessionMetadata` 包含会话名称、创建时间、修改时间
- `Session` 包裹对话记忆与会话元数据
- 自动上下文压缩：`SimpleTruncationStrategy`、`SummarizationStrategy`
- `CompressingContextPolicy` - 可感知压缩的上下文策略
- `AutoCompressingConversation` - 自动压缩的对话记忆
- CLI 会话命令：`gmaf chat --session`、`gmaf sessions`、`gmaf delete`

### 变更

- 版本号更新为 1.1.4
- ROADMAP.md 移除已稳定的会话和压缩条目

## [1.1.0] - 2026-08-03

### 新增

- 标准回合协议：同步、流式和异步路径共同遵守的统一消息协议
- `AssistantTurn`、`ToolOutcome`、`TurnDecision` 内部数据结构
- `StreamingTurnAccumulator` 流式回合累积器
- 多工具调用按原始顺序执行，一条 assistant 消息对应多个 tool results
- `finish_reason` 语义：`stop`、`length`、`content_filter` 正确映射到终止状态
- 空响应和协议错误返回 `model_error`，不再伪造消息重试
- 参数解析失败返回 `invalid_arguments`，模型可修正重试
- 默认 system prompt 改为原生工具调用导向，不再要求文本 ReAct 格式

### 变更

- 同步、流式和异步路径通过统一协议函数，保证消息顺序和终止语义一致
- 多工具回合使用一条 assistant 消息和完整结果集合，不再交错
- `length` 和 `content_filter` 不再报告成功，返回 `incomplete` 且不写记忆
- 流式路径在累积完整回合后才执行工具，不提前启动
- CI 和文档更新为使用 `general_mini_agent` 命名空间

### 修复

- 修复同步路径多工具调用时拆分 assistant 消息的问题
- 修复流式路径工具调用和文本增量事件边界问题
- 修复异步路径取消传播和记忆提交条件

## [1.0.0] - 2026-07-29

### 变更

- 删除 `core` 命名空间，仅保留 `general_mini_agent`
- 所有测试和文档更新为使用新命名空间
- 版本号更新为 1.0.0，公共 API 冻结

### 迁移说明

从 0.9.0 升级：将 `from core import X` 替换为 `from general_mini_agent import X`。

## [0.9.0] - 2026-07-28

### 新增

- `general_mini_agent` 命名空间：稳定的公共 API 入口，导出所有公共组件
- 模型能力适配器：`ProviderCapabilities` 自动检测并适配 OpenAI、DeepSeek、Claude 等服务商的工具调用差异
- 统一配置：`FrameworkConfig` 提供框架级配置入口
- 安全日志：自动脱敏 API Key、Authorization header 等敏感信息
- 迁移文档：`docs/MIGRATING.md` 提供 `core` 到 `general_mini_agent` 的机械替换步骤

### 变更

- 版本号更新为 0.9.0
- 所有文档和 Demo 更新为 `from general_mini_agent import` 导入风格
- README 新增 0.9.0 能力说明和迁移指南链接
- `docs/RELEASING.md` 更新验证命令使用新命名空间

### 弃用

- `core` 命名空间在 0.9.0 仍可使用，但将在 1.0.0 删除
- 建议尽快迁移到 `general_mini_agent` 命名空间

## [0.8.0] - 2026-07-28

### 新增

- 工作流节点：`Workflow`、`WorkflowNode` 协议、`WorkflowResult`
- 串行节点：`SequenceNode` 依次执行，传递前一节点输出
- 并行节点：`ParallelNode` 有限并发，结果按声明顺序排列
- 条件节点：`ConditionalNode` 根据 predicate 选择分支
- 错误策略：`fail_fast` 和 `collect_errors`
- 适配器：`AgentNode`、`AsyncAgentNode`、`DebateNode`
- 离线工作流 Demo：`demo/workflow_demo.py`

### 变更

- 版本号更新为 0.8.0
- PLAN.md 新增 workflow.py 和 workflow_adapters.py 模块说明
- ROADMAP.md 移除已稳定的编排条目

## [0.7.1] - 2026-07-28

### 新增

- HTML 报告渲染：`trace_to_html()`、`export_trace_html()`、`compare_traces_to_html()`
- 事件过滤：类型、run ID、停止原因、仅错误
- 双运行对比报告：显示 usage、耗时、错误差异
- 离线 Demo：`python demo/offline.py` 生成 Agent 和 Debate 轨迹
- 脚本化模型：`demo/scripted_models.py` 用于无网络测试

### 变更

- HTML 报告从实验性提升为稳定能力
- 版本号更新为 0.7.1
- PLAN.md 将 HTML trace 标记为稳定

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
