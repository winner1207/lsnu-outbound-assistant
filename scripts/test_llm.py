# -*- coding: utf-8 -*-
"""连通性探测：读仓库根目录 .env，请求 OpenAI 兼容 chat/completions。"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}")
    data: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


def request_json(url: str, *, method: str, headers: dict[str, str], body: bytes | None, timeout: int) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        return exc.code, payload


def main() -> int:
    env = load_env(ENV_PATH)
    base = env.get("LLM_BASE_URL", "").rstrip("/")
    key = env.get("LLM_API_KEY", "")
    model = env.get("LLM_MODEL", "")
    if not base or not key or not model:
        print("ENV_INCOMPLETE: 需要 LLM_BASE_URL / LLM_API_KEY / LLM_MODEL")
        return 2

    print(f"BASE={base}")
    print(f"MODEL={model}")
    print(f"KEY=sk-...{key[-4:]}" if key.startswith("sk-") else "KEY=set")

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "lsnu-assistant-llm-probe/1.0",
    }

    print("\n--- 1) GET /models ---")
    status, payload = request_json(f"{base}/models", method="GET", headers=headers, body=None, timeout=30)
    print(f"HTTP {status}")
    if isinstance(payload, dict):
        ids = []
        for item in payload.get("data") or []:
            if isinstance(item, dict) and item.get("id"):
                ids.append(item["id"])
        print("models:", ", ".join(ids[:20]) if ids else json.dumps(payload, ensure_ascii=False)[:800])
        model_ok = model in ids if ids else None
        print(f"target_in_list={model_ok}")
    else:
        print(str(payload)[:800])

    print("\n--- 2) POST /chat/completions ---")
    body = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": "只回复一个英文单词：pong"},
                {"role": "user", "content": "ping"},
            ],
            "max_tokens": 32,
            "temperature": 0,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    status, payload = request_json(
        f"{base}/chat/completions",
        method="POST",
        headers=headers,
        body=body,
        timeout=90,
    )
    print(f"HTTP {status}")
    if not isinstance(payload, dict):
        print(str(payload)[:1200])
        return 1

    err = payload.get("error")
    if err:
        print("error:", json.dumps(err, ensure_ascii=False)[:1200])
        return 1

    choices = payload.get("choices") or []
    if not choices:
        print(json.dumps(payload, ensure_ascii=False)[:1200])
        return 1

    msg = choices[0].get("message") or {}
    content = msg.get("content")
    print("content:", content)
    usage = payload.get("usage")
    if usage:
        print("usage:", json.dumps(usage, ensure_ascii=False))
    print("OK")

    print("\n--- 3) POST /chat/completions (image) ---")
    logo = ROOT / "brand" / "f_logo.png"
    if not logo.exists():
        print(f"SKIP no file {logo}")
        return 0
    import base64

    b64 = base64.b64encode(logo.read_bytes()).decode("ascii")
    vision_body = json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "这张图里有没有乐山师范学院的校徽或校名？只答：有 或 没有。",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                    ],
                }
            ],
            "max_tokens": 64,
            "temperature": 0,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    status, payload = request_json(
        f"{base}/chat/completions",
        method="POST",
        headers=headers,
        body=vision_body,
        timeout=120,
    )
    print(f"HTTP {status}")
    if isinstance(payload, dict):
        if payload.get("error"):
            print("vision_error:", json.dumps(payload["error"], ensure_ascii=False)[:1200])
            print("VISION_FAIL")
            return 0
        choices = payload.get("choices") or []
        content = ((choices[0].get("message") or {}).get("content") if choices else None)
        print("vision_content:", content)
        print("VISION_OK" if content else "VISION_EMPTY")
    else:
        print(str(payload)[:1200])
        print("VISION_FAIL")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"EXCEPTION {type(exc).__name__}: {exc}")
        raise
