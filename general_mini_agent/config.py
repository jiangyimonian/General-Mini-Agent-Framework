"""统一配置加载与校验。

配置优先级（从高到低）：
1. 命令行参数/显式参数
2. 项目配置文件 (./.gmaf.toml)
3. 用户配置文件 (~/.config/gmaf/config.toml)
4. 环境变量 (GMAF_*)
5. 默认值
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    # Python 3.11-
    import tomli as tomllib


@dataclass(frozen=True)
class FrameworkConfig:
    """框架配置。

    所有配置项优先级：显式参数 > GMAF_* 环境变量 > 默认值。
    """

    api_key: str
    base_url: str
    model: str
    timeout: float = 60.0
    max_retries: int = 2
    context_window: int | None = None
    reserved_output_tokens: int | None = None
    provider: str = "openai-compatible"

    def __post_init__(self) -> None:
        """交叉字段校验。"""
        # 非空校验
        if not self.api_key:
            raise ValueError("api_key is required and cannot be empty")
        if not self.base_url:
            raise ValueError("base_url is required and cannot be empty")
        if not self.model:
            raise ValueError("model is required and cannot be empty")

        # 数值范围校验
        if self.timeout <= 0:
            raise ValueError(f"timeout must be positive, got {self.timeout}")
        if self.max_retries < 0:
            raise ValueError(f"max_retries must be non-negative, got {self.max_retries}")

        # context_window 和 reserved_output_tokens 必须同时提供
        if (self.context_window is None) != (self.reserved_output_tokens is None):
            raise ValueError(
                "context_window and reserved_output_tokens must be both set or both unset"
            )

        # context_window 必须大于 reserved_output_tokens
        if (
            self.context_window is not None
            and self.reserved_output_tokens is not None
            and self.context_window <= self.reserved_output_tokens
        ):
            raise ValueError(
                f"context_window ({self.context_window}) must be greater than "
                f"reserved_output_tokens ({self.reserved_output_tokens})"
            )

    @classmethod
    def from_env(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> FrameworkConfig:
        """从环境变量和显式参数创建配置。

        优先级：显式参数 > GMAF_* 环境变量 > 默认值。

        Args:
            environ: 环境变量映射，None 表示使用 os.environ
            **overrides: 显式参数，优先级最高

        Returns:
            FrameworkConfig 实例

        Raises:
            ValueError: 配置校验失败
        """
        env = environ if environ is not None else os.environ

        # 辅助函数：获取配置值
        def get_value(name: str, env_key: str, default: Any) -> Any:
            # 最高优先级：显式参数
            if name in overrides:
                return overrides[name]
            # 次优先级：环境变量
            env_value = env.get(env_key, "")
            if env_value:
                # 类型转换
                if name in ("timeout",):
                    try:
                        return float(env_value)
                    except ValueError:
                        raise ValueError(
                            f"invalid value for {env_key}: {env_value!r}"
                        )
                elif name in ("max_retries", "context_window", "reserved_output_tokens"):
                    try:
                        return int(env_value)
                    except ValueError:
                        raise ValueError(
                            f"invalid value for {env_key}: {env_value!r}"
                        )
                else:
                    return env_value
            # 最低优先级：默认值
            return default

        # 获取所有配置值
        api_key = get_value("api_key", "GMAF_API_KEY", "")
        base_url = get_value("base_url", "GMAF_BASE_URL", "https://api.openai.com/v1")
        model = get_value("model", "GMAF_MODEL", "gpt-3.5-turbo")
        timeout = get_value("timeout", "GMAF_TIMEOUT", 60.0)
        max_retries = get_value("max_retries", "GMAF_MAX_RETRIES", 2)
        context_window = get_value("context_window", "GMAF_CONTEXT_WINDOW", None)
        reserved_output_tokens = get_value(
            "reserved_output_tokens", "GMAF_RESERVED_OUTPUT_TOKENS", None
        )
        provider = get_value("provider", "GMAF_PROVIDER", "openai-compatible")

        # 构造配置对象（在 __post_init__ 中进行校验）
        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            timeout=timeout,
            max_retries=max_retries,
            context_window=context_window,
            reserved_output_tokens=reserved_output_tokens,
            provider=provider,
        )

    @classmethod
    def load(
        cls,
        *,
        project_config: Path | None = None,
        user_config: Path | None = None,
        environ: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> FrameworkConfig:
        """加载配置，支持配置文件、环境变量和显式参数。

        优先级（从高到低）：
        1. 显式参数 (**overrides)
        2. 项目配置文件 (./.gmaf.toml)
        3. 用户配置文件 (~/.config/gmaf/config.toml)
        4. 环境变量 (GMAF_*)
        5. 默认值

        Args:
            project_config: 项目配置文件路径，None 表示自动探测
            user_config: 用户配置文件路径，None 表示自动探测
            environ: 环境变量映射，None 表示使用 os.environ
            **overrides: 显式参数，优先级最高

        Returns:
            FrameworkConfig 实例

        Raises:
            ValueError: 配置校验失败
        """
        environ = environ if environ is not None else os.environ
        config_values: dict[str, Any] = {}

        # 1. 加载用户配置
        user_cfg_path = user_config
        if user_cfg_path is None:
            if sys.platform == "win32":
                app_data = environ.get("APPDATA")
                if app_data:
                    user_cfg_path = Path(app_data) / "gmaf" / "config.toml"
            else:
                xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "~/.config")
                user_cfg_path = Path(xdg_config_home).expanduser() / "gmaf" / "config.toml"
        if user_cfg_path and user_cfg_path.exists():
            user_cfg = _load_toml_config(user_cfg_path)
            config_values.update(user_cfg)

        # 2. 加载项目配置
        project_cfg_path = project_config
        if project_cfg_path is None:
            project_cfg_path = Path.cwd() / ".gmaf.toml"
        if project_cfg_path.exists():
            project_cfg = _load_toml_config(project_cfg_path)
            config_values.update(project_cfg)

        # 3. 环境变量已在 from_env 中处理
        # 4. 显式参数已在 from_env 中处理

        # 合并到 overrides（注意：config_values 优先级低于显式 overrides）
        merged_overrides: dict[str, Any] = {}
        merged_overrides.update(config_values)
        merged_overrides.update(overrides)

        return cls.from_env(environ=environ, **merged_overrides)


def _load_toml_config(path: Path) -> dict[str, Any]:
    """加载 TOML 配置文件。

    Args:
        path: 配置文件路径

    Returns:
        配置字典，空字典表示加载失败或文件为空
    """
    try:
        content = path.read_text(encoding="utf-8")
        data = tomllib.loads(content)
        return data.get("gmaf", data)  # 支持有或没有 [gmaf] 顶层
    except Exception:
        return {}


def find_project_root(start_path: Path | None = None) -> Path | None:
    """从当前目录向上查找项目根目录（包含 .gmaf.toml 的目录）。

    Args:
        start_path: 起始路径，None 表示当前目录

    Returns:
        项目根目录路径，None 表示未找到
    """
    path = (start_path or Path.cwd()).resolve()
    while True:
        if (path / ".gmaf.toml").exists():
            return path
        parent = path.parent
        if parent == path:  # 到达文件系统根
            return None
        path = parent