# 发布手册

本文档描述 General Mini Agent Framework 的发布流程，供维护者参考。

## 发布前检查

### 1. 工作区状态

确保工作区干净，无未提交的更改：

```bash
git status
git diff --check
```

### 2. 分支与版本确认

- 发布从 `dev` 分支合并到 `main` 分支
- 确认 `pyproject.toml` 中的版本号已更新
- 确认 `CHANGELOG.md` 包含本次版本条目

### 3. 版本号位置

版本号需要同步更新以下文件：

- `pyproject.toml` - `[project]` 表的 `version` 字段
- `CHANGELOG.md` - 版本条目标题
- 测试文件中的版本断言（见下文）

## 离线验证

### 安装开发依赖

```bash
python -m pip install ".[dev,release]"
```

### 运行测试

```bash
python -m pytest tests -v
```

### Lint 检查

```bash
ruff check general_mini_agent tests demo
```

### 字节码编译检查

```bash
python -m compileall -q general_mini_agent demo tests
```

## 发行包验证

### 构建 sdist 和 wheel

```bash
rm -rf dist/
python -m build
```

### 检查发行包元数据

```bash
python -m twine check dist/*
```

### 干净安装验证

创建临时虚拟环境，安装 wheel 并验证：

```powershell
python -m venv C:\tmp\release-venv
C:\tmp\release-venv\Scripts\python -m pip install dist\*.whl
C:\tmp\release-venv\Scripts\python -c "from importlib.metadata import version; from general_mini_agent import Agent, Debate, LLM, MemoryQuery; print(version('general-mini-agent-framework'))"
```

在 Unix 系统上：

```bash
python -m venv /tmp/release-venv
/tmp/release-venv/bin/python -m pip install dist/*.whl
/tmp/release-venv/bin/python -c "from importlib.metadata import version; from general_mini_agent import Agent, Debate, LLM, MemoryQuery; print(version('general-mini-agent-framework'))"
```

输出应为发布版本号（如 `0.4.1`）。

## 合并与打 Tag

### 合并到 main

```bash
git checkout main
git merge dev
git push origin main
```

### 创建版本 Tag

```bash
git tag v0.4.1
git push origin v0.4.1
```

## 约束与故障排查

### 约束

- CI 失败时不得打 tag
- 已推送的错误 tag 不得强制覆盖，应修复后提升补丁版本
- 不提交生成的 `dist/` 目录
- CI 不持有 PyPI token，发布需人工执行

### 常见问题

**pytest 导入了错误的包**

使用 `python -m pytest` 而非直接调用 `pytest`，避免导入 site-packages 中的同名包。

**twine check 失败**

检查 `README.md` 是否使用了 PyPI 不支持的 markdown 扩展语法。

**wheel 安装后导入失败**

确认 `pyproject.toml` 的 `[tool.hatch.build.targets.wheel]` 正确配置了 `packages = ["general_mini_agent"]`。

**版本号不一致**

版本号需在 `pyproject.toml`、`CHANGELOG.md` 和测试断言中同步更新。

## 发布后

1. 确认 GitHub Actions CI 全部通过
2. 如需发布到 PyPI，使用 `twine upload dist/*` 并提供凭据
3. 在 GitHub Releases 创建对应版本的 Release Note