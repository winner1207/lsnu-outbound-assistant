# -*- coding: utf-8 -*-
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
GLOSSARY_PATH = ROOT / "data" / "glossary.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"
BRAND_DIR = ROOT / "brand"


def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip("'\"")
    return data


ENV = load_env()
LLM_BASE_URL = ENV.get("LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = ENV.get("LLM_API_KEY", "")
LLM_MODEL = ENV.get("LLM_MODEL", "gpt-5.6-terra")
APP_HOST = ENV.get("APP_HOST", "127.0.0.1")
APP_PORT = int(ENV.get("APP_PORT", "8000"))
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
