# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from functools import lru_cache

from app.config import GLOSSARY_PATH

SCENES = ("leshan_buddha", "moruo", "jiayang_train", "campus", "unknown")


@lru_cache(maxsize=1)
def load() -> dict:
    return json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))


def scene_meta(scene: str) -> dict:
    data = load()
    scenes = data.get("scenes") or {}
    return scenes.get(scene) or scenes["unknown"]


def terms_for_scene(scene: str) -> list[dict]:
    data = load()
    packs = set(scene_meta(scene).get("packs") or [])
    return [term for term in data.get("terms") or [] if term.get("pack") in packs]


def term_table_for_prompt(terms: list[dict]) -> str:
    lines = ["中文 | English | 日本語"]
    for term in terms:
        lines.append(f"{term['zh']} | {term['en']} | {term['ja']}")
    return "\n".join(lines)
