# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
from io import BytesIO


def compress_for_vision(data: bytes, mime: str, *, max_side: int = 1280, quality: int = 80) -> tuple[str, str, int]:
    """缩小后转 JPEG，降低视觉接口超时概率。返回 mime, b64, 压缩后字节数。"""
    try:
        from PIL import Image
    except ImportError:
        return mime, base64.b64encode(data).decode("ascii"), len(data)
    try:
        im = Image.open(BytesIO(data))
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        if len(out) >= len(data) and mime in ("image/jpeg", "image/jpg"):
            return mime, base64.b64encode(data).decode("ascii"), len(data)
        return "image/jpeg", base64.b64encode(out).decode("ascii"), len(out)
    except Exception:
        return mime, base64.b64encode(data).decode("ascii"), len(data)
