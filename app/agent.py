# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
import uuid
from typing import Any

from app import glossary, llm, search
from app.lock import apply_lock

SESSIONS: dict[str, dict[str, Any]] = {}
MAX_SESSIONS = 40
LANGS = glossary.LANGS

IDENT_PROMPT = """你是通用讲解 Agent 的「识地」模块。只看用户此刻上传的这一张图。
任务：抽出可用来检索地名的视觉指纹，并给出最可能的世界著名景点候选。不是从我们的测试图库配对。

请抓这些可区分特征：地貌（锥状喀斯特峰林 / 峰丛 / 丹霞 / 冰川 / 海岸）、农田形态（同心圆漏斗田 / 长条梯田 / 平坝）、建筑样式、题刻文字、独特构图。
- 锥状喀斯特峰林 + 山间盆地同心圆稻田（漏斗/天坑状田心）：中国贵州兴义万峰林「八卦田」是最著名匹配之一；广西/云南峰林农田也要列入候选并说明差异。
- 长条状梯田爬坡：更像元阳、龙脊，而不是八卦田。
- 有足够把握就点名，不要因为怕说错而只写「山地田园」。

只返回 JSON：
{
  "in_photo": "一句话描述所见",
  "ocr_text": "图中文字，没有则空",
  "ocr_note": "读法",
  "features": ["锥状喀斯特峰林", "同心圆稻田", "漏斗田心", "山脚村寨"],
  "search_query": "用于维基检索的中文关键词",
  "candidates": [{"name":"万峰林八卦田","region":"贵州兴义","confidence":0.86,"why":"峰林+同心圆稻田"}],
  "label_zh": "最可能的短名",
  "region": "省市区或国家",
  "confidence": 0.86,
  "reason": "依据画面哪一部分",
  "scene": "photo"
}"""

STORY_PROMPT = """你是通用多语种讲解 Agent。下面是识图结果和检索摘要。请写七语导游讲解。
识图：
{ident_json}

检索摘要（可能有噪音，只采纳与画面吻合的条目）：
{grounding}

术语锁定（出现这些专名时必须用表内译法）：
{term_table}

规则：
- 标题用识图给出的地名；检索能印证则写清行政区（例如在贵州兴义万峰林）。
- 先讲画面里看见的，再补地理/人文故事。
- 检索与画面冲突时以画面为准，并写「请老师补充」。
- 七语 zh en ja fr es ko th，每语 80–140 字。
只返回 JSON：
{{"zh":"...","en":"...","ja":"...","fr":"...","es":"...","ko":"...","th":"..."}}
"""

KNOWN_FACTS = """已知讲解口径（与照片/专名相关时采用，不得编造相反内容）：
- 乐山大佛下山虎：指景区内「龙湫虎穴」。下山虎是利用天然崖壁与古人崖墓形成的虎形景观，位于通往大佛的沿途。崖壁或塑像形似白虎下山，下方或附近为古人墓穴。
- 回头是岸：乐山大佛一带崖壁题刻，匾额常从右到左读作「回头是岸」。
- 凌云寺：凌云山寺宇，牌匾繁体常作「凌雲寺」，从右到左读。
"""

TEXT_PROMPT = """你是通用的多语种讲解 Agent。用户手动输入一个地名、文物、题刻或短语（可以是峨眉山、乐山大佛下山虎，或任何景点专名），请做七语讲解并补一点背景故事。
输入：{query}
{facts}
术语表中的专名必须用表内译法：
{term_table}

规则：
- 先给规范译名，再讲它是什么、在哪、游客怎么看。
- 下面「已知口径」仅当输入确实指向该条时采用，不要把无关输入套进去。
- 不知道的年代数字写「请老师补充」，不要编造。
- 七语 zh en ja fr es ko th，每语 80–140 字。
只返回 JSON：
{{"scene":"photo","label_zh":"专名短名","reason":"一句话","zh":"...","en":"...","ja":"...","fr":"...","es":"...","ko":"...","th":"..."}}
"""
CHAT_PROMPT = """你是通用的多语种讲解 Agent。请围绕用户刚上传的这张照片继续回答。
识别名称：{label_zh}
图中文字：{ocr_text}
画面：{in_photo}
专名锁定：
{term_table}
先依据画面所见；问到题刻/佛语按识读结果解释，看不清就请老师补充。
用用户提问的语言回答；未限定时用中文，并补两句英文。"""


def _guess_lang(text: str) -> str:
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u0e00-\u0e7f]", text):
        return "th"
    if re.search(r"[àâçéèêëîïôùûüœÀÂÇÉÈÊËÎÏÔÙÛÜŒ]", text):
        return "fr"
    if re.search(r"[áéíóúñü¿¡ÁÉÍÓÚÑÜ]", text):
        return "es"
    letters = [ch for ch in text if ch.isascii() and ch.isalpha()]
    if letters and (sum(ch.isascii() for ch in text) / max(len(text), 1) > 0.72):
        return "en"
    return "zh"


def _trim_sessions() -> None:
    if len(SESSIONS) <= MAX_SESSIONS:
        return
    oldest = sorted(SESSIONS.items(), key=lambda item: item[1].get("ts", 0))
    for key, _ in oldest[: len(SESSIONS) - MAX_SESSIONS]:
        SESSIONS.pop(key, None)


def _lock_bundle(texts: dict[str, str], terms: list[dict]) -> tuple[dict[str, str], dict[str, list[str]]]:
    locked, hits = {}, {}
    for lang in LANGS:
        locked[lang], hits[lang] = apply_lock(texts.get(lang, "") or "", terms, lang)
    return locked, hits


def _normalize_ident(data: dict) -> dict:
    scene = data.get("scene") if data.get("scene") in glossary.SCENES else "photo"
    meta = glossary.scene_meta(scene)
    region = (data.get("region") or "").strip()
    cands = data.get("candidates") or []
    if not region and cands and isinstance(cands, list) and isinstance(cands[0], dict):
        region = (cands[0].get("region") or "").strip()
    label = (data.get("label_zh") or "").strip()
    if not label and cands and isinstance(cands, list) and isinstance(cands[0], dict):
        label = (cands[0].get("name") or "").strip()
    return {
        "scene": scene,
        "label_zh": label or meta["label_zh"],
        "region": region,
        "ocr_text": (data.get("ocr_text") or "").strip(),
        "ocr_note": (data.get("ocr_note") or "").strip(),
        "in_photo": (data.get("in_photo") or "").strip(),
        "related": bool(data.get("related", True)),
        "confidence": float(data.get("confidence") or 0),
        "reason": data.get("reason") or "",
    }



def explain_text(query: str) -> tuple[dict, list[dict], dict[str, str], dict[str, list[str]]]:
    q = query.strip()
    terms = glossary.all_terms()
    raw = llm.chat(
        [
            {
                "role": "system",
                "content": TEXT_PROMPT.format(
                    query=q,
                    facts=KNOWN_FACTS,
                    term_table=glossary.term_table_for_prompt(terms),
                ),
            },
            {"role": "user", "content": q},
        ],
        max_tokens=2800,
        timeout=120,
    )
    data = llm.parse_json_object(raw)
    ident = _normalize_ident(data)
    ident["label_zh"] = data.get("label_zh") or q
    ident["in_photo"] = f"手动输入：{q}"
    ident["ocr_text"] = q
    ident["ocr_note"] = "手动翻译"
    if ident["scene"] not in glossary.SCENES:
        ident["scene"] = "photo"
    terms = glossary.all_terms()
    texts = {lang: data.get(lang, "") or "" for lang in LANGS}
    locked, hits = _lock_bundle(texts, terms)
    return ident, terms, locked, hits


def identify_from_image(mime: str, b64: str) -> tuple[dict, dict, str]:
    raw = llm.chat(
        [
            {"role": "system", "content": IDENT_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "识别这张照片最可能是哪里，并给出检索关键词。"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ],
        max_tokens=900,
        timeout=120,
    )
    ident_raw = llm.parse_json_object(raw)
    return _normalize_ident(ident_raw), ident_raw, raw


def ground_ident(ident: dict, ident_raw: dict) -> tuple[str, str]:
    query = ident_raw.get("search_query") or ident.get("label_zh") or ""
    cands = ident_raw.get("candidates") or []
    if cands and isinstance(cands, list) and isinstance(cands[0], dict) and cands[0].get("name"):
        query = f"{cands[0].get('name')} {query}".strip()
    return query, search.wiki_ground(query)


def write_story(ident_raw: dict, raw: str, grounding: str) -> tuple[list[dict], dict[str, str], dict[str, list[str]]]:
    terms = glossary.all_terms()
    story_raw = llm.chat(
        [
            {
                "role": "system",
                "content": STORY_PROMPT.format(
                    ident_json=raw if len(raw) < 1800 else str(ident_raw)[:1800],
                    grounding=grounding or "（检索无结果，请仅依据画面与你的可靠地理知识；无把握则请老师补充）",
                    term_table=glossary.term_table_for_prompt(terms),
                ),
            },
            {"role": "user", "content": "请根据识图与检索写七语讲解。"},
        ],
        max_tokens=2200,
        timeout=120,
    )
    texts = llm.parse_json_object(story_raw)
    locked, hits = _lock_bundle({lang: texts.get(lang, "") or "" for lang in LANGS}, terms)
    return terms, locked, hits


def iter_photo_progress(mime: str, b64: str):
    yield {"type": "status", "step": "identify", "message": "正在看图，抽取地貌与构图指纹…"}
    ident, ident_raw, raw = identify_from_image(mime, b64)
    features = ident_raw.get("features") or []
    cands = ident_raw.get("candidates") or []
    yield {
        "type": "identify",
        "step": "identify",
        "ident": ident,
        "features": features,
        "candidates": cands,
        "message": f"初步判断：{ident.get('label_zh') or '画面景物'}"
        + (f"（{ident.get('region')}）" if ident.get("region") else ""),
    }
    yield {"type": "status", "step": "search", "message": "正在检索核对地名…"}
    query, grounding = ground_ident(ident, ident_raw)
    snippet = (grounding or "检索无结果，改用模型地理知识").replace("\n", " ")
    yield {
        "type": "search",
        "step": "search",
        "query": query,
        "grounding": snippet[:600],
        "message": f"检索：{query or '（无关键词）'}",
    }
    yield {"type": "status", "step": "story", "message": "正在撰写中英日法西韩泰讲解…"}
    terms, locked, hits = write_story(ident_raw, raw, grounding)
    payload = create_session(ident, terms, locked, hits)
    yield {"type": "done", "step": "deliver", "result": payload, "message": "讲解完成"}


def explain_photo(mime: str, b64: str) -> tuple[dict, list[dict], dict[str, str], dict[str, list[str]]]:
    result = None
    for ev in iter_photo_progress(mime, b64):
        if ev.get("type") == "done":
            result = ev["result"]
    if not result:
        raise RuntimeError("识图未完成")
    session = SESSIONS[result["session_id"]]
    return session["ident"], session["terms"], session["intro"], session["hits"]


def generate_intro(ident: dict) -> tuple[list[dict], dict[str, str], dict[str, list[str]]]:
    terms = glossary.all_terms()
    raw = llm.chat(
        [
            {
                "role": "system",
                "content": STORY_PROMPT.format(ident_json=str(ident), grounding='（无检索）', term_table=glossary.term_table_for_prompt(terms)),
            },
            {
                "role": "user",
                "content": (
                    f"不看图，按已识读结果写七语讲解。\n"
                    f"名称：{ident.get('label_zh')}\n"
                    f"图中文字：{ident.get('ocr_text')}\n"
                    f"识读说明：{ident.get('ocr_note')}\n"
                    f"画面：{ident.get('in_photo')}"
                ),
            },
        ],
        max_tokens=1800,
        timeout=120,
    )
    data = llm.parse_json_object(raw)
    texts = {lang: data.get(lang, "") or "" for lang in LANGS}
    return terms, *_lock_bundle(texts, terms)


def create_session(ident: dict, terms: list[dict], intro: dict, hits: dict) -> dict:
    _trim_sessions()
    session_id = uuid.uuid4().hex
    session = {
        "id": session_id,
        "ts": time.time(),
        "ident": ident,
        "scene": ident["scene"],
        "label_zh": ident["label_zh"],
        "confidence": ident["confidence"],
        "reason": ident["reason"],
        "ocr_text": ident.get("ocr_text", ""),
        "ocr_note": ident.get("ocr_note", ""),
        "in_photo": ident.get("in_photo", ""),
        "terms": terms,
        "intro": intro,
        "hits": hits,
        "messages": [
            {
                "role": "system",
                "content": CHAT_PROMPT.format(
                    label_zh=ident["label_zh"],
                    ocr_text=ident.get("ocr_text") or "（无）",
                    in_photo=ident.get("in_photo") or "（无）",
                    term_table=glossary.term_table_for_prompt(terms),
                ),
            },
            {"role": "assistant", "content": intro.get("zh") or ""},
        ],
    }
    SESSIONS[session_id] = session
    return public_session(session)


def public_session(session: dict, extra: dict | None = None) -> dict:
    payload = {
        "session_id": session["id"],
        "scene": session["scene"],
        "label_zh": session["label_zh"],
        "confidence": session["confidence"],
        "reason": session["reason"],
        "ocr_text": session.get("ocr_text", ""),
        "ocr_note": session.get("ocr_note", ""),
        "in_photo": session.get("in_photo", ""),
        "region": session.get("ident", {}).get("region", ""),
        "intro": session["intro"],
        "locked_terms": session["hits"],
        "term_table": [
            {
                "zh": t["zh"],
                "en": glossary.term_value(t, "en"),
                "ja": glossary.term_value(t, "ja"),
                "fr": glossary.term_value(t, "fr"),
                "es": glossary.term_value(t, "es"),
                "ko": glossary.term_value(t, "ko"),
                "th": glossary.term_value(t, "th"),
                "reviewer": t.get("reviewer", ""),
            }
            for t in session["terms"]
        ],
        "scenes": [
            {"id": key, "label_zh": val["label_zh"]}
            for key, val in (glossary.load().get("scenes") or {}).items()
        ],
    }
    if extra:
        payload.update(extra)
    return payload


def override_scene(session_id: str, scene: str) -> dict:
    session = SESSIONS.get(session_id)
    if not session:
        raise KeyError("会话不存在，请重新上传图片")
    if scene not in glossary.SCENES:
        raise ValueError("未知场景")
    ident = dict(session.get("ident") or {})
    ident["scene"] = scene
    ident["label_zh"] = glossary.scene_meta(scene)["label_zh"]
    terms, intro, hits = generate_intro(ident)
    session.update(
        {
            "ts": time.time(),
            "ident": ident,
            "scene": scene,
            "label_zh": ident["label_zh"],
            "terms": terms,
            "intro": intro,
            "hits": hits,
            "messages": [
                {
                    "role": "system",
                    "content": CHAT_PROMPT.format(
                        label_zh=ident["label_zh"],
                        ocr_text=ident.get("ocr_text") or "（无）",
                        in_photo=ident.get("in_photo") or "（无）",
                        term_table=glossary.term_table_for_prompt(terms),
                    ),
                },
                {"role": "assistant", "content": intro.get("zh") or ""},
            ],
        }
    )
    return public_session(session)


def chat(session_id: str, user_text: str) -> dict:
    session = SESSIONS.get(session_id)
    if not session:
        raise KeyError("会话不存在，请重新上传图片")
    session["messages"].append({"role": "user", "content": user_text.strip()})
    keep = [session["messages"][0]] + session["messages"][-8:]
    raw = llm.chat(keep, max_tokens=800, timeout=90)
    locked, hits = apply_lock(raw, session["terms"], _guess_lang(raw))
    session["messages"].append({"role": "assistant", "content": locked})
    session["ts"] = time.time()
    return {"reply": locked, "locked_terms": hits, "session_id": session_id}
