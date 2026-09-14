# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

UA = {"User-Agent": "lsnu-outbound-assistant/1.0 (landmark-grounding)"}
CTX = ssl.create_default_context()


def _get(url: str, timeout: int = 12) -> dict | list | None:
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def wiki_ground(query: str, *, limit: int = 3) -> str:
    q = " ".join((query or "").split())
    if not q:
        return ""
    search_url = (
        "https://zh.wikipedia.org/w/api.php?"
        + urllib.parse.urlencode(
            {
                "action": "query",
                "list": "search",
                "srsearch": q,
                "srlimit": str(limit),
                "utf8": "1",
                "format": "json",
            }
        )
    )
    payload = _get(search_url)
    hits = ((payload or {}).get("query") or {}).get("search") or []
    titles = [h.get("title") for h in hits if h.get("title")]
    if not titles:
        return ""
    extract_url = (
        "https://zh.wikipedia.org/w/api.php?"
        + urllib.parse.urlencode(
            {
                "action": "query",
                "prop": "extracts",
                "exintro": "1",
                "explaintext": "1",
                "exchars": "380",
                "titles": "|".join(titles[:limit]),
                "utf8": "1",
                "format": "json",
            }
        )
    )
    ext = _get(extract_url)
    pages = ((ext or {}).get("query") or {}).get("pages") or {}
    chunks = []
    for page in pages.values():
        title = page.get("title") or ""
        text = (page.get("extract") or "").replace("\n", " ").strip()
        if title and text:
            chunks.append(f"【{title}】{text}")
    return "\n".join(chunks[:limit])
