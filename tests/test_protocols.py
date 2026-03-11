"""Tests for OpenAI <-> Anthropic protocol conversion."""

import json
import pytest
from claw_router.protocols import openai_to_anthropic, anthropic_to_openai, anthropic_sse_to_openai_sse


class TestOpenAIToAnthropic:
    def test_basic(self):
        body = {
            "model": "test",
            "messages": [{"role": "user", "content": "hello"}],
            "max_tokens": 1000,
        }
        result = openai_to_anthropic(body, "doubao-pro")
        assert result["model"] == "doubao-pro"
        assert result["max_tokens"] == 1000
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "user"
        assert result["messages"][0]["content"] == "hello"

    def test_system_extracted(self):
        body = {
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "hi"},
            ],
        }
        result = openai_to_anthropic(body, "m")
        assert result["system"] == "You are helpful"
        assert len(result["messages"]) == 1

    def test_image_base64(self):
        body = {
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "describe"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc123"}},
            ]}],
        }
        result = openai_to_anthropic(body, "m")
        parts = result["messages"][0]["content"]
        assert parts[1]["type"] == "image"
        assert parts[1]["source"]["type"] == "base64"
        assert parts[1]["source"]["data"] == "abc123"

    def test_image_url(self):
        body = {
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
            ]}],
        }
        result = openai_to_anthropic(body, "m")
        parts = result["messages"][0]["content"]
        assert parts[0]["source"]["type"] == "url"

    def test_stream_flag(self):
        body = {"messages": [{"role": "user", "content": "hi"}], "stream": True}
        result = openai_to_anthropic(body, "m")
        assert result["stream"] is True

    def test_temperature_and_top_p(self):
        body = {"messages": [{"role": "user", "content": "hi"}], "temperature": 0.5, "top_p": 0.9}
        result = openai_to_anthropic(body, "m")
        assert result["temperature"] == 0.5
        assert result["top_p"] == 0.9


class TestAnthropicToOpenAI:
    def test_basic(self):
        resp = {
            "id": "msg_123",
            "content": [{"type": "text", "text": "Hello!"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
            "stop_reason": "end_turn",
        }
        result = anthropic_to_openai(resp, "test-model")
        assert result["object"] == "chat.completion"
        assert result["choices"][0]["message"]["content"] == "Hello!"
        assert result["choices"][0]["finish_reason"] == "stop"
        assert result["usage"]["total_tokens"] == 15

    def test_max_tokens_reason(self):
        resp = {"content": [{"type": "text", "text": "x"}], "stop_reason": "max_tokens", "usage": {}}
        result = anthropic_to_openai(resp, "m")
        assert result["choices"][0]["finish_reason"] == "length"


class TestAnthropicSSEConversion:
    def test_content_delta(self):
        data = json.dumps({"type": "content_block_delta", "delta": {"text": "Hello"}})
        result = anthropic_sse_to_openai_sse(data, "cid-123", "model-1")
        assert result is not None
        assert '"content": "Hello"' in result

    def test_message_stop(self):
        data = json.dumps({"type": "message_stop"})
        result = anthropic_sse_to_openai_sse(data, "cid-123", "model-1")
        assert "finish_reason" in result
        assert "[DONE]" in result

    def test_done_signal(self):
        result = anthropic_sse_to_openai_sse("[DONE]", "cid", "m")
        assert result == "data: [DONE]\n\n"

    def test_empty(self):
        result = anthropic_sse_to_openai_sse("", "cid", "m")
        assert result == "data: [DONE]\n\n"

    def test_unknown_event_skipped(self):
        data = json.dumps({"type": "ping"})
        result = anthropic_sse_to_openai_sse(data, "cid", "m")
        assert result is None

    def test_invalid_json(self):
        result = anthropic_sse_to_openai_sse("not json", "cid", "m")
        assert result is None
