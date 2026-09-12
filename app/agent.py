# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import uuid
from typing import Any

from app import glossary, llm
from app.lock import apply_lock


def _guess_lang(text: str) -> str:
    import re
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    letters = [ch for ch in text if ch.isascii() and ch.isalpha()]
    if letters and (sum(ch.isascii() for ch in text) / max(len(text), 1) > 0.72):
        return "en"
    return "zh"


SESSIONS: dict[str, dict[str, Any]] = {}
MAX_SESSIONS = 40

IDENTIFY_PROMPT = """你是乐山师范学院对外教学助手的识图模块。
只判断照片是否与乐山 / 乐山大佛 / 郭沫若（沫若）/ 嘉阳小火车 / 乐山师范学院校园相关。
不要编造没看见的内容。不确定就 unknown。
只返回 JSON：
{"scene":"leshan_buddha|moruo|jiayang_train|campus|unknown","label_zh":"中文短名","confidence":0.0,"reason":"一句话"}"""

INTRO_PROMPT = """你是乐山师范学院对外讲解助手，服务留学生与对外教学。
必须逐字使用下列锁定术语的对应语言译法，禁止意译、拆开或替换：
{term_table}

请根据识别结果「{label_zh}」写一段背景介绍，分中文、英文、日文。
规则：
- 只写审定常识：乐山、乐山大佛、师范办学、沫若、嘉阳小火车等；不知道的事实写「请老师补充」，不要编造数字、年代、传说细节。
- 不要党政文件口吻，不要宣传口号堆砌。
- 每语 120–180 字。
只返回 JSON：{{"zh":"...","en":"...","ja":"..."}}"""

CHAT_PROMPT = """你是乐山师范学院对外讲解助手。继续回答用户追问。
锁定术语必须保持原译，不得改写：
{term_table}
只讲乐师 / 乐山相关内容。不知道就请老师补充，不要编造。
用用户提问的语言回答；若用户没限定语言，用中文回答，并在末尾补两句英文要点。"""


def _trim_sessions() -> None:
    if len(SESSIONS) <= MAX_SESSIONS:
        return
    oldest = sorted(SESSIONS.items(), key=lambda item: item[1].get("ts", 0))
    for key, _ in oldest[: len(SESSIONS) - MAX_SESSIONS]:
        SESSIONS.pop(key, None)


def _lock_bundle(texts: dict[str, str], terms: list[dict]) -> tuple[dict[str, str], dict[str, list[str]]]:
    locked = {}
    hits = {}
    for lang in ("zh", "en", "ja"):
        locked[lang], hits[lang] = apply_lock(texts.get(lang, ""), terms, lang)
    return locked, hits


def identify_image(mime: str, b64: str) -> dict:
    raw = llm.chat(
        [
            {"role": "system", "content": IDENTIFY_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "识别这张图片所属场景。"},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ],
        max_tokens=300,
        timeout=120,
    )
    data = llm.parse_json_object(raw)
    scene = data.get("scene") if data.get("scene") in glossary.SCENES else "unknown"
    meta = glossary.scene_meta(scene)
    return {
        "scene": scene,
        "label_zh": data.get("label_zh") or meta["label_zh"],
        "confidence": float(data.get("confidence") or 0),
        "reason": data.get("reason") or "",
    }


def generate_intro(scene: str, label_zh: str) -> tuple[list[dict], dict[str, str], dict[str, list[str]]]:
    terms = glossary.terms_for_scene(scene)
    raw = llm.chat(
        [
            {
                "role": "system",
                "content": INTRO_PROMPT.format(
                    term_table=glossary.term_table_for_prompt(terms),
                    label_zh=label_zh,
                ),
            },
            {"role": "user", "content": f"请介绍：{label_zh}"},
        ],
        max_tokens=1200,
        timeout=120,
    )
    texts = llm.parse_json_object(raw)
    locked, hits = _lock_bundle(
        {"zh": texts.get("zh", ""), "en": texts.get("en", ""), "ja": texts.get("ja", "")},
        terms,
    )
    return terms, locked, hits


def create_session(ident: dict, terms: list[dict], intro: dict, hits: dict) -> dict:
    _trim_sessions()
    session_id = uuid.uuid4().hex
    session = {
        "id": session_id,
        "ts": time.time(),
        "scene": ident["scene"],
        "label_zh": ident["label_zh"],
        "confidence": ident["confidence"],
        "reason": ident["reason"],
        "terms": terms,
        "intro": intro,
        "hits": hits,
        "messages": [
            {
                "role": "system",
                "content": CHAT_PROMPT.format(term_table=glossary.term_table_for_prompt(terms)),
            },
            {
                "role": "assistant",
                "content": intro["zh"],
            },
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
        "intro": session["intro"],
        "locked_terms": session["hits"],
        "term_table": [
            {
                "zh": t["zh"],
                "en": t["en"],
                "ja": t["ja"],
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
    meta = glossary.scene_meta(scene)
    terms, intro, hits = generate_intro(scene, meta["label_zh"])
    session.update(
        {
            "ts": time.time(),
            "scene": scene,
            "label_zh": meta["label_zh"],
            "terms": terms,
            "intro": intro,
            "hits": hits,
            "messages": [
                {
                    "role": "system",
                    "content": CHAT_PROMPT.format(term_table=glossary.term_table_for_prompt(terms)),
                },
                {"role": "assistant", "content": intro["zh"]},
            ],
        }
    )
    return public_session(session)


def chat(session_id: str, user_text: str) -> dict:
    session = SESSIONS.get(session_id)
    if not session:
        raise KeyError("会话不存在，请重新上传图片")
    session["messages"].append({"role": "user", "content": user_text.strip()})
    # 控制上下文长度
    keep = [session["messages"][0]] + session["messages"][-8:]
    raw = llm.chat(keep, max_tokens=700, timeout=90)
    locked, hits = apply_lock(raw, session["terms"], _guess_lang(raw))
    session["messages"].append({"role": "assistant", "content": locked})
    session["ts"] = time.time()
    return {"reply": locked, "locked_terms": hits, "session_id": session_id}
