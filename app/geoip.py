# -*- coding: utf-8 -*-
from __future__ import annotations

import ipaddress
import json
import urllib.request
from typing import Any

DEFAULT_CITY = "乐山"
DEFAULT_PROVINCE = "四川"
DEFAULT_LABEL = "四川乐山"
NEIGHBORS = {"乐山": "成都", "成都": "乐山"}
_CACHE: dict[str, dict[str, str]] = {}


def client_ip(request: Any) -> str:
    headers = getattr(request, "headers", {}) or {}
    forwarded = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    real = (headers.get("x-real-ip") or "").strip()
    if real:
        return real
    client = getattr(request, "client", None)
    return (getattr(client, "host", None) or "").strip()


def is_unusable(ip: str) -> bool:
    if not ip:
        return True
    try:
        obj = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return bool(obj.is_private or obj.is_loopback or obj.is_reserved or obj.is_link_local or obj.is_multicast)


def _strip_admin(name: str) -> str:
    text = (name or "").strip()
    for suffix in ("特别行政区", "自治区", "地区", "盟", "省", "市", "州"):
        if text.endswith(suffix) and len(text) > len(suffix):
            text = text[: -len(suffix)]
            break
    return text.strip()


def _near(city: str, province: str) -> str:
    if city in NEIGHBORS:
        return NEIGHBORS[city]
    if province:
        return f"{province}邻近地区"
    return "邻近地区"


def _label(city: str, province: str) -> str:
    if province and city and city not in province:
        return f"{province}{city}"
    return city or province or DEFAULT_LABEL


def _default() -> dict[str, str]:
    return {
        "city": DEFAULT_CITY,
        "province": DEFAULT_PROVINCE,
        "label": DEFAULT_LABEL,
        "near": NEIGHBORS[DEFAULT_CITY],
    }


def lookup_pconline(ip: str) -> dict[str, str]:
    url = f"https://whois.pconline.com.cn/ipJson.jsp?ip={ip}&json=true"
    req = urllib.request.Request(url, headers={"User-Agent": "lsnu-outbound-assistant"})
    with urllib.request.urlopen(req, timeout=2) as resp:
        raw = resp.read()
    text = raw.decode("gbk", errors="replace")
    data = json.loads(text)
    if data.get("err"):
        raise RuntimeError(str(data.get("err")))
    city = _strip_admin(data.get("city") or "")
    province = _strip_admin(data.get("pro") or "")
    if not city and not province:
        addr = _strip_admin(data.get("addr") or "")
        if addr:
            city = addr
    if not city and not province:
        raise RuntimeError("empty geo")
    if not city:
        city = province
    return {
        "city": city,
        "province": province or city,
        "label": _label(city, province),
        "near": _near(city, province),
    }


def locate(ip: str, fetch=lookup_pconline) -> dict[str, str]:
    if is_unusable(ip):
        return _default()
    cached = _CACHE.get(ip)
    if cached:
        return dict(cached)
    try:
        info = fetch(ip)
    except Exception:
        info = _default()
    if not info.get("city"):
        info = _default()
    _CACHE[ip] = dict(info)
    return dict(info)


def scope_from_ip(ip: str, fetch=lookup_pconline) -> str:
    return locate(ip, fetch=fetch)["label"]
