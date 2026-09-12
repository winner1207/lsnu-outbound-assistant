# -*- coding: utf-8 -*-
from __future__ import annotations

import re


def _canonical(term: dict, lang: str) -> str:
    return (term.get(lang) or term.get('en') or term['zh']).strip()


def _variants(term: dict, lang: str) -> list[str]:
    canonical = _canonical(term, lang)
    aliases = list(term.get(f'aliases_{lang}') or [])
    names = [canonical, *aliases]
    if lang != 'zh':
        names.append(term['zh'])
        if lang not in ('en',) and term.get('en'):
            names.append(term['en'])
    uniq = []
    seen = set()
    for name in names:
        key = name.strip()
        if not key:
            continue
        folded = key.lower()
        if folded in seen:
            continue
        seen.add(folded)
        uniq.append(key)
    uniq.sort(key=len, reverse=True)
    return uniq


def _overlap(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(not (end <= a or start >= b) for a, b in spans)


def apply_lock(text: str, terms: list[dict], lang: str) -> tuple[str, list[str]]:
    if not text:
        return text, []
    flags = re.IGNORECASE if lang != 'zh' else 0
    matches: list[tuple[int, int, str]] = []
    for term in terms:
        canonical = _canonical(term, lang)
        if not canonical:
            continue
        for variant in _variants(term, lang):
            for found in re.finditer(re.escape(variant), text, flags):
                matches.append((found.start(), found.end(), canonical))
    matches.sort(key=lambda item: (-(item[1] - item[0]), item[0]))
    kept: list[tuple[int, int, str]] = []
    for start, end, canonical in matches:
        if _overlap(start, end, [(a, b) for a, b, _ in kept]):
            continue
        kept.append((start, end, canonical))
    kept.sort(key=lambda item: item[0])
    out = []
    cursor = 0
    hits: list[str] = []
    for start, end, canonical in kept:
        out.append(text[cursor:start])
        out.append(canonical)
        if canonical not in hits:
            hits.append(canonical)
        cursor = end
    out.append(text[cursor:])
    return ''.join(out), hits
