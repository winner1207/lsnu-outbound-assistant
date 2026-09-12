# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import agent, imageutil
from app.config import BRAND_DIR, MAX_UPLOAD_BYTES, STATIC_DIR

app = FastAPI(title="乐师对外教学助手", version="1.0")
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


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "name": "lsnu-outbound-assistant"}


def _sse(event: dict) -> str:
    return "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


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

    def gen():
        try:
            yield _sse({"type": "status", "step": "identify", "message": f"图片已压缩为 JPEG 再送视觉模型（{_n // 1024} KB）"})
            for ev in agent.iter_photo_progress(mime, b64):
                yield _sse(ev)
        except Exception as exc:
            yield _sse({"type": "error", "message": str(exc)})

    return StreamingResponse(
        gen(),
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
        ident, terms, intro, hits = agent.explain_photo(mime, b64)
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
