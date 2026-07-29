"""测试 FrameworkConfig 配置加载与校验。"""

import pytest

from general_mini_agent.config import FrameworkConfig


class TestFrameworkConfigPriority:
    """测试配置优先级：显式参数 > 环境变量 > 默认值。"""

    def test_explicit_overrides_have_highest_priority(self) -> None:
        """显式参数优先级最高。"""
        environ = {
            "GMAF_API_KEY": "env-api-key",
            "GMAF_BASE_URL": "https://env.example.com/v1",
            "GMAF_MODEL": "env-model",
        }

        config = FrameworkConfig.from_env(
            environ=environ,
            api_key="explicit-api-key",
            base_url="https://explicit.example.com/v1",
            model="explicit-model",
        )

        assert config.api_key == "explicit-api-key"
        assert config.base_url == "https://explicit.example.com/v1"
        assert config.model == "explicit-model"

    def test_env_vars_have_medium_priority(self) -> None:
        """环境变量优先级居中。"""
        environ = {
            "GMAF_API_KEY": "env-api-key",
            "GMAF_BASE_URL": "https://env.example.com/v1",
            "GMAF_MODEL": "env-model",
            "GMAF_TIMEOUT": "120.0",
            "GMAF_MAX_RETRIES": "5",
        }

        config = FrameworkConfig.from_env(environ=environ)

        assert config.api_key == "env-api-key"
        assert config.base_url == "https://env.example.com/v1"
        assert config.model == "env-model"
        assert config.timeout == 120.0
        assert config.max_retries == 5

    def test_defaults_have_lowest_priority(self) -> None:
        """默认值优先级最低。"""
        config = FrameworkConfig.from_env(
            environ={},
            api_key="test-key",
            base_url="https://test.example.com/v1",
            model="test-model",
        )

        assert config.timeout == 60.0
        assert config.max_retries == 2
        assert config.provider == "openai-compatible"
        assert config.context_window is None
        assert config.reserved_output_tokens is None

    def test_empty_string_treated_as_missing(self) -> None:
        """空字符串视为缺失。"""
        environ = {
            "GMAF_API_KEY": "",
            "GMAF_TIMEOUT": "",
        }

        # api_key 为空字符串时应该使用默认值（空字符串），但会在校验时失败
        with pytest.raises(ValueError, match="api_key is required"):
            FrameworkConfig.from_env(environ=environ)

    def test_invalid_timeout_raises_error(self) -> None:
        """非法数字在客户端创建前失败。"""
        environ = {
            "GMAF_API_KEY": "test-key",
            "GMAF_TIMEOUT": "not-a-number",
        }

        with pytest.raises(ValueError, match="invalid value for GMAF_TIMEOUT"):
            FrameworkConfig.from_env(environ=environ)

    def test_invalid_max_retries_raises_error(self) -> None:
        """非法数字在客户端创建前失败。"""
        environ = {
            "GMAF_API_KEY": "test-key",
            "GMAF_MAX_RETRIES": "not-a-number",
        }

        with pytest.raises(ValueError, match="invalid value for GMAF_MAX_RETRIES"):
            FrameworkConfig.from_env(environ=environ)


class TestFrameworkConfigValidation:
    """测试交叉字段校验。"""

    def test_empty_api_key_raises_error(self) -> None:
        """非空 api_key 校验。"""
        with pytest.raises(ValueError, match="api_key is required and cannot be empty"):
            FrameworkConfig(
                api_key="",
                base_url="https://example.com/v1",
                model="test-model",
            )

    def test_empty_base_url_raises_error(self) -> None:
        """非空 base_url 校验。"""
        with pytest.raises(ValueError, match="base_url is required and cannot be empty"):
            FrameworkConfig(
                api_key="test-key",
                base_url="",
                model="test-model",
            )

    def test_empty_model_raises_error(self) -> None:
        """非空 model 校验。"""
        with pytest.raises(ValueError, match="model is required and cannot be empty"):
            FrameworkConfig(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="",
            )

    def test_non_positive_timeout_raises_error(self) -> None:
        """正 timeout 校验。"""
        with pytest.raises(ValueError, match="timeout must be positive"):
            FrameworkConfig(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                timeout=0.0,
            )

        with pytest.raises(ValueError, match="timeout must be positive"):
            FrameworkConfig(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                timeout=-10.0,
            )

    def test_negative_max_retries_raises_error(self) -> None:
        """非负 retry 校验。"""
        with pytest.raises(ValueError, match="max_retries must be non-negative"):
            FrameworkConfig(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                max_retries=-1,
            )

    def test_context_window_and_reserved_tokens_must_both_be_set(self) -> None:
        """context_window 和 reserved_output_tokens 必须同时提供。"""
        # 只设置 context_window
        with pytest.raises(
            ValueError,
            match="context_window and reserved_output_tokens must be both set or both unset",
        ):
            FrameworkConfig(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                context_window=4096,
            )

        # 只设置 reserved_output_tokens
        with pytest.raises(
            ValueError,
            match="context_window and reserved_output_tokens must be both set or both unset",
        ):
            FrameworkConfig(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                reserved_output_tokens=1024,
            )

    def test_context_window_must_be_greater_than_reserved_tokens(self) -> None:
        """context_window 必须大于 reserved_output_tokens。"""
        # context_window 等于 reserved_output_tokens
        with pytest.raises(ValueError, match="context_window .* must be greater than"):
            FrameworkConfig(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                context_window=1024,
                reserved_output_tokens=1024,
            )

        # context_window 小于 reserved_output_tokens
        with pytest.raises(ValueError, match="context_window .* must be greater than"):
            FrameworkConfig(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                context_window=512,
                reserved_output_tokens=1024,
            )

    def test_valid_context_window_and_reserved_tokens(self) -> None:
        """合法的 context_window 和 reserved_output_tokens。"""
        config = FrameworkConfig(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="test-model",
            context_window=4096,
            reserved_output_tokens=1024,
        )

        assert config.context_window == 4096
        assert config.reserved_output_tokens == 1024

    def test_zero_max_retries_is_valid(self) -> None:
        """max_retries 为 0 是合法的。"""
        config = FrameworkConfig(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="test-model",
            max_retries=0,
        )

        assert config.max_retries == 0


class TestFrameworkConfigSecurity:
    """测试错误消息不泄露敏感信息。"""

    def test_error_message_does_not_expose_api_key(self) -> None:
        """错误消息不包含 api_key 值。"""
        # 空的 api_key
        with pytest.raises(ValueError) as exc_info:
            FrameworkConfig(
                api_key="",
                base_url="https://example.com/v1",
                model="test-model",
            )

        error_msg = str(exc_info.value)
        assert "api_key" in error_msg  # 字段名应该在错误消息中
        assert "test-key" not in error_msg  # api_key 的值不应该在错误消息中

        # 其他校验错误也不应该暴露 api_key
        with pytest.raises(ValueError) as exc_info:
            FrameworkConfig(
                api_key="super-secret-key-12345",
                base_url="https://example.com/v1",
                model="test-model",
                timeout=-1.0,
            )

        error_msg = str(exc_info.value)
        assert "super-secret-key-12345" not in error_msg

    def test_from_env_error_does_not_expose_api_key(self) -> None:
        """from_env 错误消息不包含 api_key 值。"""
        environ = {
            "GMAF_API_KEY": "super-secret-key-12345",
            "GMAF_TIMEOUT": "-10.0",
        }

        with pytest.raises(ValueError) as exc_info:
            FrameworkConfig.from_env(environ=environ)

        error_msg = str(exc_info.value)
        assert "super-secret-key-12345" not in error_msg


class TestFrameworkConfigFrozen:
    """测试配置是不可变的。"""

    def test_config_is_frozen(self) -> None:
        """配置对象应该是不可变的。"""
        config = FrameworkConfig(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="test-model",
        )

        with pytest.raises(AttributeError):
            config.api_key = "new-key"  # type: ignore[misc]

        with pytest.raises(AttributeError):
            config.timeout = 120.0  # type: ignore[misc]


class TestFrameworkConfigDefaults:
    """测试默认值。"""

    def test_default_values(self) -> None:
        """测试默认值。"""
        config = FrameworkConfig(
            api_key="test-key",
            base_url="https://example.com/v1",
            model="test-model",
        )

        assert config.timeout == 60.0
        assert config.max_retries == 2
        assert config.context_window is None
        assert config.reserved_output_tokens is None
        assert config.provider == "openai-compatible"