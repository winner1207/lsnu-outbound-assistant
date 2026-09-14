# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import queue
import threading
import time
from collections.abc import Callable, Iterator
from typing import Any


def sse(event: dict[str, Any]) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


def iter_with_keepalive(producer: Callable[[], Iterator[str]], interval: float = 15.0) -> Iterator[str]:
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
    last_event_at = time.monotonic()
    last_message = "正在处理"
    while True:
        try:
            kind, val = q.get(timeout=interval)
        except queue.Empty:
            waiting = int(time.monotonic() - last_event_at)
            yield sse({"type": "status", "step": last_step, "heartbeat": True, "message": f"{last_message}（本阶段已等待 {waiting} 秒）"})
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
                if ev.get("message"):
                    last_message = str(ev["message"])
                if ev.get("type") == "partial":
                    last_message = "正在生成其余语种，已完成的内容可先阅读"
                last_event_at = time.monotonic()
            yield text
        elif kind == "err":
            yield sse({"type": "error", "message": str(val)})
            return
        else:
            return
