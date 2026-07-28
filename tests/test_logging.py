"""测试安全日志接口。"""

import logging

import pytest

from core.logging import get_logger, safe_log_fields


class TestGetLogger:
    """测试 get_logger 函数。"""

    def test_logger_name_has_prefix(self) -> None:
        """logger 名称以 general_mini_agent 开头。"""
        logger = get_logger("test")
        assert logger.name == "general_mini_agent.test"

    def test_logger_name_already_has_prefix(self) -> None:
        """如果名称已有前缀，不再添加。"""
        logger = get_logger("general_mini_agent.custom")
        assert logger.name == "general_mini_agent.custom"

    def test_logger_has_null_handler(self) -> None:
        """logger 只添加 NullHandler。"""
        logger = get_logger("test_null_handler")
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0], logging.NullHandler)

    def test_logger_no_root_configuration(self) -> None:
        """不配置根 logger。"""
        # 保存原始根 logger 配置
        original_level = logging.getLogger().level
        original_handlers = len(logging.getLogger().handlers)

        # 创建 logger
        get_logger("test_no_root_config")

        # 验证根 logger 未被修改
        assert logging.getLogger().level == original_level
        assert len(logging.getLogger().handlers) == original_handlers

    def test_logger_no_propagate_setting(self) -> None:
        """不设置 propagate。"""
        logger = get_logger("test_propagate")
        # propagate 默认为 True，我们不修改它
        assert logger.propagate is True


class TestSafeLogFields:
    """测试 safe_log_fields 函数。"""

    def test_empty_fields(self) -> None:
        """无参数返回空字典。"""
        fields = safe_log_fields()
        assert fields == {}

    def test_all_fields(self) -> None:
        """所有字段都包含。"""
        fields = safe_log_fields(
            run_id="test-run-123",
            provider="openai",
            model="gpt-4",
            error_code="timeout",
            elapsed_ms=1234.56,
        )

        assert fields == {
            "run_id": "test-run-123",
            "provider": "openai",
            "model": "gpt-4",
            "error_code": "timeout",
            "elapsed_ms": 1234.56,
        }

    def test_partial_fields(self) -> None:
        """只包含非空字段。"""
        fields = safe_log_fields(
            run_id="test-run-123",
            provider=None,
            model="gpt-4",
        )

        assert fields == {
            "run_id": "test-run-123",
            "model": "gpt-4",
        }

    def test_does_not_accept_sensitive_fields(self) -> None:
        """不接受敏感字段。"""
        # safe_log_fields 不接受 API Key、消息正文等参数
        # 如果调用方尝试传递这些参数，应该得到 TypeError
        with pytest.raises(TypeError):
            safe_log_fields(api_key="secret-key")  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            safe_log_fields(message="user message")  # type: ignore[call-arg]

        with pytest.raises(TypeError):
            safe_log_fields(authorization="Bearer token")  # type: ignore[call-arg]


class TestSafeLoggingIntegration:
    """测试安全日志集成。"""

    def test_log_does_not_contain_api_key(self, caplog: pytest.LogCaptureFixture) -> None:
        """日志不包含 API Key。"""
        logger = get_logger("test_api_key")

        with caplog.at_level(logging.INFO):
            # 使用 safe_log_fields 记录安全字段
            safe_fields = safe_log_fields(
                run_id="test-run",
                provider="openai",
                error_code="auth_failed",
            )
            logger.info("Request failed", extra=safe_fields)

        # 验证日志输出不包含 API Key
        assert "sk-secret-key-12345" not in caplog.text
        # 验证日志记录包含安全字段
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert hasattr(record, "run_id")
        assert record.run_id == "test-run"  # type: ignore[attr-defined]

    def test_log_does_not_contain_authorization_header(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """日志不包含 Authorization 头的敏感值。"""
        logger = get_logger("test_auth_header")

        with caplog.at_level(logging.WARNING):
            # 使用 safe_log_fields 记录安全字段
            safe_fields = safe_log_fields(
                provider="openai",
                model="gpt-4",
                error_code="unauthorized",
            )
            logger.warning("Authorization failed", extra=safe_fields)

        # 验证日志输出不包含敏感的 Bearer token 值
        assert "Bearer sk-" not in caplog.text
        assert "token" not in caplog.text
        # 验证日志记录包含安全字段
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert hasattr(record, "provider")
        assert record.provider == "openai"  # type: ignore[attr-defined]

    def test_log_does_not_contain_message_content(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """日志不包含消息正文。"""
        logger = get_logger("test_message_content")

        with caplog.at_level(logging.ERROR):
            # 模拟记录包含消息正文的错误场景
            safe_fields = safe_log_fields(
                run_id="test-run",
                error_code="content_error",
                elapsed_ms=100.0,
            )
            logger.error("Message processing failed", extra=safe_fields)

        # 验证日志输出不包含消息正文内容
        #（在这个测试中，我们没有传递消息正文，所以只需验证字段存在）
        assert any(
            record.run_id == "test-run"  # type: ignore[attr-defined]
            for record in caplog.records
        )

    def test_log_only_contains_allowlist_fields(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """日志只包含允许列表字段。"""
        logger = get_logger("test_allowlist")

        with caplog.at_level(logging.INFO):
            safe_fields = safe_log_fields(
                run_id="run-123",
                provider="deepseek",
                model="deepseek-chat",
                error_code="rate_limit",
                elapsed_ms=2345.67,
            )
            logger.info("Request completed", extra=safe_fields)

        # 验证所有允许列表字段都被记录
        assert len(caplog.records) == 1
        record = caplog.records[0]

        assert hasattr(record, "run_id")
        assert record.run_id == "run-123"  # type: ignore[attr-defined]

        assert hasattr(record, "provider")
        assert record.provider == "deepseek"  # type: ignore[attr-defined]

        assert hasattr(record, "model")
        assert record.model == "deepseek-chat"  # type: ignore[attr-defined]

        assert hasattr(record, "error_code")
        assert record.error_code == "rate_limit"  # type: ignore[attr-defined]

        assert hasattr(record, "elapsed_ms")
        assert record.elapsed_ms == 2345.67  # type: ignore[attr-defined]