"""Real HTTP/SSE smoke check (calls the configured model and consumes tokens)."""
import argparse
import json
import time
from pathlib import Path

import requests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("image", type=Path)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    events, final = [], None
    with args.image.open("rb") as file:
        with requests.post(args.url.rstrip("/") + "/api/analyze/stream",
                           files={"file": (args.image.name, file, "image/jpeg")},
                           stream=True, timeout=(15, 110)) as response:
            response.raise_for_status()
            for line in response.iter_lines(chunk_size=1):
                if not line.startswith(b"data: "):
                    continue
                event = json.loads(line[6:])
                row = {"seconds": round(time.monotonic() - started, 1), **event}
                events.append(row)
                print(row["seconds"], event["type"], event.get("message", ""), flush=True)
                if event["type"] == "done":
                    final = event
                    break
                if event["type"] == "error":
                    break
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
    assert final, "Missing done event"
    result = final["result"]
    assert args.expected in result["label_zh"], result["label_zh"]
    assert result.get("sources"), "No verified sources"
    assert not final.get("failed_langs"), final["failed_langs"]
    assert all(result["intro"].get(lang) for lang in ("zh", "en", "ja", "fr", "es", "ko", "th"))
    print("PASS", result["label_zh"], flush=True)


if __name__ == "__main__":
    main()
