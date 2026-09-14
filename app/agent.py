# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
import re
import time
import uuid
from typing import Any

from app import glossary, llm, ocrutil, search
from app.lock import apply_lock

SESSIONS: dict[str, dict[str, Any]] = {}
MAX_SESSIONS = 40
LANGS = glossary.LANGS
LANG_LABEL = {
    "zh": "中文",
    "en": "英文",
    "ja": "日文",
    "fr": "法文",
    "es": "西班牙文",
    "ko": "韩文",
    "th": "泰文",
}

IDENT_PROMPT_TEMPLATE = """你是跨地域景点识别模块。先记录画面事实，再提出候选地点。禁止预设某个省市或景区，也禁止拿热门景点硬套。

识字：
- 匾额、摩崖、对联默认从右到左读，再给从左到右对照。
- 繁体转简体。不要为了凑地名而旋转或倒置图片。
- 乐山常见题刻：{inscriptions}

看景（字不够时）：
{visual_hints}
- 不确定具体专名时，也必须在 candidates 里给出至少一个最佳猜测（name/region/confidence/why 都要填，confidence 可以很低），标注为待人工核实；只有连大致方向都判断不出来才整体判 unknown。不要写成三游洞、赤水丹霞、万峰林、阿弥陀佛、佛光普照。

候选必须至少考虑两个不同地点或明确说明为何只有一个候选；观察事实不能写成地点结论。只返回 JSON：
{{
  "in_photo": "一句话描述所见",
  "ocr_text": "图中文字，没有则空",
  "ocr_note": "读法，是否从右到左",
  "features": ["红色砂岩", "摩崖四字"],
  "search_query": "用于检索的中文关键词",
  "candidates": [{{"name":"回头是岸","region":"四川乐山","confidence":0.86,"why":"从右到左读四字"}}],
  "label_zh": "最可能的短名",
  "region": "省市区",
  "confidence": 0.86,
  "reason": "依据画面哪一部分",
  "scene": "photo"
}}"""


def _ident_prompt() -> str:
    inscriptions = "、".join(t["zh"] for t in glossary.inscription_terms()) or "（无）"
    hints = "\n".join(f"- {hint}：{label}" for label, hint in glossary.scene_visual_hints())
    return IDENT_PROMPT_TEMPLATE.format(inscriptions=inscriptions, visual_hints=hints or "- （无）")


STORY_PROMPT = """你是乐山师范多语言智能解说。下面是识图结果和检索摘要。请写七语导游讲解。
识图：
{ident_json}

检索摘要（可能有噪音，只采纳与画面吻合的条目）：
{grounding}

已知口径：
{facts}

术语锁定（出现这些专名时必须用表内译法）：
{term_table}

规则：
- 标题用识图给出的地名；检索能印证则写清行政区。
- 先讲画面里看见的，再补地理/人文故事。
- 检索与画面冲突时以画面为准，并注明依据不足。
- 七语 zh en ja fr es ko th，每语 80–140 字。
- 按 zh、en、ja、fr、es、ko、th 的顺序写 JSON，写完一个字段再写下一项。
只返回 JSON：
{{"zh":"...","en":"...","ja":"...","fr":"...","es":"...","ko":"...","th":"..."}}
"""

KNOWN_FACTS = """已知讲解口径（与照片/专名相关时采用，不得编造相反内容）：
- 乐山大佛下山虎：指景区内「龙湫虎穴」。下山虎是利用天然崖壁与古人崖墓形成的虎形景观，位于通往大佛的沿途。崖壁或塑像形似白虎下山，下方或附近为古人墓穴。
- 回头是岸：乐山大佛一带崖壁题刻，匾额常从右到左读作「回头是岸」。
- 凌云寺：凌云山寺宇，牌匾繁体常作「凌雲寺」，从右到左读。
- 海师洞：纪念开凿大佛的海通和尚，匾额繁体常作「海師洞」，从右到左读。
- 载酒时游处：凌云山苏东坡相关摩崖，从右到左读「载酒时游处」。
- 苏园：凌云山园门，匾额「蘇園」，从右到左读。
- 东方佛都福寿摩崖造像：红砂岩崖壁摩崖组合，中央坐佛带桃形火焰背光，左右各立一尊侍者像，崖面满刻经文小字，两侧圆形龛内大字分刻「福」「寿」。多见于乐山大佛景区毗邻的东方佛都风景区内，具体造像年代与撰者待人工审定，讲解时须注明依据不足。
"""

TEXT_PROMPT = """你是乐山师范多语言智能解说。用户手动输入一个地名、文物、题刻或短语，请做七语讲解并补一点背景。
输入：{query}
{facts}
术语表中的专名必须用表内译法：
{term_table}

规则：
- 先给规范译名，再讲它是什么、在哪、游客怎么看。
- 下面「已知口径」仅当输入确实指向该条时采用，不要把无关输入套进去。
- 不知道的年代数字注明依据不足，不要编造。
- 七语 zh en ja fr es ko th，每语 80–140 字。
只返回 JSON：
{{"scene":"photo","label_zh":"专名短名","reason":"一句话","zh":"...","en":"...","ja":"...","fr":"...","es":"...","ko":"...","th":"..."}}
"""
CHAT_PROMPT = """你是乐山师范多语言智能解说。请围绕用户刚上传的这张照片继续回答。
识别名称：{label_zh}
图中文字：{ocr_text}
画面：{in_photo}
专名锁定：
{term_table}
先依据画面所见；问到题刻按识读结果解释，看不清就注明依据不足。
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
        enable_search=True,
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


def ident_from_term(term: dict, texts: list[str]) -> tuple[dict, dict, str]:
    zh = term["zh"]
    region = term.get("region") or "四川乐山"
    ident = {
        "scene": glossary.scene_for_term(term),
        "label_zh": zh,
        "region": region,
        "ocr_text": zh,
        "ocr_note": "题刻已按校本术语校对",
        "in_photo": f"图中题刻为「{zh}」",
        "related": True,
        "confidence": 0.96,
        "reason": "命中校本术语",
    }
    ident_raw = {
        **ident,
        "search_query": f"{zh} 乐山",
        "features": [t for t in texts if t][:8],
        "candidates": [{"name": zh, "region": region, "confidence": 0.96, "why": "校本锁定"}],
    }
    return ident, ident_raw, json.dumps(ident_raw, ensure_ascii=False)


def identify_from_image(mime: str, b64: str, ocr_texts: list[str] | None = None) -> tuple[dict, dict, str]:
    hint = "识别这张照片。先读题刻（从右到左），再判断跨地域的景点候选；不要假设照片来自乐山。"
    if ocr_texts:
        hint += " 本地OCR（顺序可能反了）：" + "、".join(ocr_texts[:8])
    raw = llm.chat(
        [
            {"role": "system", "content": _ident_prompt()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": hint},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ],
        max_tokens=900,
        timeout=180,
        enable_search=True,
    )
    ident_raw = llm.parse_json_object(raw)
    return _normalize_ident(ident_raw), ident_raw, raw


def ground_ident(ident: dict, ident_raw: dict) -> tuple[str, str]:
    candidates = ident_raw.get("candidates") or []
    names = [str(c.get("name") or "").strip() for c in candidates if isinstance(c, dict)]
    names = [n for n in names if n]
    neutral = "洞穴 瀑布 水潭 栈道 摩崖题刻 景点"
    queries = [neutral]
    for name in names[:3]:
        queries.append(f"{name} 景区 瀑布 洞穴")
    chunks = []
    for query in queries:
        text = search.wiki_ground(query)
        if text:
            chunks.append(f"【检索词：{query}】{text}")
    query = "；".join(queries)
    return query, "\n".join(chunks)


def iter_write_story(ident_raw: dict, raw: str, grounding: str, *, enable_search: bool = False):
    terms = glossary.all_terms()
    messages = [
        {
            "role": "system",
            "content": STORY_PROMPT.format(
                ident_json=raw if len(raw) < 1800 else str(ident_raw)[:1800],
                grounding=grounding or "（检索无结果，仅依据画面；无把握则注明依据不足）",
                facts=KNOWN_FACTS,
                term_table=glossary.term_table_for_prompt(terms),
            ),
        },
        {"role": "user", "content": "请根据识图与检索写七语讲解。先写中文。"},
    ]
    locked = {lang: "" for lang in LANGS}
    hits = {lang: [] for lang in LANGS}
    seen: set[str] = set()
    buf = ""
    for piece in llm.chat_stream(messages, max_tokens=2200, timeout=180, enable_search=enable_search):
        buf += piece
        found = llm.extract_lang_fields(buf, LANGS)
        fresh = []
        for lang, text in found.items():
            if lang in seen or not text.strip():
                continue
            locked[lang], hits[lang] = apply_lock(text, terms, lang)
            seen.add(lang)
            fresh.append(lang)
        if fresh:
            yield terms, locked, hits, fresh
    try:
        texts = llm.parse_json_object(buf)
    except RuntimeError:
        texts = {}
        if not any(locked.values()):
            raise
    final = []
    for lang in LANGS:
        text = (texts.get(lang) or locked.get(lang) or "").strip()
        if not text:
            continue
        locked[lang], hits[lang] = apply_lock(text, terms, lang)
        if lang not in seen:
            final.append(lang)
            seen.add(lang)
    if final or not seen:
        yield terms, locked, hits, final or list(LANGS)


def write_story(ident_raw: dict, raw: str, grounding: str, *, enable_search: bool = False) -> tuple[list[dict], dict[str, str], dict[str, list[str]]]:
    last = None
    for terms, locked, hits, _langs in iter_write_story(ident_raw, raw, grounding, enable_search=enable_search):
        last = (terms, locked, hits)
    if not last:
        raise RuntimeError("讲解未完成")
    return last


def iter_photo_progress(mime: str, b64: str, original: bytes | None = None):
    yield {"type": "status", "step": "identify", "message": "正在准备图片…"}
    yield {"type": "status", "step": "identify", "message": "正在识读题刻文字…"}
    ocr_texts = ocrutil.read_texts(original or base64.b64decode(b64))
    yield {"type": "status", "step": "identify", "message": "正在匹配校本术语…"}
    hits = glossary.match_terms(ocr_texts)
    locked_by_glossary = False
    yield {"type": "status", "step": "identify", "message": "正在调用视觉模型看画面…"}
    ident, ident_raw, raw = identify_from_image(mime, b64, ocr_texts)
        vl_hits = glossary.match_terms(
            ocr_texts
            + [
                ident.get("ocr_text") or "",
                ident.get("label_zh") or "",
                ident_raw.get("ocr_text") or "",
            ]
        )
        if vl_hits:
            ident_raw["glossary_hits"] = [item[0].get("zh", "") for item in vl_hits[:3]]
    features = ident_raw.get("features") or ocr_texts
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
    if locked_by_glossary:
        query = ident_raw.get("search_query") or ident.get("label_zh") or ""
        grounding = ""
        yield {
            "type": "search",
            "step": "search",
            "query": query,
            "grounding": "校本术语已锁定，跳过外网检索",
            "message": f"校本锁定：{ident.get('label_zh')}",
        }
    else:
        yield {"type": "status", "step": "search", "message": "正在生成检索关键词…"}
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
    yield {"type": "status", "step": "story", "message": "正在准备术语表…"}
    yield {"type": "status", "step": "story", "message": "正在撰写七语讲解…"}
    payload = None
    session_id = None
    for terms, locked, hits, langs in iter_write_story(ident_raw, raw, grounding, enable_search=not locked_by_glossary):
        if session_id is None:
            payload = create_session(ident, terms, locked, hits)
            session_id = payload["session_id"]
        else:
            payload = patch_session(session_id, locked, hits)
        names = "、".join(LANG_LABEL.get(lang, lang) for lang in langs)
        yield {
            "type": "partial",
            "step": "story",
            "langs": langs,
            "result": payload,
            "message": f"已写出{names}",
        }
    if not payload:
        raise RuntimeError("讲解未完成")
    yield {"type": "done", "step": "deliver", "result": payload, "message": "讲解完成"}


def explain_photo(mime: str, b64: str, original: bytes | None = None) -> tuple[dict, list[dict], dict[str, str], dict[str, list[str]]]:
    result = None
    for ev in iter_photo_progress(mime, b64, original=original):
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
                "content": STORY_PROMPT.format(
                    ident_json=str(ident),
                    grounding="（无检索）",
                    facts=KNOWN_FACTS,
                    term_table=glossary.term_table_for_prompt(terms),
                ),
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


def patch_session(session_id: str, intro: dict, hits: dict) -> dict:
    session = SESSIONS.get(session_id)
    if not session:
        raise KeyError("会话不存在，请重新上传图片")
    session["intro"] = intro
    session["hits"] = hits
    session["ts"] = time.time()
    if session.get("messages") and len(session["messages"]) >= 2:
        session["messages"][1] = {"role": "assistant", "content": intro.get("zh") or ""}
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
