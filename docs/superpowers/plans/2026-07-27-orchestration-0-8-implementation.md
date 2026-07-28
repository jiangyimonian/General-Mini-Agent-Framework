# 0.8.0 编排实施计划

> **供 Agent 执行者使用：** 必须使用 `subagent-driven-development`（推荐）或
> `executing-plans` 逐任务实施。使用复选框（`- [ ]`）跟踪进度。

**目标：** 提供可组合、可取消、可观察的串行、有限并行和条件节点，同时保持框架轻量且不引入
工作流 DSL、持久化调度或分布式执行。

**架构：** 新建 `core/workflow.py`，所有节点统一接收 JSON 值和 `RunContext`，返回结构化
`NodeResult`。Agent/Debate 通过适配节点接入；串行传递上一节点值，并行共享同一输入并按声明
顺序汇总结果，条件节点只调用显式 predicate。所有子节点使用统一事件父子 run ID。

**技术栈：** Python 3.12+、asyncio TaskGroup/Semaphore、dataclass、Protocol、JSONValue。

## 全局约束

- 开始前 `0.6.0` 异步取消和 `0.7.0` run ID/事件必须稳定。
- 核心执行接口为异步；同步调用方可自行使用 `asyncio.run()`，本版不提供嵌套事件循环包装。
- 节点输入输出限定为 `JSONValue`，不得在 trace 中保存任意 Python 对象。
- 并行节点必须有正整数并发上限。
- 条件 predicate 是调用方代码，不允许模型动态创建或修改图。
- 不实现循环、重试 DSL、持久化恢复、任务队列、分布式 worker 或可视化编辑器。
- 工作流实例只保存拓扑配置，所有状态属于单次 `run()`。

---

## 文件职责

- `core/workflow.py`：节点协议、结果、组合节点、错误策略和 Workflow 入口。
- `core/workflow_adapters.py`：AsyncAgent、同步 Agent 和 Debate 适配器。
- `tests/test_workflow.py`：顺序、并行、条件、取消、错误和运行隔离。
- `demo/workflow_demo.py`：离线组合示例。

### 任务 1：节点协议、结果与工作流入口

**接口：**

```python
WorkflowStopReason = Literal["completed", "node_error"]

@dataclass(frozen=True)
class NodeResult:
    value: JSONValue | None
    run_id: str
    error_code: str | None = None
    error: str | None = None

class WorkflowNode(Protocol):
    async def run(
        self,
        value: JSONValue,
        *,
        run_context: RunContext,
    ) -> NodeResult: ...

@dataclass
class WorkflowResult:
    value: JSONValue | None
    run_id: str
    node_results: list[NodeResult]
    stop_reason: WorkflowStopReason
    error: str | None = None

class Workflow:
    def __init__(self, root: WorkflowNode, *, event_sink: EventSink | None = None): ...
    async def run(self, value: JSONValue) -> WorkflowResult: ...
```

- [ ] **步骤 1：增加契约和隔离测试**

使用记录型节点验证 root 获得 child context、结果保留 root run ID、两次运行不共享 node_results，
节点返回非 JSON 值时产生 `node_error` 而不是序列化 `repr`。

- [ ] **步骤 2：运行测试并确认失败**

```powershell
python -m pytest tests/test_workflow.py -v
```

- [ ] **步骤 3：实现最小 Workflow**

每次 `run()` 创建新的 root emitter 和结果列表。节点异常转换为脱敏 `node_error`，但
`CancelledError` 原样传播；取消前已完成的 node results 可保留在内部事件中，不返回伪完成结果。

- [ ] **步骤 4：运行并提交**

```powershell
python -m pytest tests/test_workflow.py -v
git add core/workflow.py tests/test_workflow.py
git commit -m "feat: define observable workflow nodes"
```

### 任务 2：串行节点

**接口：**

```python
class SequenceNode:
    def __init__(self, nodes: Sequence[WorkflowNode]) -> None: ...
```

- [ ] **步骤 1：增加串行测试**

三个节点依次把字符串追加标记。断言调用顺序、每个输出成为下一个输入、失败后不调用后续节点、
每个子 run 的 parent 指向 sequence run。

- [ ] **步骤 2：实现显式传递**

构造时拒绝空节点序列。只在节点 `error_code is None` 时继续；最终 value 等于最后成功节点结果。

- [ ] **步骤 3：运行并提交**

```powershell
python -m pytest tests/test_workflow.py -k "sequence" -v
git add core/workflow.py tests/test_workflow.py
git commit -m "feat: compose sequential workflow nodes"
```

### 任务 3：有限并行与错误策略

**接口：**

```python
ParallelErrorPolicy = Literal["fail_fast", "collect_errors"]

class ParallelNode:
    def __init__(
        self,
        nodes: Sequence[WorkflowNode],
        *,
        max_concurrency: int,
        error_policy: ParallelErrorPolicy = "fail_fast",
    ) -> None: ...
```

- [ ] **步骤 1：增加并发上限与顺序测试**

用门闩节点记录同时运行数量，断言不超过 `max_concurrency`；完成顺序故意打乱，最终 value 列表
仍按声明顺序排列。

- [ ] **步骤 2：增加两种错误策略测试**

`fail_fast` 在首个错误后取消未完成 async 节点并传播取消；`collect_errors` 等待全部节点并在
NodeResult 中保留每个错误。两种模式都不得丢失已完成结果。

- [ ] **步骤 3：实现 TaskGroup + Semaphore**

构造时拒绝空节点和非正并发数。不得吞掉 `CancelledError`；同步线程工具的不可强停限制沿用
`0.6.0`，工作流文档不得声称其已终止。

- [ ] **步骤 4：运行并提交**

```powershell
python -m pytest tests/test_workflow.py -k "parallel or concurrency" -v
git add core/workflow.py tests/test_workflow.py
git commit -m "feat: run bounded parallel workflow nodes"
```

### 任务 4：条件路由

**接口：**

```python
WorkflowPredicate = Callable[[JSONValue], bool]

class ConditionalNode:
    def __init__(
        self,
        predicate: WorkflowPredicate,
        when_true: WorkflowNode,
        when_false: WorkflowNode,
    ) -> None: ...
```

- [ ] **步骤 1：增加分支测试**

分别覆盖 true/false，只允许一个分支执行。predicate 抛异常时返回 `node_error`，两个分支都不得
调用；predicate 收到输入的防御性复制。

- [ ] **步骤 2：实现条件节点**

predicate 同步、无框架重试；返回值必须是真实 bool，不接受 truthy 对象。事件记录所选分支名，
不记录完整敏感输入。

- [ ] **步骤 3：运行并提交**

```powershell
python -m pytest tests/test_workflow.py -k "conditional" -v
git add core/workflow.py tests/test_workflow.py
git commit -m "feat: route conditional workflow nodes"
```

### 任务 5：Agent 与 Debate 适配器

**接口：**

```python
class AsyncAgentNode:
    def __init__(self, agent: AsyncAgent) -> None: ...

class AgentNode:
    def __init__(self, agent: Agent) -> None: ...

class DebateNode:
    def __init__(self, debate: Debate) -> None: ...
```

- [ ] **步骤 1：增加适配器测试**

字符串输入分别映射到 AsyncAgent content、同步 Agent content 和 Debate verdict。同步 Agent 通过
`asyncio.to_thread()` 执行；非字符串输入在调用底层组件前返回 `invalid_node_input`。

- [ ] **步骤 2：实现父子上下文和错误映射**

适配器传入 workflow child RunContext。底层非 completed 结果转换成 NodeResult error；保留底层
run ID，不重写 trace 或停止原因。

- [ ] **步骤 3：运行并提交**

```powershell
python -m pytest tests/test_workflow.py tests/test_agent.py tests/test_debate.py -v
git add core/workflow_adapters.py tests/test_workflow.py
git commit -m "feat: adapt agents to workflow nodes"
```

### 任务 6：离线示例、导出和 0.8.0 发布

- [ ] **步骤 1：更新现有版本、导出和文档契约测试**

要求版本 `0.8.0`、导出所有稳定 workflow 类型、README 明确异步入口和非目标。

- [ ] **步骤 2：实现离线工作流 Demo**

使用 `0.7.1` 脚本化模型构建“并行产生两个候选 -> 条件选择是否进入 Debate -> 输出结果”的
小流程，生成 JSON/HTML trace，不访问网络。

- [ ] **步骤 3：更新文档**

PLAN 记录 workflow 只编排节点；ROADMAP 移除串行、并行和条件路由，保留循环、持久化与分布式
为明确非目标或远期；CHANGELOG 记录两种错误策略和取消限制。

- [ ] **步骤 4：完整发布验证**

```powershell
python -m pytest tests -v
python -m compileall -q core demo tests
ruff check core tests demo
python -m build
python -m twine check dist/*
git diff --check
```

- [ ] **步骤 5：提交发布**

```powershell
git add core/__init__.py demo/workflow_demo.py README.md PLAN.md ROADMAP.md CHANGELOG.md pyproject.toml tests/test_docs_contract.py tests/test_package_metadata.py
git commit -m "feat: release lightweight workflows in 0.8.0"
```

## 验收标准

- Workflow、组合节点和适配器实例不保存运行结果，重复/并发运行完全隔离。
- 串行节点严格传递前一结果，错误后不执行后续节点。
- 并行节点从不超过配置并发数，结果始终按声明顺序排列。
- `fail_fast` 和 `collect_errors` 具有不同且文档化的终态；取消不被转换成普通错误。
- 条件节点只执行一个显式分支，predicate 异常不会执行任何分支。
- 所有子节点 run ID 正确关联到 workflow root run ID。
- 非 JSON 节点值和非字符串 Agent 输入在副作用前失败。
- 没有 DSL、循环、持久化、队列或分布式依赖进入稳定 API。
- 离线 Demo、完整测试、trace 导出和发行包验证通过。
