# -*- coding: utf-8 -*-
from types import SimpleNamespace

from app import geoip


class DummyRequest:
    def __init__(self, headers=None, host=""):
        self.headers = headers or {}
        self.client = SimpleNamespace(host=host) if host else None


def setup_function():
    geoip._CACHE.clear()


def test_client_ip_prefers_forwarded_for():
    req = DummyRequest({"x-forwarded-for": "1.2.3.4, 10.0.0.1", "x-real-ip": "8.8.8.8"}, host="127.0.0.1")
    assert geoip.client_ip(req) == "1.2.3.4"


def test_private_ip_defaults_to_leshan():
    info = geoip.locate("127.0.0.1")
    assert info["city"] == "乐山"
    assert info["label"] == "四川乐山"
    assert info["near"] == "成都"


def test_chengdu_neighbor_is_leshan():
    info = geoip.locate("1.1.1.1", fetch=lambda ip: {"city": "成都", "province": "四川", "label": "四川成都", "near": "乐山"})
    assert info["city"] == "成都"
    assert info["near"] == "乐山"
    assert info["label"] == "四川成都"


def test_lookup_failure_falls_back_to_leshan():
    def boom(ip):
        raise RuntimeError("timeout")
    assert geoip.scope_from_ip("8.8.8.8", fetch=boom) == "四川乐山"


def test_pconline_payload_strips_suffix():
    payload = {"pro": "四川省", "city": "乐山市", "err": ""}
    info = geoip.locate("119.6.0.1", fetch=lambda ip: {
        "city": geoip._strip_admin(payload["city"]),
        "province": geoip._strip_admin(payload["pro"]),
        "label": geoip._label(geoip._strip_admin(payload["city"]), geoip._strip_admin(payload["pro"])),
        "near": geoip._near(geoip._strip_admin(payload["city"]), geoip._strip_admin(payload["pro"])),
    })
    assert info["label"] == "四川乐山"
    assert info["near"] == "成都"
