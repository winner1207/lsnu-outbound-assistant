# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import queue
import threading
from collections.abc import Callable, Iterator
from typing import Any


def sse(event: dict[str, Any]) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


def iter_with_keepalive(producer: Callable[[], Iterator[str]], interval: float = 15.0) -> Iterator[str]:
    """阻塞的上游（识字 / 模型）期间仍向 nginx 推数据，避免 proxy_read_timeout。"""
    q: queue.Queue[tuple[str, object]] = queue.Queue()

    def run() -> None:
        try:
            for item in producer():
                q.put(("data", item))
            q.put(("done", None))
        except Exception as exc:
            q.put(("err", exc))

    threading.Thread(target=run, daemon=True).start()
    last_step = "identify"
    while True:
        try:
            kind, val = q.get(timeout=interval)
        except queue.Empty:
            yield sse({"type": "status", "step": last_step, "message": "仍在处理，请稍候…"})
            continue
        if kind == "data":
            text = str(val)
            line = text.split("\n", 1)[0]
            if line.startswith("data: "):
                try:
                    ev = json.loads(line[6:])
                except json.JSONDecodeError:
                    ev = {}
                if ev.get("step"):
                    last_step = ev["step"]
            yield text
        elif kind == "err":
            yield sse({"type": "error", "message": str(val)})
            return
        else:
            return
