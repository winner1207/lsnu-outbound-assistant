# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.request

from app.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL


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


def chat(messages: list[dict], *, max_tokens: int = 1200, timeout: int = 180, retries: int = 1) -> str:
    last = None
    for attempt in range(retries + 1):
        try:
            payload = _request(
                f"{LLM_BASE_URL}/chat/completions",
                {
                    "model": LLM_MODEL,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                },
                timeout,
            )
            break
        except RuntimeError as exc:
            last = exc
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


def chat_stream(messages: list[dict], *, max_tokens: int = 1200, timeout: int = 180):
    if not LLM_BASE_URL or not LLM_API_KEY:
        raise RuntimeError("未配置 LLM_BASE_URL / LLM_API_KEY")
    data = json.dumps(
        {
            "model": LLM_MODEL,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "stream": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
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
    ctx = ssl.create_default_context()
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
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

    ctype = (resp.headers.get("Content-Type") or "").lower()
    try:
        if "text/event-stream" not in ctype and "json" in ctype:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            if payload.get("error"):
                raise RuntimeError(str(payload["error"]))
            text = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            if text:
                yield str(text)
            return
        buf = b""
        while True:
            chunk = resp.read(256)
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
                piece = _delta_text(payload)
                if piece:
                    yield piece
    finally:
        resp.close()
