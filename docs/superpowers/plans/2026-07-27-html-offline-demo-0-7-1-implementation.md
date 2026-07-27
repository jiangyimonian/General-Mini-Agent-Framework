# 0.7.1 HTML Trace 与离线示例实施计划

> **供 Agent 执行者使用：** 必须使用 `subagent-driven-development`（推荐）或
> `executing-plans` 逐任务实施。使用复选框（`- [ ]`）跟踪进度。

**目标：** 将实验性 HTML trace 稳定为只消费 `schema_version = 1` JSON trace 的静态报告，
增加过滤与双运行对比，并提供完全离线的框架示例。

**架构：** `core/trace.py` 不再理解 Agent/Debate 内部对象，只渲染 `TraceDocument`。报告继续是
无外部资源的单 HTML 文件；离线 Demo 使用仓库内脚本化模型产生真实 Agent、工具和 Debate
事件，不读取 `.env`、不访问网络。

**技术栈：** Python 3.12+、标准库 HTML/JSON、原生 CSS/JavaScript、pytest。

## 全局约束

- 开始前 `0.7.0` JSON trace schema version 1 必须稳定。
- 不引入 Node、前端构建工具、CDN、外部字体或遥测。
- 报告必须转义所有用户、模型、工具和错误文本。
- 报告必须在断网环境通过本地文件直接打开。
- 过滤只改变可见性，不修改或重新解释原始 trace 数据。
- 对比只接受相同 schema version 的两个文档。
- 不测试 CSS 像素细节；测试数据嵌入、交互状态和 XSS 边界。

---

## 文件职责

- `core/trace.py`：TraceDocument 到自包含 HTML 的渲染和导出。
- `demo/scripted_models.py`：Demo 专用同步、流式和 Debate 脚本模型。
- `demo/offline.py`：一条命令生成单 Agent 与 Debate JSON/HTML。
- `demo/export_demo.py`：迁移到稳定 TraceDocument 输入。
- `tests/test_trace.py`：渲染、过滤数据、对比和转义契约。
- `tests/test_offline_demo.py`：无环境变量、无网络的端到端示例。

### 任务 1：TraceDocument 单运行 HTML

**接口：**

```python
def trace_to_html(
    document: TraceDocument,
    *,
    title: str = "Agent Trace",
) -> str: ...

def export_trace_html(
    document: TraceDocument,
    path: str | Path,
    *,
    title: str = "Agent Trace",
) -> None: ...
```

- [ ] **步骤 1：改写渲染测试输入**

用固定 TraceDocument 替换伪 AgentResult。断言 run ID、事件类型、usage、elapsed、停止原因和
角色名出现在嵌入 JSON 中，且页面不包含 `http://`、`https://`、`<script src=` 或外部 CSS。

- [ ] **步骤 2：增加 XSS 测试**

payload 包含 `</script><script>alert(1)</script>`、HTML 属性和 Unicode；断言原始闭合标签不
出现在 script 数据块，页面仍能解析到完整原文。

- [ ] **步骤 3：运行测试并确认失败**

```powershell
python -m pytest tests/test_trace.py -v
```

- [ ] **步骤 4：实现稳定渲染入口**

删除从任意对象读取 `.trace` 的推断路径。使用安全 JSON 嵌入方式转义 `<`、`>`、`&` 和 Unicode
行分隔符；页面 JavaScript 只从固定数据节点读取文档。

- [ ] **步骤 5：提交**

```powershell
git add core/trace.py tests/test_trace.py
git commit -m "feat: render stable trace documents"
```

### 任务 2：过滤与可扫描视图

- [ ] **步骤 1：定义过滤字段**

页面必须提供事件类型、角色/run、停止原因和“仅错误”四类控件。所有选项从 trace 数据计算，
默认显示全部；无匹配结果时显示空状态，不删除 DOM 数据。

- [ ] **步骤 2：增加数据与交互契约测试**

断言生成 HTML 包含稳定的 `data-event-type`、`data-run-id`、`data-stop-reason`、`data-error`
属性，以及 filter 控件 ID。测试不依赖完整 HTML 字符串快照。

- [ ] **步骤 3：实现原生过滤逻辑**

过滤条件使用 AND 组合，重置按钮恢复全部选项。控件有 `<label>`、键盘焦点和 `aria-live`
结果计数；不得用颜色作为唯一错误标识。

- [ ] **步骤 4：运行并提交**

```powershell
python -m pytest tests/test_trace.py -v
git add core/trace.py tests/test_trace.py
git commit -m "feat: filter HTML trace events"
```

### 任务 3：双运行对比

**接口：**

```python
def compare_traces_to_html(
    baseline: TraceDocument,
    candidate: TraceDocument,
    *,
    title: str = "Trace Comparison",
) -> str: ...
```

- [ ] **步骤 1：增加对比测试**

构造 usage、耗时、错误数、停止原因和 Debate 轮数不同的两个文档。断言报告显示两侧绝对值和
candidate-baseline 差值；不同 schema version 必须抛出 `ValueError`。

- [ ] **步骤 2：实现结构化摘要**

摘要只基于事件 payload 中的稳定字段；缺失数据展示“不可用”，不得按零计算。事件明细使用
并列区域且共享过滤条件，不尝试自动对齐不同模型生成的自然语言内容。

- [ ] **步骤 3：运行并提交**

```powershell
python -m pytest tests/test_trace.py -v
git add core/trace.py tests/test_trace.py
git commit -m "feat: compare HTML trace reports"
```

### 任务 4：完全离线 Demo

**接口：**

```powershell
python demo/offline.py
```

输出：

```text
output/offline-agent.json
output/offline-agent.html
output/offline-debate.json
output/offline-debate.html
```

- [ ] **步骤 1：增加端到端 Demo 测试**

测试清空 DeepSeek/OpenAI 环境变量并 monkeypatch 网络客户端使任何网络访问立即失败，然后在
临时目录调用 `demo.offline.main(output_dir)`。断言四个文件存在、JSON 可导入、HTML 包含对应
root run ID。

- [ ] **步骤 2：实现脚本化模型**

脚本化模型实现项目稳定协议并按队列返回响应；每次调用记录防御性复制的 messages/tools。
它只用于 Demo 和测试，不从 `core` 导出。

- [ ] **步骤 3：实现离线 Agent 与 Debate 场景**

Agent 场景至少包含一个结构化工具调用；Debate 场景包含两个参与者和独立 Judge。两者必须通过
正式 Agent/Debate API 产生事件，禁止直接手写最终 trace 文档。

- [ ] **步骤 4：运行并提交**

```powershell
python -m pytest tests/test_offline_demo.py -v
git add demo/scripted_models.py demo/offline.py tests/test_offline_demo.py
git commit -m "feat: add offline trace demos"
```

### 任务 5：文档与 0.7.1 发布

- [ ] **步骤 1：更新现有契约测试**

要求版本 `0.7.1`、README 提供离线命令和四个输出、PLAN 将 HTML trace 标记为稳定、ROADMAP
移除 HTML 过滤/对比和离线 Mock Demo。

- [ ] **步骤 2：迁移旧 Demo 和兼容入口**

`demo/export_demo.py` 改用 TraceDocument。旧 `render_html(result)` 和 `debate_to_html(result)`
在 `0.7.1` 保留为带 DeprecationWarning 的兼容包装，文档不再推荐。

- [ ] **步骤 3：浏览器冒烟验证**

运行离线 Demo，用本地浏览器检查单运行和对比报告：过滤器可操作、长文本不重叠、移动宽度可
横向滚动对比区域、控制台无错误。保存截图到临时输出，不提交截图。

- [ ] **步骤 4：执行一次完整发布验证**

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
git add core/trace.py demo/export_demo.py README.md PLAN.md ROADMAP.md CHANGELOG.md pyproject.toml tests/test_docs_contract.py tests/test_package_metadata.py
git commit -m "feat: stabilize HTML traces in 0.7.1"
```

## 验收标准

- HTML 渲染器只依赖 TraceDocument/schema version 1，不读取 Agent/Debate 私有结构。
- 单 HTML 文件不包含外部资源，在断网和 `file://` 打开时功能完整。
- 用户、模型、工具和错误文本无法闭合数据节点或执行脚本。
- 事件类型、run/角色、停止原因和错误过滤可组合、可重置、键盘可用。
- 双运行对比正确展示 usage、耗时、错误、停止原因和轮次差异，缺失值不伪装为零。
- 离线 Demo 不读取 `.env`、不访问网络，并通过正式 API 生成四个有效文件。
- 旧 HTML 函数仅作为明确弃用的兼容包装存在。
- 完整测试、浏览器冒烟、发行构建和文档契约全部通过。
