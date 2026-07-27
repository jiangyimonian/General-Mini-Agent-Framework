# 0.9.0 模型兼容、配置与命名空间迁移实施计划

> **供 Agent 执行者使用：** 必须使用 `subagent-driven-development`（推荐）或
> `executing-plans` 逐任务实施。使用复选框（`- [ ]`）跟踪进度。

**目标：** 用显式能力适配器吸收 OpenAI 兼容服务差异，建立统一配置与安全日志，并把正式导入
命名空间迁移到 `general_mini_agent`，为 `1.0.0` 删除通用顶层包 `core` 提供过渡期。

**架构：** 新建 provider/config/logging 边界，模型客户端只消费已校验配置和适配器；核心 Agent
不包含厂商条件。将实现模块移动到 `general_mini_agent/`，`core/` 变为薄弃用转发层，两个入口
导出同一对象身份。

**技术栈：** Python 3.12+、dataclass、Protocol、标准库 os/logging/warnings、httpx、Hatchling。

## 全局约束

- 开始前 `0.8.0` 必须完成，工作流和事件层不能依赖 `core` 绝对导入。
- 不根据模型名称猜测能力；所有差异来自显式 ProviderCapabilities/Adapter。
- 代码参数优先于 `GMAF_*` 环境变量，缺失值才使用默认值。
- 不自动读取 YAML/TOML/JSON 配置文件，不新增配置解析依赖。
- 日志默认不包含消息正文、工具参数、长期记忆正文、认证头或 API Key。
- 库不得配置根 logger、handler 或全局日志级别。
- `general_mini_agent` 是 `0.9.0` 起唯一推荐入口；`core` 只发出 DeprecationWarning 并保持兼容。
- `1.0.0` 将删除 `core`，README 和 warning 必须给出明确迁移方式。

---

## 文件职责

- `general_mini_agent/providers.py`：能力描述、通用 OpenAI 和 DeepSeek 适配器。
- `general_mini_agent/config.py`：统一配置、环境读取、优先级和校验。
- `general_mini_agent/logging.py`：logger 获取与安全结构化字段 helper。
- `general_mini_agent/` 其余模块：从 `core/` 移动的正式实现。
- `core/`：只保留弃用转发模块，不能拥有独立状态或复制实现。
- `tests/test_providers.py`、`tests/test_config.py`：能力、payload、优先级和脱敏。
- `tests/test_namespace_compat.py`：对象身份、warning 和 wheel 内容。

### 任务 1：ProviderCapabilities 与适配器

**接口：**

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    supports_tools: bool = True
    supports_streaming: bool = True
    supports_stream_usage: bool = False
    supports_parallel_tool_calls: bool = True

class ProviderAdapter(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...
    def prepare_request(self, payload: dict[str, JSONValue]) -> dict[str, JSONValue]: ...
    def normalize_response(self, payload: dict[str, Any]) -> dict[str, Any]: ...

class OpenAICompatibleAdapter: ...
class DeepSeekAdapter: ...
```

- [ ] **步骤 1：增加能力和防御性复制测试**

通用适配器保持标准 payload；DeepSeek 适配器只处理已证实的 stream usage/request 差异。输入
字典在调用后不变，输出不共享嵌套引用。

- [ ] **步骤 2：增加不支持能力测试**

关闭 tools 或 streaming 后，客户端必须在网络请求前抛出带 provider 上下文的
`ModelCapabilityError`，不得静默删除工具或降级成非流式调用。

- [ ] **步骤 3：实现适配器边界**

适配器只转换模型 HTTP payload，不执行工具、不管理 Agent 状态、不读取环境变量。未知响应字段
默认保留给已有解析器，除非与兼容协议明确冲突。

- [ ] **步骤 4：运行并提交**

```powershell
python -m pytest tests/test_providers.py tests/test_llm.py tests/test_async_llm.py -v
git add core/providers.py core/llm.py core/async_llm.py tests/test_providers.py tests/test_llm.py tests/test_async_llm.py
git commit -m "feat: adapt explicit model capabilities"
```

### 任务 2：统一配置加载与校验

**接口：**

```python
@dataclass(frozen=True)
class FrameworkConfig:
    api_key: str
    base_url: str
    model: str
    timeout: float = 60.0
    max_retries: int = 2
    context_window: int | None = None
    reserved_output_tokens: int | None = None
    provider: str = "openai-compatible"

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> FrameworkConfig: ...
```

- [ ] **步骤 1：增加优先级测试**

验证显式 overrides > `GMAF_*` 环境变量 > 默认值；传入 environ 映射而不是修改真实进程环境。
空字符串视为缺失，非法数字在客户端创建前失败。

- [ ] **步骤 2：增加交叉字段校验**

要求非空 api_key/base_url/model、正 timeout、非负 retry；context_window 和 reserved tokens 必须
同时提供，且 window 大于 reserved。错误消息包含字段名但不包含 api_key 值。

- [ ] **步骤 3：迁移 Demo 配置**

Demo 使用 `FrameworkConfig.from_env()`；为现有 `DEEPSEEK_API_KEY` 等变量提供文档化的 Demo
兼容映射，但核心配置只正式支持 `GMAF_*`。

- [ ] **步骤 4：运行并提交**

```powershell
python -m pytest tests/test_config.py tests/test_llm.py tests/test_chat_demo.py -v
git add core/config.py core/llm.py demo tests/test_config.py tests/test_chat_demo.py
git commit -m "feat: load validated framework configuration"
```

### 任务 3：安全日志接口

**接口：**

```python
def get_logger(name: str) -> logging.Logger: ...

def safe_log_fields(
    *,
    run_id: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    error_code: str | None = None,
    elapsed_ms: float | None = None,
) -> dict[str, str | float]: ...
```

- [ ] **步骤 1：增加日志捕获测试**

使用 `caplog` 验证模型请求、工具错误和 workflow 终态只记录 allowlist 字段；构造含 API Key、
Authorization 和消息正文的错误，日志文本不得包含敏感值。

- [ ] **步骤 2：实现 NullHandler 友好边界**

库 logger 命名以 `general_mini_agent` 开头，只添加 `NullHandler`，不设置 propagate、根级别或
formatter。调用方传入 logger 时使用其对象，不写入全局变量。

- [ ] **步骤 3：运行并提交**

```powershell
python -m pytest tests/test_config.py tests/test_events.py tests/test_llm.py -v
git add core/logging.py core/llm.py core/async_llm.py core/events.py tests/test_config.py tests/test_events.py
git commit -m "feat: emit safe framework logs"
```

### 任务 4：迁移正式命名空间

**文件：**
- 创建：`general_mini_agent/`（移动全部正式实现模块）
- 修改：`core/`（弃用转发层）
- 修改：`pyproject.toml`
- 创建：`tests/test_namespace_compat.py`

- [ ] **步骤 1：先增加双入口对象身份测试**

对全部稳定导出断言：

```python
from general_mini_agent import Agent as NewAgent
from core import Agent as LegacyAgent

assert NewAgent is LegacyAgent
```

导入 `core` 必须产生一次可定位到调用方的 DeprecationWarning；导入正式命名空间不得 warning。

- [ ] **步骤 2：增加 wheel 内容测试**

构建 wheel 后断言同时包含 `general_mini_agent/` 和薄 `core/`，正式实现文件只位于新命名空间；
两个包可在干净虚拟环境导入。

- [ ] **步骤 3：移动实现并改为相对导入**

使用文件移动保留历史。所有正式模块内部只使用 `general_mini_agent` 相对导入。`core/__init__.py`
和子模块只 re-export，不复制类、类型别名、注册表或缓存。

- [ ] **步骤 4：更新 Hatchling 包列表**

wheel packages 明确包含 `general_mini_agent` 与 `core`。项目名继续为
`general-mini-agent-framework`，分发名不改变。

- [ ] **步骤 5：运行完整导入回归**

```powershell
python -m pytest tests/test_namespace_compat.py tests -v
```

预期：现有 `core` 测试暂时保持通过，新入口对象身份一致。

- [ ] **步骤 6：提交**

```powershell
git add general_mini_agent core pyproject.toml tests/test_namespace_compat.py
git commit -m "refactor: introduce the general_mini_agent namespace"
```

### 任务 5：导出、迁移文档和 0.9.0 发布

- [ ] **步骤 1：更新所有 Demo 和推荐文档导入**

README、PLAN、RELEASING 和 Demo 全部使用 `general_mini_agent`；新增 `docs/MIGRATING.md`，给出
`from core import X` 到 `from general_mini_agent import X` 的机械替换和 `1.0.0` 删除时间点。

- [ ] **步骤 2：更新版本与契约测试**

版本提升到 `0.9.0`。现有文档契约要求新命名空间、provider/config/logging 能力和弃用说明；
CHANGELOG 用“弃用”章节明确 `core` 尚可用但不再推荐。

- [ ] **步骤 3：更新路线图**

移除模型能力兼容、统一配置和日志已完成项；`1.0.0` 路线明确删除 `core`、冻结公共 API 和 schema。

- [ ] **步骤 4：完整发布验证**

```powershell
python -m pytest tests -v
python -m compileall -q general_mini_agent core demo tests
ruff check general_mini_agent core tests demo
python -m build
python -m twine check dist/*
git diff --check
```

额外在干净环境分别运行：

```python
from general_mini_agent import Agent, AsyncAgent, Workflow
from core import Agent as LegacyAgent
assert Agent is LegacyAgent
```

- [ ] **步骤 5：提交发布**

```powershell
git add README.md PLAN.md ROADMAP.md CHANGELOG.md docs/MIGRATING.md docs/RELEASING.md demo tests pyproject.toml
git commit -m "feat: release provider compatibility in 0.9.0"
```

## 验收标准

- Provider 能力完全由显式 adapter 决定，核心 Agent/Workflow 不包含厂商名称条件分支。
- 不支持的 tools/streaming 能力在网络请求前以 `ModelCapabilityError` 失败。
- 配置优先级固定为显式参数、`GMAF_*` 环境变量、默认值；所有错误不泄露 key。
- 库不配置根 logger，默认日志不包含正文、参数、记忆、认证头或 API Key。
- `general_mini_agent` 是文档、Demo 和新代码的唯一推荐入口。
- `core` 只包含弃用转发层，导出对象与新命名空间对象身份相同且产生 DeprecationWarning。
- wheel 同时包含新命名空间和兼容层，干净安装验证两个入口可用。
- 文档明确 `core` 将在 `1.0.0` 删除，并提供可机械执行的迁移步骤。
- 完整同步、异步、事件、HTML、workflow 与发行测试全部通过。
