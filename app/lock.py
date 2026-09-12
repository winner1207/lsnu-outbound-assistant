# -*- coding: utf-8 -*-
from __future__ import annotations

import re


def _variants(term: dict, lang: str) -> list[str]:
    canonical = term[lang]
    aliases = list(term.get(f"aliases_{lang}") or [])
    names = [canonical, *aliases]
    if lang != "zh":
        names.append(term["zh"])
    # 长的先替换，避免短名切开长名
    uniq = []
    seen = set()
    for name in names:
        key = name.strip()
        if key and key.lower() not in seen:
            seen.add(key.lower())
            uniq.append(key)
    uniq.sort(key=len, reverse=True)
    return uniq


def apply_lock(text: str, terms: list[dict], lang: str) -> tuple[str, list[str]]:
    if not text:
        return text, []
    hits: list[str] = []
    out = text
    for term in terms:
        canonical = term[lang]
        for variant in _variants(term, lang):
            if variant == canonical:
                if canonical in out and canonical not in hits:
                    hits.append(canonical)
                continue
            pattern = re.compile(re.escape(variant), re.IGNORECASE if lang != "zh" else 0)
            if pattern.search(out):
                out = pattern.sub(canonical, out)
                if canonical not in hits:
                    hits.append(canonical)
        if canonical in out and canonical not in hits:
            hits.append(canonical)
    return out, hits
