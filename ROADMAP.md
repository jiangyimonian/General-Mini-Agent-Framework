# General Mini Agent Framework 路线图

`0.9.0` 已稳定模型能力适配、统一配置、安全日志和 `general_mini_agent` 命名空间。
路线图只记录尚未稳定或仍需实现的能力；当前稳定能力以 [README.md](README.md) 为准。

## 1.0.0 规划

- 删除 `core` 命名空间，仅保留 `general_mini_agent`
- 冻结公共 API 和 schema
- 完善文档和示例

## 后续：异步扩展

- 异步 Debate 与并行参与者
- 异步长期记忆适配器
- 异步 ChromaDB 集成

## 后续：示例与发布

- 补充 API 文档和常见问题
- 建立变更日志和发布验证
- 整理各稳定版本对应的最小示例

每个版本稳定后同步更新 README，并将对应实验性标记移除。规划中的能力不得描述为
当前稳定功能。
