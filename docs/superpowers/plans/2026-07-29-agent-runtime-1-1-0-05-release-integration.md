# Agent Runtime 1.1.0 Plan 05: Release Integration

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Execute Plans 01–04 first.

**Goal:** 将已经验证的 Agent Runtime 发布为 `1.1.0`，同步修正包元数据、CI、文档、旧命名空间契约，并提供可选真实 API 工具循环冒烟入口。

**Architecture:** 发布层不重新实现 Agent 循环。CI 使用 `general_mini_agent` 构建和 wheel smoke；手动 smoke 使用 `FrameworkConfig`、`LLM`、`Agent` 和一个 calculator 工具；未来 `1.1.1`–`1.1.4` 只保留在 ROADMAP。

**Tech Stack:** Hatchling、`build`、`twine`、GitHub Actions、Python 3.12+。

## Global Constraints

- 版本改为 `1.1.0`，不增加运行时依赖。
- 当前代码和命令不得引用已经删除的 `core` 包；CHANGELOG 中的历史迁移记录可以保留。
- 默认测试不请求网络、不读取真实 API Key。
- wheel smoke 必须从临时环境导入安装后的 `general_mini_agent`。
- live smoke 只能手动显式运行，脚本源码不包含密钥。

## Files

- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/RELEASING.md`
- Modify: `demo/workflow_demo.py`
- Modify: `demo/offline.py`
- Create: `demo/live_agent_smoke.py`
- Modify: `tests/test_docs_contract.py`
- Modify: `tests/test_package_metadata.py`
- Modify: `tests/test_namespace_compat.py`

## Task 5A: Version, Namespace, and Documentation Contracts

- [ ] Update contract tests first: expect `version = "1.1.0"`, import `general_mini_agent`, and remove assertions that the current CI imports `core`.
- [ ] Run:

```bash
python -m pytest tests/test_docs_contract.py tests/test_package_metadata.py tests/test_namespace_compat.py -v
```

Expected: FAIL on current `1.0.0` and old namespace assertions.

- [ ] Set `pyproject.toml` project version to `1.1.0`; leave runtime dependencies unchanged.
- [ ] Replace CI commands:

```yaml
- run: ruff check general_mini_agent tests demo
- run: python -m compileall -q general_mini_agent demo tests
```

- [ ] Replace wheel smoke imports with:

```python
import general_mini_agent
from general_mini_agent import Agent, Debate, LLM, MemoryQuery
assert Path(general_mini_agent.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
```

- [ ] Update README current capability text to describe native tool calls, one assistant message per tool turn, ordered tool execution, sync/stream/async parity, structured tool errors, and no CLI yet.
- [ ] Remove `core` from current README, releasing commands, CI commands, and demo imports/comments. Keep only historical migration notes where they are explicitly labeled historical.
- [ ] Add ROADMAP entries for not-yet-implemented `1.1.1` project tools, `1.1.2` authorization, `1.1.3` CLI, and `1.1.4` sessions/context compaction. Do not describe them as stable features.
- [ ] Add `CHANGELOG.md` section `## [1.1.0]` recording protocol, multi-tool, finish reason, empty response, prompt, namespace and documentation changes.
- [ ] Run `rg -n "core" README.md docs/RELEASING.md ROADMAP.md demo .github tests`; resolve every current-code/command hit and retain only explicitly historical text.
- [ ] Run `python -m pytest tests/test_docs_contract.py tests/test_package_metadata.py tests/test_namespace_compat.py -v`; expect PASS.
- [ ] Commit:

```bash
git add pyproject.toml .github/workflows/ci.yml README.md ROADMAP.md CHANGELOG.md docs/RELEASING.md demo/workflow_demo.py demo/offline.py tests/test_docs_contract.py tests/test_package_metadata.py tests/test_namespace_compat.py
git commit -m "chore: prepare 1.1.0 package and namespace contracts"
```

## Task 5B: Opt-In Live Agent Smoke

- [ ] Add the static contract test:

```python
def test_live_smoke_is_explicit_and_contains_no_real_key():
    smoke = Path("demo/live_agent_smoke.py").read_text(encoding="utf-8")
    assert "GMAF_API_KEY" in smoke
    assert "Agent(" in smoke
    assert "@tool" in smoke
    assert "calculator" in smoke
    assert "sk-" not in smoke
```

- [ ] Run the test and expect failure because the script is absent.
- [ ] Create `demo/live_agent_smoke.py` with a calculator tool and this core flow:

```python
from general_mini_agent import Agent, LLM, LLMConfig, tool
from general_mini_agent.config import FrameworkConfig


@tool(description="Evaluate a simple integer addition")
def calculator(a: int, b: int) -> int:
    return a + b


def main() -> int:
    config = FrameworkConfig.from_env()
    llm = LLM(LLMConfig(
        api_key=config.api_key,
        base_url=config.base_url,
        model=config.model,
        timeout=config.timeout,
        max_retries=config.max_retries,
    ))
    try:
        result = Agent(llm, tools=[calculator], max_iterations=4).run(
            "Use the calculator tool to compute 19 + 23, then explain the result."
        )
        print(result.content)
        print(f"stop_reason={result.stop_reason} iterations={result.iterations}")
        return 0 if result.stop_reason == "completed" else 1
    finally:
        llm.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] Add a docstring requiring `GMAF_API_KEY`, optionally `GMAF_BASE_URL` and `GMAF_MODEL`; do not load `.env` automatically or print configuration values.
- [ ] Document manual commands in README and releasing guide, but keep them outside default offline test commands.
- [ ] Run:

```bash
python -m pytest tests/test_docs_contract.py::test_live_smoke_is_explicit_and_contains_no_real_key -v
python -m compileall -q demo/live_agent_smoke.py
```

- [ ] Commit:

```bash
git add demo/live_agent_smoke.py README.md docs/RELEASING.md tests/test_docs_contract.py
git commit -m "docs: add opt-in live agent smoke test"
```

## Task 5C: Full Offline and Distribution Verification

- [ ] Run the complete offline suite:

```bash
python -m pytest tests -v
```

- [ ] Run code quality and compilation:

```bash
ruff check general_mini_agent tests demo
python -m compileall -q general_mini_agent demo tests
git diff --check
```

- [ ] Build and inspect artifacts:

```bash
python -m pip install ".[dev,release]"
python -m build
python -m twine check dist/*
```

Expected: sdist and wheel build successfully, `twine check` passes, metadata version is `1.1.0`.

- [ ] Install the wheel in a clearly named temporary environment and verify from outside the repository:

```powershell
python -m venv .tmp-wheel-smoke
.tmp-wheel-smoke\Scripts\python -m pip install dist\*.whl
.tmp-wheel-smoke\Scripts\python -c "import general_mini_agent; from general_mini_agent import Agent, Debate, LLM, MemoryQuery; print(general_mini_agent.__file__)"
```

- [ ] Remove only `.tmp-wheel-smoke` after verification; do not remove the repository or unrelated directories.
- [ ] With an explicitly supplied real key, optionally run:

```powershell
$env:GMAF_API_KEY = "your-key-here"
python demo/live_agent_smoke.py
```

Expected: at least one calculator tool call and `stop_reason=completed`. Without a key, record that live smoke was skipped; never claim it passed.
- [ ] Run `git status --short` and `git log --oneline --decorate -20`; the handoff must contain no unreviewed modifications.
- [ ] Commit only any verification-driven documentation correction; do not amend runtime behavior in this release task.

## Handoff

After this document passes, `1.1.0` is ready for release review. The next feature plan must be a new document for `1.1.1` project tools; it must not append new features to this plan.
