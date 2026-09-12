# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from functools import lru_cache

from app.config import GLOSSARY_PATH

LANGS = ("zh", "en", "ja", "fr", "es", "ko", "th")
CJK = re.compile(r"[\u4e00-\u9fff]+")
FOLD = str.maketrans(
    "頭雲淩師載遊處園樂壽蘇時圓覺羅長門東坡處",
    "头云凌师载游处园乐寿苏时圆觉罗长门东坡处",
)
SKIP_OCR = ("美篇", "美篇号")
SCENES = (
    "leshan_buddha",
    "lingyun",
    "moruo",
    "jiayang_train",
    "xiashan_hu",
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


def all_terms() -> list[dict]:
    return list(load().get("terms") or [])


def term_value(term: dict, lang: str) -> str:
    return (term.get(lang) or term.get("en") or term["zh"]).strip()


def term_table_for_prompt(terms: list[dict]) -> str:
    lines = ["中文 | English | 日本語 | Français | Español | 한국어 | ไทย"]
    for term in terms:
        lines.append(" | ".join(term_value(term, lang) for lang in LANGS))
    return "\n".join(lines)


def fold_zh(text: str) -> str:
    return (text or "").translate(FOLD).strip()


def scene_for_term(term: dict) -> str:
    scene = term.get("scene")
    if scene in SCENES:
        return scene
    return "photo"


def _lev(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(cur[-1] + 1, prev[j] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _names(term: dict) -> list[str]:
    out = [fold_zh(term["zh"])]
    for alias in term.get("aliases_zh") or []:
        out.append(fold_zh(alias))
    uniq, seen = [], set()
    for name in out:
        if name and name not in seen:
            seen.add(name)
            uniq.append(name)
    return uniq


def _blobs(texts: list[str]) -> list[str]:
    blobs: list[str] = []
    seen = set()
    for text in texts:
        if not text or any(skip in text for skip in SKIP_OCR):
            continue
        for run in CJK.findall(text):
            folded = fold_zh(run)
            for blob in (folded, folded[::-1]):
                if blob and blob not in seen:
                    seen.add(blob)
                    blobs.append(blob)
    return blobs


def _score(blob: str, name: str) -> int:
    if not blob or not name:
        return 0
    if blob == name:
        return 100
    if name in blob:
        return 90 + min(len(name), 9)
    if len(blob) >= 2 and blob in name:
        return 70 + min(len(blob), 9)
    if len(name) >= 5 and len(blob) >= 3:
        for i in range(len(name) - 2):
            piece = name[i : i + 3]
            if piece in blob:
                return 55 + min(len(name), 9)
    if len(name) >= 3 and len(blob) >= 3:
        dist = _lev(blob, name)
        if dist == 1:
            return 60
        if dist == 2 and len(name) >= 5:
            return 50
    return 0


def match_terms(texts: list[str]) -> list[tuple[dict, int]]:
    blobs = _blobs(texts)
    scored: list[tuple[int, int, dict]] = []
    for term in all_terms():
        best = 0
        for name in _names(term):
            for blob in blobs:
                best = max(best, _score(blob, name))
        if best:
            scored.append((best, len(term["zh"]), term))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return [(term, score) for score, _, term in scored]
