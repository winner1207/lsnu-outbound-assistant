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
