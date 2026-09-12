# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from functools import lru_cache

from app.config import GLOSSARY_PATH

LANGS = ("zh", "en", "ja", "fr", "es")
SCENES = (
    "leshan_buddha",
    "lingyun",
    "moruo",
    "jiayang_train",
    "campus",
    "inscription",
    "photo",
    "unknown",
)


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))


def scene_meta(scene: str) -> dict:
    data = load()
    scenes = data.get("scenes") or {}
    return scenes.get(scene) or scenes["photo"]


def terms_for_scene(scene: str) -> list[dict]:
    data = load()
    packs = set(scene_meta(scene).get("packs") or ["tourism", "campus"])
    return [term for term in data.get("terms") or [] if term.get("pack") in packs]


def term_value(term: dict, lang: str) -> str:
    return (term.get(lang) or term.get("en") or term["zh"]).strip()


def term_table_for_prompt(terms: list[dict]) -> str:
    lines = ["中文 | English | 日本語 | Français | Español"]
    for term in terms:
        lines.append(" | ".join(term_value(term, lang) for lang in LANGS))
    return "\n".join(lines)
