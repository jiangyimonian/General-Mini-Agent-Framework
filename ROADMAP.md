# General Mini Agent Framework 路线图

`1.0.0` 已删除 `core` 命名空间，冻结公共 API。
路线图只记录尚未稳定或仍需实现的能力；当前稳定能力以 [README.md](README.md) 为准。

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