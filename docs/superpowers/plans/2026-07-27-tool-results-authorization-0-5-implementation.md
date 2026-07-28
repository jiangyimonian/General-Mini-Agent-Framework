# 0.5.0 工具结果与授权实施计划

> **供 Agent 执行者使用：** 必须使用 `subagent-driven-development`（推荐）或
> `executing-plans` 逐任务实施。使用复选框（`- [ ]`）跟踪进度。

**目标：** 在不改变既有字符串工具行为的前提下，稳定 JSON 结构化工具结果和实例级、
fail-closed 的工具授权策略。

**架构：** `core/tools.py` 继续拥有工具元数据、参数校验和执行结果；授权在参数绑定成功后、
工具函数执行前完成。`core/agent.py` 只注入策略并消费统一的 `ToolExecutionResult`，同步与流式
路径不得各自实现序列化或授权。

**技术栈：** Python 3.12+、dataclass、Protocol、标准库 `json`、pytest、Ruff。

## 全局约束

- 开始实施前必须确认 `0.4.1` 已提交且完整验证通过。
- 保留 `Tool.execute(**kwargs) -> str` 和未配置策略时的现有行为。
- 不增加工具超时、线程终止、异步 callable、RBAC 或参数改写。
- 授权策略属于 `ToolRegistry`/Agent 实例，不得使用进程级全局注册表。
- 授权拒绝或策略异常时不得调用工具函数。
- JSON 输出必须使用 `ensure_ascii=False`、`sort_keys=True`、`allow_nan=False`。
- 最多新增 6 个测试函数；相似输入在一个参数化测试中覆盖。
- 每项任务运行聚焦测试，发布任务只运行一次完整测试。

---

## 文件职责

- `core/tools.py`：JSON 值类型、执行结果、授权协议、确定性序列化和注册表执行边界。
- `core/agent.py`：策略注入以及同步/流式 observation、trace 和模型工具消息。
- `core/__init__.py`：稳定公共导出。
- `tests/test_tools.py`：结构化结果、拒绝、fail-closed 和注册表隔离。
- `tests/test_agent.py`：同步/流式 Agent 对新执行结果的一致消费。
- `demo/reasoning.py`：最小授权和结构化工具结果示例。
- `README.md`、`PLAN.md`、`ROADMAP.md`、`CHANGELOG.md`：真实能力和非目标。
- `pyproject.toml`、`tests/test_package_metadata.py`、`tests/test_docs_contract.py`：`0.5.0` 发布契约。

### 任务 1：稳定结构化工具结果

**文件：**
- 修改：`core/tools.py`
- 修改：`tests/test_tools.py`

**接口：**

```python
type JSONValue = str | int | float | bool | None | list[JSONValue] | dict[str, JSONValue]

@dataclass(frozen=True)
class ToolExecutionResult:
    content: str
    value: JSONValue | None = None
    error_code: str | None = None
```

- [ ] **步骤 1：增加一个结构化结果测试函数**

测试同一函数返回嵌套字典时，`value` 保留 JSON 值，`content` 等于确定性 JSON；同一函数内
同时断言字符串返回仍原样保留。预期 JSON：

```python
'{"items":[1,true,null],"status":"ok"}'
```

- [ ] **步骤 2：增加一个非法结果测试函数**

使用 `object()`、`float("nan")` 和包含非字符串键的字典作为参数化输入，全部断言：

```python
result.error_code == "serialization_failed"
result.content == "tool result is not valid JSON"
result.value is None
```

- [ ] **步骤 3：运行测试并确认失败**

```powershell
python -m pytest tests/test_tools.py -k "structured or serialization" -v
```

预期：因 `ToolExecutionResult.value` 和 JSON 序列化尚未实现而失败。

- [ ] **步骤 4：实现递归 JSON 校验与确定性序列化**

实现私有 `_serialize_result(value: Any) -> ToolExecutionResult`。字符串的 `content` 保持原值；
其他合法 JSON 值使用 `json.dumps()` 生成紧凑文本。拒绝非字符串对象键、NaN、Infinity、
不可序列化对象和递归容器，不得退回 `repr()`。

- [ ] **步骤 5：运行工具测试**

```powershell
python -m pytest tests/test_tools.py -v
```

预期：全部通过。

- [ ] **步骤 6：提交**

```powershell
git add core/tools.py tests/test_tools.py
git commit -m "feat: preserve structured tool results"
```

### 任务 2：实例级工具授权

**文件：**
- 修改：`core/tools.py`
- 修改：`tests/test_tools.py`

**接口：**

```python
@dataclass(frozen=True)
class ToolAuthorizationRequest:
    name: str
    arguments: dict[str, Any]

@dataclass(frozen=True)
class ToolAuthorizationDecision:
    allowed: bool
    reason: str | None = None

class ToolAuthorizationPolicy(Protocol):
    def authorize(
        self,
        request: ToolAuthorizationRequest,
    ) -> ToolAuthorizationDecision: ...

ToolRegistry(
    tools: Iterable[Tool | Callable[..., Any]] = (),
    *,
    authorization_policy: ToolAuthorizationPolicy | None = None,
)
```

- [ ] **步骤 1：增加拒绝和策略异常测试函数**

同一测试分别使用返回 `allowed=False` 的策略和抛出 `RuntimeError` 的策略。断言工具调用计数
保持零，错误码分别为 `permission_denied` 和 `authorization_error`，模型可见文本只包含通用
描述，不包含策略异常内容。

- [ ] **步骤 2：增加注册表隔离测试函数**

两个注册表注册同名工具，一个允许、一个拒绝。分别执行后断言允许方有副作用、拒绝方没有，
且策略调用记录不交叉。

- [ ] **步骤 3：运行聚焦测试并确认失败**

```powershell
python -m pytest tests/test_tools.py -k "authorization or policy" -v
```

预期：构造参数和授权协议尚不存在。

- [ ] **步骤 4：实现 fail-closed 授权顺序**

`ToolRegistry.execute()` 必须依次执行：查找工具、绑定参数、构造防御性复制的请求、调用策略、
调用工具、序列化结果。策略拒绝返回 `permission_denied`；策略抛出异常返回
`authorization_error`；两者均不得泄露 reason 或异常正文。

- [ ] **步骤 5：运行工具测试**

```powershell
python -m pytest tests/test_tools.py -v
```

预期：全部通过。

- [ ] **步骤 6：提交**

```powershell
git add core/tools.py tests/test_tools.py
git commit -m "feat: authorize tool calls per registry"
```

### 任务 3：同步和流式 Agent 集成

**文件：**
- 修改：`core/agent.py`
- 修改：`tests/test_agent.py`

**接口：**

```python
Agent(
    llm: ChatModel,
    tools: list[Tool | Callable[..., Any]] | None = None,
    ...,
    tool_authorization_policy: ToolAuthorizationPolicy | None = None,
)
```

- [ ] **步骤 1：增加同步授权恢复测试函数**

脚本化模型先请求被拒工具，再根据 `permission_denied` observation 给出最终答案。断言工具未
执行、trace 含错误码、第二次模型请求收到通用拒绝文本、Agent 最终 `completed`。

- [ ] **步骤 2：增加流式结构化结果测试函数**

流式模型请求返回嵌套字典的工具，然后完成回答。断言公开 observation 事件、trace 和下一次
模型请求中的 tool message 使用完全相同的确定性 JSON 文本。

- [ ] **步骤 3：运行聚焦测试并确认失败**

```powershell
python -m pytest tests/test_agent.py -k "authorization or structured_tool" -v
```

预期：Agent 构造器尚不能注入策略，或仍使用旧字符串化结果。

- [ ] **步骤 4：只通过注册表集成新能力**

Agent 构造时把策略传给自己的 `ToolRegistry`。同步和流式循环继续调用
`registry.execute()`，不得复制授权或 JSON 序列化逻辑。所有错误继续作为 observation
返回模型，不新增 Agent stop reason。

- [ ] **步骤 5：运行 Agent 与工具测试**

```powershell
python -m pytest tests/test_tools.py tests/test_agent.py -v
```

预期：全部通过。

- [ ] **步骤 6：提交**

```powershell
git add core/agent.py tests/test_agent.py
git commit -m "feat: enforce tool authorization in agents"
```

### 任务 4：稳定导出、示例和 0.5.0 发布

**文件：**
- 修改：`core/__init__.py`
- 修改：`demo/reasoning.py`
- 修改：`README.md`
- 修改：`PLAN.md`
- 修改：`ROADMAP.md`
- 修改：`CHANGELOG.md`
- 修改：`pyproject.toml`
- 修改：`tests/test_docs_contract.py`
- 修改：`tests/test_package_metadata.py`

**稳定导出：** `JSONValue`、`ToolExecutionResult`、`ToolAuthorizationRequest`、
`ToolAuthorizationDecision`、`ToolAuthorizationPolicy`。

- [ ] **步骤 1：先更新现有导出、文档和版本契约测试**

将现有版本断言改为 `0.5.0`，在现有公共导出测试中加入五个新符号，在现有 README 契约中
要求出现“结构化工具结果”“工具授权”和“不提供同步强制终止”。不新增独立文档测试模块。

- [ ] **步骤 2：运行契约测试并确认失败**

```powershell
python -m pytest tests/test_package_metadata.py tests/test_docs_contract.py -v
```

预期：版本、导出和文档尚未更新。

- [ ] **步骤 3：更新导出、Demo 和文档**

Demo 使用一个只允许指定参数的本地策略和返回字典的工具。README 说明字符串兼容、JSON
序列化和 fail-closed 行为；PLAN 记录模块边界；ROADMAP 删除已完成条目并保留工具 timeout、
取消和异步；CHANGELOG 只记录本版真实变化。

- [ ] **步骤 4：提升版本并运行契约测试**

将 `pyproject.toml` 版本设置为 `0.5.0`，运行：

```powershell
python -m pytest tests/test_package_metadata.py tests/test_docs_contract.py -v
```

预期：全部通过。

- [ ] **步骤 5：执行一次完整发布验证**

```powershell
python -m pytest tests -v
python -m compileall -q core demo tests
ruff check core tests demo
python -m build
python -m twine check dist/*
git diff --check
```

预期：171 项既有测试及本版新增测试全部通过，其他命令退出码为零。

- [ ] **步骤 6：提交发布**

```powershell
git add core/__init__.py demo/reasoning.py README.md PLAN.md ROADMAP.md CHANGELOG.md pyproject.toml tests/test_docs_contract.py tests/test_package_metadata.py
git commit -m "feat: release structured and authorized tools in 0.5.0"
```

## 验收标准

- 未配置策略时，现有字符串工具调用、同步 Agent 和流式 Agent 行为保持兼容。
- 字符串结果原样传给模型；合法 JSON 值保存在 `value` 并生成确定性 JSON `content`。
- 非法 JSON 值返回 `serialization_failed`，不包含对象 `repr` 或内存地址。
- 未知工具和无效参数不会调用授权策略；合法参数在工具副作用前完成授权。
- 策略拒绝返回 `permission_denied`，策略异常返回 `authorization_error`，两者均 fail closed。
- 策略、工具和执行记录保持 Agent/注册表实例隔离。
- 同步与流式 observation、trace 和模型 tool message 对同一结果完全一致。
- 新稳定符号从 `core` 导出，文档明确不支持同步强制终止、timeout 和取消。
- 完整离线测试、Ruff、编译、sdist/wheel 和干净安装验证通过。
