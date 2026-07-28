# 1.0.0 稳定化实施计划

> **供 Agent 执行者使用：** 必须使用 `subagent-driven-development`（推荐）或
> `executing-plans` 逐任务实施。使用复选框（`- [ ]`）跟踪进度。

**目标：** 删除已完成过渡的 `core` 命名空间，冻结正式公共 API、事件/trace schema 和兼容政策，
完成可复现的 `1.0.0` 发布候选验证；本版不增加运行时功能。

**架构：** `general_mini_agent` 成为唯一安装包与导入入口。通过显式公共 API 清单、schema
fixture、迁移文档和 wheel 安装测试锁定兼容边界；实验性兼容导出要么正式稳定，要么在 1.0
前删除，不带入含糊状态。

**技术栈：** Python 3.12+、Hatchling、pytest、Ruff、build、twine。

## 全局约束

- 开始前 `0.9.0` 必须已经发布，并完成至少一个补丁周期或明确的迁移验证窗口。
- `1.0.0` 不增加工具、模型、记忆、事件、HTML、workflow 或 provider 新能力。
- 删除 `core` 是已批准的破坏性变更；分发名仍为 `general-mini-agent-framework`。
- 正式 Python 包只包含 `general_mini_agent`。
- Trace JSON `schema_version = 1` 在整个 1.x 保持可读取；新增字段必须向后兼容。
- 公开异常不得泄露密钥；状态、工具、策略、配置和事件继续保持实例隔离。
- 所有弃用必须在 `0.9.x` 已有 warning 和迁移文档，1.0 不临时新增无过渡删除项。

---

## 文件职责

- `general_mini_agent/__init__.py`：唯一稳定公共导出清单。
- `tests/test_public_api.py`：导出名称、签名与关键默认值快照。
- `tests/fixtures/public_api_1_0.json`：机器可读公共 API 基线。
- `tests/fixtures/trace_schema_v1.json`：1.x 必须可读的 trace 样本。
- `docs/API.md`：稳定 API 分类、生命周期与非稳定入口。
- `docs/COMPATIBILITY.md`：Python、schema、弃用和依赖政策。
- `docs/MIGRATING.md`：从 0.9.x 到 1.0.0 的迁移。
- `core/`：删除。

### 任务 1：公共 API 审计与冻结清单

- [ ] **步骤 1：生成候选导出列表**

从 `general_mini_agent.__all__`、README 稳定 API、PLAN 和现有导出测试生成对照表，按模型、工具、
Agent、上下文、记忆、异步、事件、trace、Debate、workflow、provider/config 分类。

- [ ] **步骤 2：处理实验性兼容导出**

`SlidingWindowMemory`、旧 `LongTermMemory`、旧 HTML 包装函数等只有在 `0.9.x` 已标记稳定时才能
进入 1.0；否则从 `__all__` 删除。每个删除项必须已在 `docs/MIGRATING.md` 给出替代入口。

- [ ] **步骤 3：创建 API fixture**

`public_api_1_0.json` 对每个符号记录名称、kind、所属模块、`inspect.signature()` 字符串和关键
dataclass 默认值。fixture 不记录文档字符串和实现文件行号。

- [ ] **步骤 4：增加快照测试**

测试当前 `__all__` 与 fixture 名称完全相等、没有重复、没有以下划线开头的符号，并逐项核对
模块、类型和签名。差异必须显式更新 fixture，不能自动接受。

- [ ] **步骤 5：运行并提交**

```powershell
python -m pytest tests/test_public_api.py -v
git add general_mini_agent/__init__.py tests/test_public_api.py tests/fixtures/public_api_1_0.json
git commit -m "test: freeze the 1.0 public API"
```

### 任务 2：删除 `core` 兼容命名空间

- [ ] **步骤 1：先更新命名空间测试**

修改 `tests/test_namespace_compat.py`：wheel 中不得出现 `core/`；干净环境中
`import general_mini_agent` 成功；在未安装其他同名包的隔离环境中 `import core` 必须失败。

- [ ] **步骤 2：迁移仓库内全部导入**

使用：

```powershell
rg -n "from core|import core|core\." README.md PLAN.md docs demo tests general_mini_agent
```

除迁移文档中的历史示例和明确失败测试外，预期无匹配。不得用动态 `sys.modules` alias 保留
隐藏兼容。

- [ ] **步骤 3：删除兼容目录并更新构建配置**

删除 `core/`，Hatch wheel packages 只保留 `general_mini_agent`。更新 compileall、Ruff、发布
手册和 CI 路径。

- [ ] **步骤 4：构建并检查 wheel 内容**

```powershell
python -m build
python -m twine check dist/*
python -m pytest tests/test_namespace_compat.py -v
```

预期：wheel 只有正式包；分发版本仍可通过 `importlib.metadata.version()` 读取。

- [ ] **步骤 5：提交**

```powershell
git add -A core general_mini_agent pyproject.toml .github/workflows/ci.yml docs demo tests
git commit -m "refactor: remove the deprecated core namespace"
```

### 任务 3：冻结 Trace schema version 1

- [ ] **步骤 1：创建覆盖型 schema fixture**

fixture 包含同步 Agent、异步工具 timeout、Debate 父子 run、workflow 并行错误和脱敏模型错误。
所有 UUID、UTC 时间和耗时使用固定值，不含密钥。

- [ ] **步骤 2：增加向后读取测试**

当前 `trace_from_json()` 必须读取 fixture 并重新导出等价数据。未知字段在 schema v1 的兼容策略
按 `docs/COMPATIBILITY.md` 明确：读取器忽略未知可选字段，但拒绝未知 schema version 和缺失
必填字段。

- [ ] **步骤 3：增加 HTML 消费测试**

`trace_to_html()` 和 `compare_traces_to_html()` 必须直接消费 fixture 解析结果，确保 1.x trace
稳定性覆盖 JSON 与 HTML 两层。

- [ ] **步骤 4：运行并提交**

```powershell
python -m pytest tests/test_events.py tests/test_trace.py -v
git add tests/fixtures/trace_schema_v1.json tests/test_events.py tests/test_trace.py docs/COMPATIBILITY.md
git commit -m "test: freeze trace schema version 1"
```

### 任务 4：兼容性、API 和迁移文档

- [ ] **步骤 1：编写 `docs/API.md`**

按公共 API fixture 分类列出稳定符号、构造入口、同步/异步关系、异常/停止原因和生命周期。
明确 `general_mini_agent.<module>` 中未导出的对象不属于兼容承诺。

- [ ] **步骤 2：编写 `docs/COMPATIBILITY.md`**

固定以下政策：Python 最低版本的移除需次版本预告；1.x 不删除公共符号；新增可选 dataclass 字段
必须有默认值；trace v1 可读取；弃用至少跨一个次版本；安全修复可收紧错误文本但不泄密。

- [ ] **步骤 3：完成 `docs/MIGRATING.md`**

提供 `core` 到 `general_mini_agent` 的导入替换、旧 HTML API 替代、实验性记忆替代、配置变量
迁移和常见导入冲突排查。所有代码示例必须在文档契约测试中编译。

- [ ] **步骤 4：同步 README、PLAN 和 ROADMAP**

README 面向使用者简述 1.0 稳定范围并链接三份文档；PLAN 描述真实模块边界；ROADMAP 只保留
1.0 后尚未实现的能力，不保留已完成事项。

- [ ] **步骤 5：运行并提交**

```powershell
python -m pytest tests/test_docs_contract.py -v
git add README.md PLAN.md ROADMAP.md docs/API.md docs/COMPATIBILITY.md docs/MIGRATING.md tests/test_docs_contract.py
git commit -m "docs: publish the 1.0 compatibility contract"
```

### 任务 5：发布候选验证

- [ ] **步骤 1：提升版本并更新 CHANGELOG**

`pyproject.toml` 设置 `1.0.0`；CHANGELOG 按“新增、变更、弃用移除、迁移”记录，不把历史版本
全部功能重复列为本版新增。

- [ ] **步骤 2：运行 Python 3.12/3.13 CI 等价验证**

本地运行当前解释器全量测试，CI 必须分别在 3.12 与 3.13 运行。若此时项目已正式扩展 3.14
矩阵，也必须通过，但不得在 1.0 临时扩大支持范围。

- [ ] **步骤 3：完整本地验证**

```powershell
python -m pytest tests -v
python -m compileall -q general_mini_agent demo tests
ruff check general_mini_agent tests demo
python -m build
python -m twine check dist/*
git diff --check
```

- [ ] **步骤 4：干净环境验收**

安装 wheel 后依次运行公共 API 导入、离线 Demo、JSON trace fixture 读取和 workflow 示例；确认
环境中没有 `core` 包目录，输出中没有 DeprecationWarning 或网络请求。

- [ ] **步骤 5：检查制品元数据**

确认分发名、版本、Python 要求、依赖、README 渲染、license、项目 URL 和 wheel tag 正确；sdist
包含测试所需文档但不包含 `.env`、output、缓存、工作树或 API Key。

- [ ] **步骤 6：提交发布候选**

```powershell
git add pyproject.toml CHANGELOG.md tests/test_package_metadata.py
git commit -m "feat: prepare the 1.0.0 release"
```

- [ ] **步骤 7：人工发布门禁**

只有目标分支 CI 全绿、工作区干净、CHANGELOG 日期确定且 wheel 干净安装通过后，才按
`docs/RELEASING.md` 创建带注释的 `v1.0.0` tag。不得由实施 Agent 自动推送或覆盖 tag。

## 验收标准

- wheel 和 sdist 只提供 `general_mini_agent` 正式包，不包含 `core` 或隐藏 alias。
- 所有仓库代码和推荐文档使用新命名空间；历史迁移示例是唯一允许的 `core` 文本。
- `__all__` 与 `public_api_1_0.json` 完全一致，稳定符号、签名和默认值有机器约束。
- Trace schema version 1 fixture 可读取、确定性重导出，并能渲染单运行与对比 HTML。
- README、API、兼容性和迁移文档相互一致，没有规划能力冒充稳定能力。
- 所有旧弃用项均已在 0.9.x 提供过渡；1.0 没有未经预告的额外删除。
- Python 3.12/3.13 CI、完整离线测试、Ruff、编译、sdist/wheel、twine 和干净安装全部通过。
- 离线 Demo 在无 `.env`、无网络环境成功运行。
- 发行制品不包含密钥、缓存、运行输出或开发工作树。
- `v1.0.0` tag 只在全部门禁通过后由维护者人工创建。
