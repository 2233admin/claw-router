"""OpenAI <-> Anthropic Messages protocol conversion."""

from __future__ import annotations

import json
import re
import time
import uuid


def openai_to_anthropic(body: dict, target_model: str) -> dict:
    """Convert OpenAI chat completion request to Anthropic messages format."""
    messages = body.get("messages", [])
    system_text = None
    anthropic_msgs = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            if isinstance(content, str):
                system_text = content
            continue

        if isinstance(content, list):
            parts = []
            for part in content:
                if part.get("type") == "text":
                    parts.append({"type": "text", "text": part["text"]})
                elif part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        media_match = re.match(r'data:(image/\w+);base64,(.+)', url)
                        if media_match:
                            parts.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_match.group(1),
                                    "data": media_match.group(2),
                                }
                            })
                    else:
                        parts.append({
                            "type": "image",
                            "source": {"type": "url", "url": url}
                        })
            anthropic_msgs.append({
                "role": "assistant" if role == "assistant" else role,
                "content": parts,
            })
        else:
            anthropic_msgs.append({"role": role, "content": content})

    req = {
        "model": target_model,
        "messages": anthropic_msgs,
        "max_tokens": body.get("max_tokens", 4096),
    }
    if system_text:
        req["system"] = system_text
    if body.get("temperature") is not None:
        req["temperature"] = body["temperature"]
    if body.get("top_p") is not None:
        req["top_p"] = body["top_p"]
    if body.get("stream"):
        req["stream"] = True
    return req


def anthropic_to_openai(resp_data: dict, model: str) -> dict:
    """Convert Anthropic messages response to OpenAI chat completion format."""
    content_blocks = resp_data.get("content", [])
    text = ""
    for block in content_blocks:
        if block.get("type") == "text":
            text += block.get("text", "")

    usage = resp_data.get("usage", {})
    stop_reason = resp_data.get("stop_reason", "stop")
    finish_reason_map = {"end_turn": "stop", "max_tokens": "length", "stop_sequence": "stop"}

    return {
        "id": f"chatcmpl-{resp_data.get('id', uuid.uuid4().hex[:24])}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": text},
            "finish_reason": finish_reason_map.get(stop_reason, "stop"),
        }],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", 0),
            "completion_tokens": usage.get("output_tokens", 0),
            "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
        },
    }


def anthropic_sse_to_openai_sse(
    event_data: str, completion_id: str, model: str
) -> str | None:
    """Convert a single Anthropic SSE event to OpenAI SSE format.

    Returns the SSE string to send, or None if event should be skipped.
    """
    if not event_data or event_data == "[DONE]":
        return "data: [DONE]\n\n"

    try:
        evt = json.loads(event_data)
    except json.JSONDecodeError:
        return None

    evt_type = evt.get("type", "")

    if evt_type == "content_block_delta":
        delta_text = evt.get("delta", {}).get("text", "")
        if delta_text:
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}],
            }
            return f"data: {json.dumps(chunk)}\n\n"

    elif evt_type == "message_stop":
        stop_chunk = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        return f"data: {json.dumps(stop_chunk)}\n\ndata: [DONE]\n\n"

    return None
