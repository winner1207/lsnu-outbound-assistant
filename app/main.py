# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import agent, glossary, imageutil
from app.config import BRAND_DIR, MAX_UPLOAD_BYTES, STATIC_DIR
from app.sseutil import iter_with_keepalive, sse

app = FastAPI(title="识景译韵-多语言智能解说系统", version="1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/brand", StaticFiles(directory=BRAND_DIR), name="brand")

MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


class ChatIn(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=2000)


class SceneIn(BaseModel):
    session_id: str
    scene: str


class TextIn(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class TermIn(BaseModel):
    zh: str = Field(min_length=1, max_length=40)
    en: str = ""
    ja: str = ""
    fr: str = ""
    es: str = ""
    ko: str = ""
    th: str = ""
    pack: str = "tourism"
    scene: str = ""
    region: str = Field(default="", max_length=40)
    aliases_zh: list[str] = Field(default_factory=list)
    source: str = Field(default="", max_length=80)
    reviewer: str = Field(default="", max_length=40)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
def favicon():
    return FileResponse(BRAND_DIR / "favicon.ico", media_type="image/x-icon")


@app.get("/api/health")
def health():
    return {"ok": True, "name": "lsnu-outbound-assistant"}


@app.post("/api/analyze/stream")
async def analyze_stream(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    mime = MIME.get(suffix)
    if not mime:
        raise HTTPException(400, "请上传 jpg / png / webp 图片")
    data = await file.read()
    if not data:
        raise HTTPException(400, "图片是空的")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "图片请小于 10MB")
    mime, b64, _n = imageutil.compress_for_vision(data, mime)

    def producer():
        try:
            yield sse({"type": "status", "step": "identify", "message": f"正在处理图片（{_n // 1024} KB）"})
            for ev in agent.iter_photo_progress(mime, b64, original=data):
                yield sse(ev)
        except Exception as exc:
            yield sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        iter_with_keepalive(producer),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    mime = MIME.get(suffix)
    if not mime:
        raise HTTPException(400, "请上传 jpg / png / webp 图片")
    data = await file.read()
    if not data:
        raise HTTPException(400, "图片是空的")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "图片请小于 10MB")
    try:
        mime, b64, _n = imageutil.compress_for_vision(data, mime)
        ident, terms, intro, hits = agent.explain_photo(mime, b64, original=data)
        return agent.create_session(ident, terms, intro, hits)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/scene")
def change_scene(body: SceneIn):
    try:
        return agent.override_scene(body.session_id, body.scene)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/text")
def explain_text(body: TextIn):
    try:
        ident, terms, intro, hits = agent.explain_text(body.query)
        return agent.create_session(ident, terms, intro, hits)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/chat")
def chat(body: ChatIn):
    try:
        return agent.chat(body.session_id, body.message)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.get("/api/terms")
def list_terms():
    return glossary.public_catalog()


@app.post("/api/terms")
def add_term(body: TermIn):
    try:
        return glossary.create_term(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.put("/api/terms/{term_id}")
def edit_term(term_id: str, body: TermIn):
    try:
        return glossary.update_term(term_id, body.model_dump())
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.delete("/api/terms/{term_id}")
def remove_term(term_id: str):
    try:
        glossary.delete_term(term_id)
        return {"ok": True, "id": term_id}
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
