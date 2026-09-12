# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import time
import uuid
from typing import Any

from app import glossary, llm
from app.lock import apply_lock

SESSIONS: dict[str, dict[str, Any]] = {}
MAX_SESSIONS = 40
LANGS = glossary.LANGS

EXPLAIN_PROMPT = """你是通用的多语种讲解 Agent，服务游客、留学生和随手拍照的人。
输入永远是「用户此刻上传的这一张图」。不要用图库、文件名、预设景点名单去配对。

工作方式：
1. 看图：如实描述画面（山、寺、塔、造像、题刻、人物、局部特写等）。
2. 识字：读出能看清的文字。中文匾额/对联常从右到左或繁体竖排，按正确顺序转成规范简体。看不清用□，禁止编造没出现的经文或题字。
3. 点名：仅在视觉证据足够时才给出具体地名/寺名/文物名（例如能看出是峨眉山金顶、乐山大佛、某块题刻）。证据不足就用画面描述当标题，不要猜。
4. 故事：结合画面讲背景（历史、宗教、地理、参观注意），像现场导游。不确定的年代、传说写「请老师补充」。
5. 专名锁定：讲解里若出现术语表中的专名，必须用表内对应译法，禁止乱译。

label_zh 用画面短名，例如「峨眉山金顶」「崖壁题刻回头是岸」「白虎塑像」。
scene 弱标签即可：photo / mountain / temple / statue / inscription / campus / unknown

术语表：
{term_table}

七语 zh en ja fr es ko th，每语 80–140 字。
只返回 JSON：
{{
  "scene":"photo",
  "label_zh":"画面短名",
  "ocr_text":"图中文字，没有则空",
  "ocr_note":"读法说明",
  "in_photo":"一句话描述所见",
  "related":true,
  "confidence":0.0,
  "reason":"判断依据来自画面哪一部分",
  "zh":"...","en":"...","ja":"...","fr":"...","es":"...","ko":"...","th":"..."
}}"""


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
    return {
        "scene": scene,
        "label_zh": data.get("label_zh") or meta["label_zh"],
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


def explain_photo(mime: str, b64: str) -> tuple[dict, list[dict], dict[str, str], dict[str, list[str]]]:
    terms = glossary.all_terms()
    raw = llm.chat(
        [
            {
                "role": "system",
                "content": EXPLAIN_PROMPT.format(term_table=glossary.term_table_for_prompt(terms)),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "请只根据这张照片识读并讲解。不要套预设景点。若能明确认出（如峨眉山、乐山大佛）再点名。",
                    },
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ],
        max_tokens=2800,
        timeout=150,
    )
    data = llm.parse_json_object(raw)
    ident = _normalize_ident(data)
    terms = glossary.all_terms()
    texts = {lang: data.get(lang, "") or "" for lang in LANGS}
    locked, hits = _lock_bundle(texts, terms)
    return ident, terms, locked, hits


def generate_intro(ident: dict) -> tuple[list[dict], dict[str, str], dict[str, list[str]]]:
    terms = glossary.all_terms()
    raw = llm.chat(
        [
            {
                "role": "system",
                "content": EXPLAIN_PROMPT.format(term_table=glossary.term_table_for_prompt(terms)),
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
