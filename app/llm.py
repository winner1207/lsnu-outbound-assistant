# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import re
import socket
import ssl
import time
import urllib.error
import urllib.request

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

logger = logging.getLogger(__name__)


def _request(url: str, body: dict, timeout: int) -> dict:
    if not LLM_BASE_URL or not LLM_API_KEY:
        raise RuntimeError("未配置 LLM_BASE_URL / LLM_API_KEY")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "lsnu-outbound-assistant/1.0",
        },
        method="POST",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(raw)
        except json.JSONDecodeError:
            err = raw
        raise RuntimeError(f"LLM HTTP {exc.code}: {err}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("模型响应超时，请稍后再试或换一张更小的图") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        msg = str(reason)
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            raise RuntimeError("模型响应超时，请稍后再试或换一张更小的图") from exc
        raise RuntimeError(f"模型接口连不上：{reason}") from exc
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload


def chat(messages: list[dict], *, max_tokens: int = 1200, timeout: int = 180, retries: int = 1, enable_search: bool = False, enable_thinking: bool | None = None) -> str:
    last = None
    search_on = enable_search
    for attempt in range(retries + 1):
        try:
            body = {
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": max_tokens,
            }
            if search_on:
                body["enable_search"] = True
            if enable_thinking is not None:
                body["enable_thinking"] = enable_thinking
            payload = _request(f"{LLM_BASE_URL}/chat/completions", body, timeout)
            break
        except RuntimeError as exc:
            last = exc
            if search_on and "HTTP 400" in str(exc):
                search_on = False
                continue
            if attempt >= retries or "超时" not in str(exc):
                raise
            time.sleep(1.2)
    else:
        raise last or RuntimeError("模型无返回")
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("模型无返回")
    content = (choices[0].get("message") or {}).get("content") or ""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content).strip()


def parse_json_object(text: str) -> dict:
    raw = text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise RuntimeError(f"模型未返回 JSON：{text[:300]}")
    return json.loads(raw[start : end + 1])


def extract_lang_fields(buf: str, langs: tuple[str, ...] | list[str]) -> dict[str, str]:
    decoder = json.JSONDecoder()
    out: dict[str, str] = {}
    for lang in langs:
        needle = f'"{lang}"'
        idx = 0
        while True:
            pos = buf.find(needle, idx)
            if pos < 0:
                break
            j = pos + len(needle)
            while j < len(buf) and buf[j].isspace():
                j += 1
            if j >= len(buf) or buf[j] != ":":
                idx = pos + 1
                continue
            j += 1
            while j < len(buf) and buf[j].isspace():
                j += 1
            if j >= len(buf):
                break
            try:
                val, _ = decoder.raw_decode(buf, j)
            except json.JSONDecodeError:
                break
            if isinstance(val, str) and val.strip():
                out[lang] = val
            break
    return out


def _delta_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    item = choices[0]
    delta = item.get("delta") or item.get("message") or {}
    content = delta.get("content") or ""
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)


def _stream_request(body: dict, timeout: int) -> urllib.request.Request:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return urllib.request.Request(
        f"{LLM_BASE_URL}/chat/completions",
        data=data,
        headers={
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "lsnu-outbound-assistant/1.0",
        },
        method="POST",
    )


def chat_stream(messages: list[dict], *, max_tokens: int = 1200, timeout: int = 180, enable_search: bool = False, enable_thinking: bool | None = None):
    if not LLM_BASE_URL or not LLM_API_KEY:
        raise RuntimeError("未配置 LLM_BASE_URL / LLM_API_KEY")
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if enable_search:
        body["enable_search"] = True
    if enable_thinking is not None:
        body["enable_thinking"] = enable_thinking
    req = _stream_request(body, timeout)
    ctx = ssl.create_default_context()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
    except urllib.error.HTTPError as exc:
        if enable_search and exc.code == 400:
            body.pop("enable_search", None)
            req = _stream_request(body, timeout)
            try:
                resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
            except urllib.error.HTTPError as exc2:
                exc = exc2
            else:
                exc = None
        if exc is not None:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                err = json.loads(raw)
            except json.JSONDecodeError:
                err = raw
            raise RuntimeError(f"LLM HTTP {exc.code}: {err}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError("模型响应超时，请稍后再试或换一张更小的图") from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        msg = str(reason)
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            raise RuntimeError("模型响应超时，请稍后再试或换一张更小的图") from exc
        raise RuntimeError(f"模型接口连不上：{reason}") from exc

    ctype = (resp.headers.get("Content-Type") or "").lower()
    deadline = time.monotonic() + timeout
    finished = False
    try:
        if "text/event-stream" not in ctype and "json" in ctype:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))
            if (payload.get("choices") or [{}])[0].get("finish_reason") == "length":
                raise RuntimeError("生成内容达到长度上限，未完整返回")
            text = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if text:
                yield str(text)
            return
        buf = b""
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError("模型生成超时，已停止等待")
            chunk = resp.read1(4096) if hasattr(resp, "read1") else resp.read(256)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line.startswith(b"data:"):
                    continue
                data_line = line[5:].strip()
                if data_line == b"[DONE]":
                    return
                try:
                    payload = json.loads(data_line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if payload.get("error"):
                    raise RuntimeError(str(payload["error"]))
                finish_reason = (payload.get("choices") or [{}])[0].get("finish_reason")
                if finish_reason == "length":
                    raise RuntimeError("生成内容达到长度上限，未完整返回")
                if finish_reason == "stop":
                    finished = True
                piece = _delta_text(payload)
                if piece:
                    yield piece
        if not finished:
            raise RuntimeError("模型输出连接中断，内容未完成")
    finally:
        resp.close()


def search_response(prompt: str, mime: str, b64: str) -> tuple[str, list[str]]:
    """Require a provider-confirmed web search; never silently fall back to memory."""
    started = time.monotonic()
    payload = _request(f"{LLM_BASE_URL}/responses", {
        "model": LLM_MODEL,
        "input": [{"role": "user", "content": [
            {"type": "input_text", "text": prompt},
            {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
        ]}],
        "tools": [{"type": "web_search"}],
        "tool_choice": "required",
        "max_tool_calls": 2,
        "enable_thinking": False,
        "max_output_tokens": 1400,
        "store": False,
    }, 90)
    output = payload.get("output") or []
    calls = [item for item in output if item.get("type") == "web_search_call" and item.get("status") == "completed"]
    logger.warning("search request_id=%s elapsed=%.1fs calls=%d status=%s", payload.get("id"), time.monotonic() - started, len(calls), payload.get("status"))
    if not calls:
        raise RuntimeError("未收到阿里云搜索执行记录，地点尚未核验")
    sources = list(dict.fromkeys(
        source["url"] for call in calls for source in (call.get("action") or {}).get("sources", [])
        if isinstance(source.get("url"), str) and source["url"].startswith(("https://", "http://"))
    ))
    if not sources:
        raise RuntimeError("阿里云搜索未返回来源，地点尚未核验")
    if payload.get("status") != "completed":
        raise RuntimeError("搜索核验输出未完成")
    text = "".join(part.get("text", "") for item in output if item.get("type") == "message"
                   for part in item.get("content", []) if part.get("type") == "output_text")
    return text, sources
