# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import threading
import uuid
from functools import lru_cache

from app.config import GLOSSARY_PATH

LANGS = ("zh", "en", "ja", "fr", "es", "ko", "th")
CJK = re.compile(r"[\u4e00-\u9fff]+")
FOLD = str.maketrans(
    "頭雲淩師載遊處園樂壽蘇時圓覺羅長門東坡處",
    "头云凌师载游处园乐寿苏时圆觉罗长门东坡处",
)
SKIP_OCR = ("美篇", "美篇号")
PACKS = ("tourism", "campus")
PACK_LABELS = {"tourism": "文旅", "campus": "校园"}
_LOCK = threading.Lock()
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


def inscription_terms() -> list[dict]:
    return [t for t in all_terms() if scene_for_term(t) == "inscription"]


def scene_visual_hints() -> list[tuple[str, str]]:
    data = load()
    out = []
    for meta in (data.get("scenes") or {}).values():
        hint = (meta or {}).get("visual_hint")
        label = (meta or {}).get("label_zh")
        if hint and label:
            out.append((label, hint))
    return out


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


def public_catalog() -> dict:
    data = load()
    scenes = [{"id": key, "label_zh": (val or {}).get("label_zh") or key} for key, val in (data.get("scenes") or {}).items()]
    return {
        "terms": all_terms(),
        "scenes": scenes,
        "packs": [{"id": key, "label_zh": PACK_LABELS[key]} for key in PACKS],
    }


def _read_unlocked() -> dict:
    return json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))


def _write_unlocked(data: dict) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    tmp = GLOSSARY_PATH.with_name(GLOSSARY_PATH.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(GLOSSARY_PATH)
    load.cache_clear()


def _clean_list(values: list | None) -> list[str]:
    out, seen = [], set()
    for raw in values or []:
        item = str(raw).strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _validated(payload: dict, *, old: dict | None = None) -> dict:
    zh = (payload.get("zh") or "").strip()
    if not zh:
        raise ValueError("中文专名不能为空")
    pack = (payload.get("pack") or (old or {}).get("pack") or "tourism").strip()
    if pack not in PACKS:
        raise ValueError("未知词包")
    scene = (payload.get("scene") or "").strip()
    if scene and scene not in SCENES:
        raise ValueError("未知场景")
    term = dict(old or {})
    term["zh"] = zh
    term["pack"] = pack
    for lang in LANGS:
        if lang == "zh":
            continue
        term[lang] = (payload.get(lang) or "").strip()
    term["aliases_zh"] = _clean_list(payload.get("aliases_zh"))
    if scene:
        term["scene"] = scene
    else:
        term.pop("scene", None)
    region = (payload.get("region") or "").strip()
    if region:
        term["region"] = region
    else:
        term.pop("region", None)
    source = (payload.get("source") or "").strip()
    if source:
        term["source"] = source
    else:
        term.pop("source", None)
    reviewer = (payload.get("reviewer") or "").strip()
    if reviewer:
        term["reviewer"] = reviewer
    else:
        term.pop("reviewer", None)
    return term


def create_term(payload: dict) -> dict:
    with _LOCK:
        data = _read_unlocked()
        terms = data.setdefault("terms", [])
        term = _validated(payload)
        if any((item.get("zh") or "").strip() == term["zh"] for item in terms):
            raise ValueError(f"已有专名「{term['zh']}」")
        used = {item.get("id") for item in terms}
        tid = "term-" + uuid.uuid4().hex[:10]
        while tid in used:
            tid = "term-" + uuid.uuid4().hex[:10]
        term["id"] = tid
        terms.append(term)
        _write_unlocked(data)
        return term


def update_term(term_id: str, payload: dict) -> dict:
    with _LOCK:
        data = _read_unlocked()
        terms = data.get("terms") or []
        idx = next((i for i, item in enumerate(terms) if item.get("id") == term_id), None)
        if idx is None:
            raise KeyError("词条不存在")
        term = _validated(payload, old=terms[idx])
        term["id"] = term_id
        if any((item.get("zh") or "").strip() == term["zh"] and item.get("id") != term_id for item in terms):
            raise ValueError(f"已有专名「{term['zh']}」")
        terms[idx] = term
        _write_unlocked(data)
        return term


def delete_term(term_id: str) -> None:
    with _LOCK:
        data = _read_unlocked()
        terms = data.get("terms") or []
        kept = [item for item in terms if item.get("id") != term_id]
        if len(kept) == len(terms):
            raise KeyError("词条不存在")
        data["terms"] = kept
        _write_unlocked(data)


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
