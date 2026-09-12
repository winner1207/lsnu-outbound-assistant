# -*- coding: utf-8 -*-
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is False:
        return None
    if _ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR

            _ENGINE = RapidOCR()
        except Exception:
            _ENGINE = False
            return None
    return _ENGINE


def _as_rgb_array(im: Image.Image):
    import numpy as np

    return np.array(im.convert("RGB"))


def _red_inv(im: Image.Image) -> Image.Image:
    import numpy as np

    arr = np.array(im.convert("RGB")).astype(np.int16)
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    ink = np.clip((r - (g + b) // 2) * 2, 0, 255).astype(np.uint8)
    return ImageOps.invert(Image.fromarray(ink)).convert("RGB")


def _ocr_image(engine, im: Image.Image) -> list[str]:
    result, _ = engine(_as_rgb_array(im))
    texts = []
    if not result:
        return texts
    for item in result:
        text = (item[1] or "").strip()
        try:
            score = float(item[2] or 0)
        except (TypeError, ValueError):
            score = 0
        if text and score >= 0.45:
            texts.append(text)
    return texts


def read_texts(data: bytes) -> list[str]:
    engine = _engine()
    if engine is None or not data:
        return []
    try:
        im = Image.open(BytesIO(data)).convert("RGB")
    except Exception:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for variant in (im, _red_inv(im), im.rotate(270, expand=True)):
        try:
            lines = _ocr_image(engine, variant)
        except Exception:
            continue
        for text in lines:
            if text not in seen:
                seen.add(text)
                out.append(text)
    return out
