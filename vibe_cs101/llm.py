"""Minimal OpenAI-compatible chat/completions client (stdlib only).

Works with any endpoint that speaks the OpenAI chat API with tool calling:
DeepSeek, OpenAI, Moonshot/Kimi, GLM, local servers, ...
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterator

from .config import LLMConfig

TIMEOUT_S = 180
RETRY_DELAY_S = 1.0
# 部分网关（如 Cloudflare WAF）会拦截 Python-urllib 默认 UA 并返回 403
USER_AGENT = "vibe-cs101/1.0"


class LLMError(RuntimeError):
    pass


def _endpoint(cfg: LLMConfig) -> str:
    return f"{cfg.model} @ {cfg.base_url.rstrip('/')}"


def _open(req: urllib.request.Request):
    """urlopen；对瞬时网络错误（DNS 抖动/连接失败/超时）自动重试一次。"""
    try:
        return urllib.request.urlopen(req, timeout=TIMEOUT_S)
    except urllib.error.HTTPError:
        raise  # 服务端已应答，重试无益，交由调用方格式化
    except (urllib.error.URLError, TimeoutError, OSError):
        time.sleep(RETRY_DELAY_S)
        return urllib.request.urlopen(req, timeout=TIMEOUT_S)


def _format_http_error(cfg: LLMConfig, code: int, body: str) -> str:
    msg = f"LLM API HTTP {code} ({cfg.model} @ {cfg.base_url.rstrip('/')}): {body[:500]}"
    if code == 403 and "1010" in body:
        msg += (
            "\n403 error code 1010 通常是网关 WAF（如 Cloudflare）拦截了请求。"
            "请运行 python3 -m vibe_cs101 info 确认当前生效的配置，"
            "并检查 vibe-cs101/.env 与 VIBE_CS101_* 环境变量是否指向预期端点。"
        )
    if code == 524:
        msg += (
            "\n524 表示上游 LLM 网关超时，通常发生在模型开始返回内容之前。"
            "本地服务仍可用；可重试、缩短问题/上下文，或切换更稳定的模型端点。"
        )
    return msg


def _stream_chunk_content(data: str) -> str | None:
    """Extract delta text from one SSE data payload.

    部分网关会发送 choices 为空的 chunk（如流末尾的 usage 统计块），跳过即可。
    """
    try:
        event = json.loads(data)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Unexpected LLM stream chunk: {data[:500]}") from exc
    if not isinstance(event, dict):
        raise LLMError(f"Unexpected LLM stream chunk: {data[:500]}")
    choices = event.get("choices") or []
    if not choices:
        return None
    return choices[0].get("delta", {}).get("content")


def chat(
    cfg: LLMConfig,
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.3,
) -> dict:
    """One chat/completions call; returns the assistant message dict."""
    if not cfg.configured:
        raise LLMError(
            "未配置 LLM API key。请设置 VIBE_CS101_API_KEY（配合 VIBE_CS101_BASE_URL / "
            "VIBE_CS101_MODEL），或设置 DEEPSEEK_API_KEY / OPENAI_API_KEY，"
            "也可写入 vibe-cs101/.env 文件。"
        )
    payload: dict = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        cfg.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with _open(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LLMError(_format_http_error(cfg, exc.code, body)) from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"LLM API request failed ({_endpoint(cfg)}): {exc}") from exc

    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected LLM response: {json.dumps(data)[:500]}") from exc


def stream_chat(
    cfg: LLMConfig,
    messages: list[dict],
    temperature: float = 0.3,
) -> Iterator[str]:
    """Stream assistant text chunks from a chat/completions call without tools."""
    if not cfg.configured:
        raise LLMError(
            "未配置 LLM API key。请设置 VIBE_CS101_API_KEY（配合 VIBE_CS101_BASE_URL / "
            "VIBE_CS101_MODEL），或设置 DEEPSEEK_API_KEY / OPENAI_API_KEY，"
            "也可写入 vibe-cs101/.env 文件。"
        )
    payload: dict = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    req = urllib.request.Request(
        cfg.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.api_key}",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with _open(req) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                content = _stream_chunk_content(data)
                if content:
                    yield content
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise LLMError(_format_http_error(cfg, exc.code, body)) from exc
    except LLMError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"LLM API request failed ({_endpoint(cfg)}): {exc}") from exc
