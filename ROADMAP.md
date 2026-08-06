# General Mini Agent Framework 路线图

`1.2.1` 已完成并发安全修复。
`1.2.0` 已完成异步 Debate 基础。
`1.1.5` 已完成循环节点。
`1.1.4` 已完成会话管理和上下文压缩功能。
路线图只记录尚未稳定或仍需实现的能力；当前稳定能力以 [README.md](README.md) 为准。

## 1.2.x 产品化路线

### 1.2.1 稳定化补丁 ✓ 已完成

- 修复 AsyncDebate 中 `_last_turn` 实例变量的并发安全问题
- 改用调用方提供的容器来暂存 async generator 返回值
- 不新增并行模式、异步长期记忆协议或其他公开 API

### 1.2.0 异步 Debate 基础 ✓ 已完成

- `AsyncDebate`、`AsyncDebateRole` 和顺序参与者执行
- 与同步 Debate 对齐的 `run_async()`、`run_stream_async()`、结果结构和终止语义
- 异步 Debate 工作流适配器、事件父子关系和离线 Demo
- 参与者按声明顺序执行；后一个参与者可以读取同轮前序发言

## 1.3.x 产品化路线

### 1.1.1 项目工具集 ✓ 已完成

- 文件工具：`read_file`、`list_files`/`glob_files`、`search_text`
- 变更工具：`write_file`、`edit_file`（要求显式启用 mutation 能力）
- 命令工具：`run_command`（要求显式启用 execute 能力）
- 共享 `ToolRuntimeContext`，路径必须位于 workspace

### 1.1.2 权限与安全边界 ✓ 已完成

- 授权协议：`allow`、`deny`、`ask`
- 风险类别：`read`、`write`、`execute`、`external`
- 结构化权限请求事件，不直接调用 `input()`
- 路径和能力边界检查
- 可组合策略框架：`AllowAllPolicy`、`DenyAllPolicy`、`RiskBasedPolicy`、`CompositePolicy` 等

### 1.1.3 即装即用 CLI ✓ 已完成

- `gmaf` console script
- `--version`、`doctor`、`init`、单次任务和 `chat`
- 配置顺序：命令 > 项目配置 > 用户配置 > 环境变量 > 默认值

### 1.1.4 长任务与会话能力 ✓ 已完成

- 会话保存与恢复
- 自动上下文压缩
- 任务计划与结构化运行记录
- 严格分离 Conversation Memory、Session Store 和 Trace Store

### 1.1.5 循环节点 ✓ 已完成

- `LoopNode`：重复执行 body 直到 should_stop 返回 True
- 支持最大迭代次数限制，防止无限循环
- 完整的事件追踪

## 后续版本计划

补丁版本只用于修复、兼容性和文档收口，不新增公开能力。以下 minor
版本是当前实现顺序，不代表已经交付的稳定功能。

### 1.3.0 并行异步 Debate

- `participant_execution="parallel"` 显式启用并行回合
- 并行参与者只读取已完成轮次，结果按声明顺序归档
- 多参与者流式事件复用、完整失败归集和取消测试

### 1.3.1 稳定化补丁

- 只修复 1.3.0 的并行调度、资源清理和事件互操作问题

### 1.4.0 异步长期记忆协议

- 异步长期记忆 Store 协议和内存实现
- `AsyncAgent` 的非阻塞检索、错误分类和离线测试替身

### 1.5.0 异步 ChromaDB 适配器

- 延迟加载的异步 ChromaDB 集成
- 连接生命周期、超时、错误映射和可替换测试实现

### 1.6.0 编排重试策略

- 模型、工具和记忆边界的显式重试策略
- 可注入时钟的指数退避、错误分类和取消语义

### 1.7.0 动态工作流节点

- 运行时添加节点的受限 API
- 节点图校验、事件关系和确定性测试

### 1.8.0 运行治理与可观测性

- 请求速率限制
- OpenTelemetry 集成
- 运行、工具和模型调用的关联追踪

### 1.9.0 工具沙箱隔离

- 工具进程或受限执行环境的隔离边界
- 文件、网络、超时和资源限制策略
- 默认拒绝的安全配置与跨平台验证

每个版本稳定后同步更新 README，并将对应实验性标记移除。规划中的能力不得描述为当前稳定功能。

版本级任务拆解见 [详细任务书](docs/superpowers/plans/2026-08-06-versioned-development-task-book.md)。
