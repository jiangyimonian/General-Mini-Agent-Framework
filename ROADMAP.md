# General Mini Agent Framework 路线图

`1.1.0` 已建立同步、流式和异步路径的标准回合协议。
路线图只记录尚未稳定或仍需实现的能力；当前稳定能力以 [README.md](README.md) 为准。

## 1.1.x 产品化路线

### 1.1.1 项目工具集

- 文件工具：`read_file`、`list_files`/`glob_files`、`search_text`
- 变更工具：`write_file`、`edit_file`（要求显式启用 mutation 能力）
- 命令工具：`run_command`（要求显式启用 execute 能力）
- 共享 `ToolRuntimeContext`，路径必须位于 workspace

### 1.1.2 权限与安全边界

- 授权协议：`allow`、`deny`、`ask`
- 风险类别：`read`、`write`、`execute`、`external`
- 结构化权限请求事件，不直接调用 `input()`
- 路径和能力边界检查

### 1.1.3 即装即用 CLI

- `gmaf` console script
- `--version`、`doctor`、`init`、单次任务和 `chat`
- 配置顺序：命令行 > 项目配置 > 用户配置 > 环境变量 > 默认值

### 1.1.4 长任务与会话能力

- 会话保存与恢复
- 自动上下文压缩
- 任务计划与结构化运行记录
- 严格分离 Conversation Memory、Session Store 和 Trace Store

## 后续：异步扩展

- 异步 Debate 与并行参与者
- 异步长期记忆适配器
- 异步 ChromaDB 集成

## 后续：编排增强

- 循环节点（Loop/While）
- 动态节点（运行时添加）
- 错误重试策略（指数退避）

## 后续：生产就绪

- 请求速率限制
- OpenTelemetry 集成
- 工具沙箱隔离

每个版本稳定后同步更新 README，并将对应实验性标记移除。规划中的能力不得描述为
当前稳定功能。