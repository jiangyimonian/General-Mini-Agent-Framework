"""测试 LLM 层（响应解析逻辑，不依赖真实 API）"""

import json
import pytest
from core.llm import LLM, LLMConfig, LLMResponse, ToolCall


class TestLLMResponseParsing:
    """测试 _parse_response 的 JSON 解析逻辑"""

    def setup_method(self):
        # 用一个假的 api_key 来初始化（不会真正发请求）
        self.config = LLMConfig(api_key="test-key")
        self.llm = LLM(self.config)

    def test_text_response(self):
        data = {
            "choices": [{
                "message": {"content": "你好！", "role": "assistant"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": "deepseek-chat",
        }
        resp = self.llm._parse_response(data)
        assert resp.content == "你好！"
        assert resp.tool_calls is None
        assert resp.usage["total_tokens"] == 15

    def test_tool_call_response(self):
        data = {
            "choices": [{
                "message": {
                    "content": "我需要计算",
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "call_abc123",
                        "type": "function",
                        "function": {
                            "name": "calculate",
                            "arguments": json.dumps({"expression": "3 + 5"}),
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
            "model": "deepseek-chat",
        }
        resp = self.llm._parse_response(data)
        assert resp.content == "我需要计算"
        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "calculate"
        assert resp.tool_calls[0].arguments == {"expression": "3 + 5"}

    def test_multiple_tool_calls(self):
        data = {
            "choices": [{
                "message": {
                    "content": "同时计算多个",
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "add", "arguments": '{"a":1,"b":2}'},
                        },
                        {
                            "id": "c2",
                            "type": "function",
                            "function": {"name": "multiply", "arguments": '{"a":3,"b":4}'},
                        },
                    ],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {},
            "model": "deepseek-chat",
        }
        resp = self.llm._parse_response(data)
        assert len(resp.tool_calls) == 2
        assert resp.tool_calls[0].name == "add"
        assert resp.tool_calls[1].name == "multiply"

    def test_no_content_no_tool_calls(self):
        """极少数情况：LLM 返回空消息"""
        data = {
            "choices": [{
                "message": {"role": "assistant"},
                "finish_reason": "stop",
            }],
            "usage": {},
            "model": "deepseek-chat",
        }
        resp = self.llm._parse_response(data)
        assert resp.content is None
        assert resp.tool_calls is None

    def test_empty_tool_calls_list(self):
        """工具调用列表为空"""
        data = {
            "choices": [{
                "message": {
                    "content": "好的",
                    "role": "assistant",
                    "tool_calls": [],
                },
                "finish_reason": "stop",
            }],
            "usage": {},
            "model": "deepseek-chat",
        }
        resp = self.llm._parse_response(data)
        assert resp.content == "好的"
        assert resp.tool_calls is None


class TestLLMInit:
    def test_missing_api_key(self):
        with pytest.raises(ValueError, match="api_key"):
            LLM(LLMConfig(api_key=""))

    def test_custom_config(self):
        config = LLMConfig(
            api_key="sk-test",
            base_url="https://custom.com/v1",
            model="custom-model",
            temperature=0.5,
        )
        llm = LLM(config)
        assert llm.config.model == "custom-model"
        assert llm.config.temperature == 0.5
