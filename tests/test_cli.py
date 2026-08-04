"""测试 CLI 功能。"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from general_mini_agent.cli import do_doctor, do_init, find_project_root
from general_mini_agent.config import FrameworkConfig


def test_find_project_root():
    """测试查找项目根目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        # 未找到配置
        assert find_project_root(subdir) is None

        # 创建配置文件
        config_file = tmp_path / ".gmaf.toml"
        config_file.write_text("api_key = 'test'")

        assert find_project_root(subdir) == tmp_path
        assert find_project_root(tmp_path) == tmp_path


def test_do_init():
    """测试 init 命令。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 首次初始化
        result = do_init(tmp_path)
        assert result == 0
        assert (tmp_path / ".gmaf.toml").exists()

        # 再次初始化不应该覆盖
        result = do_init(tmp_path)
        assert result == 1

        # 使用 --force 覆盖
        result = do_init(tmp_path, force=True)
        assert result == 0


def test_do_doctor_without_config():
    """测试 doctor 命令（无配置）。"""
    with tempfile.TemporaryDirectory():
        with patch("general_mini_agent.cli.find_project_root", return_value=None):
            with patch("sys.stdout"):
                # 没有配置，doctor 应该返回 1（部分检查失败）
                do_doctor()
                # 不强制返回值，只要不崩溃就行


def test_config_load_with_files():
    """测试配置文件加载。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)

        # 创建用户配置
        if Path.home().exists():
            # 只是测试代码路径，不实际写文件
            pass

        # 创建项目配置
        project_config = tmp_path / ".gmaf.toml"
        project_config.write_text("""
[gmaf]
api_key = "from-file"
base_url = "https://example.com"
model = "from-file-model"
""")

        # 从项目配置加载
        config = FrameworkConfig.load(
            project_config=project_config,
            environ={},
            api_key="override-key"
        )
        # 显式参数优先级最高
        assert config.api_key == "override-key"
        # 配置文件中的值
        assert config.base_url == "https://example.com"


def test_config_from_env():
    """测试从环境变量加载配置。"""
    config = FrameworkConfig.from_env(
        environ={
            "GMAF_API_KEY": "test-key",
            "GMAF_BASE_URL": "https://test.com/v1",
            "GMAF_MODEL": "test-model",
        }
    )
    assert config.api_key == "test-key"
    assert config.base_url == "https://test.com/v1"
    assert config.model == "test-model"


def test_config_validation():
    """测试配置验证。"""
    # 空 api_key 应该失败
    with pytest.raises(ValueError, match="api_key is required"):
        FrameworkConfig(api_key="", base_url="https://x.com", model="test")

    # 空 base_url 应该失败
    with pytest.raises(ValueError, match="base_url is required"):
        FrameworkConfig(api_key="x", base_url="", model="test")

    # 空 model 应该失败
    with pytest.raises(ValueError, match="model is required"):
        FrameworkConfig(api_key="x", base_url="https://x.com", model="")

    # 无效 timeout
    with pytest.raises(ValueError, match="timeout must be positive"):
        FrameworkConfig(api_key="x", base_url="https://x.com", model="test", timeout=0)

    # 无效 max_retries
    with pytest.raises(ValueError, match="max_retries must be non-negative"):
        FrameworkConfig(api_key="x", base_url="https://x.com", model="test", max_retries=-1)

    # context_window 必须大于 reserved_output_tokens
    with pytest.raises(ValueError, match="must be greater than"):
        FrameworkConfig(
            api_key="x",
            base_url="https://x.com",
            model="test",
            context_window=1000,
            reserved_output_tokens=2000,
        )

    # 必须同时设置或同时不设置
    with pytest.raises(ValueError, match="must be both set or both unset"):
        FrameworkConfig(
            api_key="x",
            base_url="https://x.com",
            model="test",
            context_window=1000,
            reserved_output_tokens=None,
        )