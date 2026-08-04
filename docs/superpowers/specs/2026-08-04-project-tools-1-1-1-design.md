# General Mini Agent Framework 1.1.1 项目工具集设计

## 状态

本设计文档描述 `1.1.1` 项目工具集。需单独完成设计确认、实施计划和验收。

## 背景

`1.1.0` 已建立稳定的 Agent 协议和同步/流式/异步执行器。现在需要提供可供 Agent 使用的项目工具，让 Agent 可以：

- 读取文件内容
- 列出目录文件
- 搜索文本内容
- 写入文件内容
- 编辑文件内容（要求旧文本唯一匹配）
- 运行命令（有超时）

这些工具需要有适当的安全边界：路径限制在 workspace 内，读写能力需要显式开启。

## 目标

### `1.1.1` 目标

- 提供 `ToolRuntimeContext` 上下文对象，包含 workspace 路径、能力开关、限制配置
- 实现只读工具：`read_file`、`list_files`、`glob_files`、`search_text`
- 实现写入工具：`write_file`、`edit_file`
- 实现执行工具：`run_command`
- 所有工具均有测试覆盖，Windows 和 POSIX 行为一致
- 工具不自动向任何 Agent 注册，由调用方显式选用
- 默认关闭 mutation 和 execute 能力

### 非目标

- 不提供图形界面
- 不提供自动确认流程（属于 1.1.2）
- 不提供 CLI（属于 1.1.3）
- 不提供会话恢复（属于 1.1.4）
- 不提供沙箱或隔离机制（属于后续）

## 设计决策

### 方案比较

**方案 A：纯函数工具集**

每个工具是独立的 `@tool` 装饰函数，通过闭包访问上下文。

优点：简单、直接、复用现有工具机制
缺点：上下文难以共享和管理

**方案 B：带上下文的工具集**

工具定义为类，接收 `ToolRuntimeContext` 参数，提供工具方法，然后注册为 `@tool`。

优点：上下文共享清晰，工具可以有状态
缺点：稍微复杂

**决策**：采用方案 A + 上下文对象，使用 `@tool` 装饰器配合闭包访问上下文。提供工厂函数 `create_project_tools(context)` 返回工具列表。

### ToolRuntimeContext 设计

```python
@dataclass(frozen=True)
class ToolRuntimeContext:
    # 工作区路径：工具只能访问此路径下的文件
    workspace: Path
    # 允许读取（默认 True）
    allow_read: bool = True
    # 允许写入（默认 False）
    allow_write: bool = False
    # 允许执行命令（默认 False）
    allow_execute: bool = False
    # 单个文件读取最大字节数（默认 1MB）
    max_file_size: int = 1_048_576
    # 搜索结果最大行数（默认 100）
    max_search_results: int = 100
    # 命令执行超时秒数（默认 30 秒）
    command_timeout: float = 30.0
    # 命令输出最大字节数（默认 100KB）
    max_command_output: int = 102_400
```

### 工具设计

#### 1. read_file

```python
def read_file(path: str, encoding: str = "utf-8") -> str
```

- 读取指定路径文件
- 路径相对于 workspace
- 检查 `allow_read`
- 检查路径是否在 workspace 内（规范化路径后检查前缀）
- 检查文件大小不超过 `max_file_size`
- 返回文件内容字符串

错误码：
- `path_outside_workspace`
- `file_not_found`
- `file_too_large`
- `encoding_error`
- `read_failed`

#### 2. list_files

```python
def list_files(path: str = ".", pattern: str | None = None) -> list[dict]
```

- 列出指定目录的文件和目录
- 可选按 glob 模式过滤
- 返回结构：`[{"name": "file.txt", "type": "file"|"dir", "size": 1234}]`

错误码：
- `path_outside_workspace`
- `dir_not_found`
- `list_failed`

#### 3. glob_files

```python
def glob_files(pattern: str, path: str = ".") -> list[str]
```

- 按 glob 模式搜索文件
- 返回匹配的相对路径列表

错误码：
- `path_outside_workspace`
- `glob_failed`

#### 4. search_text

```python
def search_text(query: str, path: str = ".", include_pattern: str | None = None) -> list[dict]
```

- 在文件中搜索文本
- 支持可选的文件 glob 模式过滤
- 返回结构：`[{"path": "file.txt", "line": 10, "content": "line with text"}]`
- 限制返回 `max_search_results` 行

错误码：
- `path_outside_workspace`
- `search_failed`

#### 5. write_file

```python
def write_file(path: str, content: str, encoding: str = "utf-8") -> str
```

- 写入文件内容
- 路径不存在时创建父目录
- 覆盖已存在的文件
- 检查 `allow_write`

错误码：
- `path_outside_workspace`
- `write_disabled`
- `write_failed`

#### 6. edit_file

```python
def edit_file(path: str, old_text: str, new_text: str, encoding: str = "utf-8") -> str
```

- 编辑文件：将 `old_text` 替换为 `new_text`
- **要求 `old_text` 在文件中唯一匹配**（精确匹配，无歧义）
- 检查 `allow_write`

匹配规则：
- 严格逐字符匹配
- 整个文件范围内查找
- 必须恰好有一个匹配
- 没有匹配或多个匹配都返回错误

错误码：
- `path_outside_workspace`
- `write_disabled`
- `file_not_found`
- `file_too_large`
- `no_match_found`
- `multiple_matches`
- `edit_failed`

#### 7. run_command

```python
def run_command(command: str, args: list[str] | None = None, shell: bool = False) -> dict
```

- 运行命令
- 可选使用 shell 执行
- 超时 `command_timeout` 秒
- 输出限制 `max_command_output` 字节
- 检查 `allow_execute`

返回结构：
```python
{
    "exit_code": int,
    "stdout": str,
    "stderr": str,
    "duration": float,
    "timed_out": bool
}
```

工作目录：workspace

错误码：
- `execute_disabled`
- `command_failed`
- `command_timed_out`
- `output_too_large`

### 路径安全

所有工具使用相同的路径检查逻辑：

```python
def resolve_path(workspace: Path, path: str) -> Path:
    # 规范化路径
    resolved = (workspace / path).resolve()
    # 检查是否在 workspace 内
    if workspace.resolve() not in resolved.parents and resolved != workspace.resolve():
        raise ValueError("path_outside_workspace")
    return resolved
```

### 工厂函数

```python
def create_project_tools(context: ToolRuntimeContext) -> list[Tool]
```

根据上下文配置返回可用的工具列表：
- 只读工具：始终包含（当 `allow_read=True`）
- 写入工具：仅当 `allow_write=True` 时包含
- 执行工具：仅当 `allow_execute=True` 时包含

### 测试策略

#### 单元测试

- 每个工具的正常路径
- 每个工具的错误路径
- 路径安全边界
- 限制配置生效
- Windows 和 POSIX 路径行为一致（使用 `Path` 抽象）

#### 集成测试

- Agent 使用工具调用的完整流程
- 多个工具调用的组合

#### 离线测试

所有默认测试使用临时目录，不访问用户文件系统。

## 文件变更边界

- 新增 `general_mini_agent/tools_project.py`
- 修改 `general_mini_agent/__init__.py`（可选导出工具和上下文）
- 新增 `tests/test_tools_project.py`
- 新增 `demo/tools_demo.py`（可选）

## 公共兼容性

- 保持稳定：工具不自动注册到任何 Agent
- 向后兼容：不改变现有公共 API
- 新增：`ToolRuntimeContext`、`create_project_tools`、以及各工具函数

## 验收标准

1. 所有工具按设计正常工作
2. 路径安全边界正确执行
3. 限制配置正确生效
4. Windows 和 POSIX 路径行为一致
5. 所有测试离线通过
6. 代码通过 lint 检查
7. `write_file`、`edit_file`、`run_command` 默认不可用
8. `edit_file` 正确执行唯一匹配替换

## 实施拆分

按照测试驱动顺序拆分：

1. 先实现 `ToolRuntimeContext` 和路径安全逻辑
2. 实现只读工具：`read_file`、`list_files`、`glob_files`、`search_text`
3. 实现写入工具：`write_file`、`edit_file`
4. 实现执行工具：`run_command`
5. 实现工厂函数 `create_project_tools`
6. 集成测试和验收

每个步骤都有对应的测试。