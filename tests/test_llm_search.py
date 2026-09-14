# -*- coding: utf-8 -*-
import json
import unittest
from io import BytesIO
from unittest.mock import patch

from app import llm


class _FakeResponse:
    def __init__(self, payload: dict):
        self._buf = BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_chat_payload():
    return {"choices": [{"message": {"content": "ok"}}]}


class EnableSearchTest(unittest.TestCase):
    def test_enable_search_flag_added_when_true(self):
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse(_fake_chat_payload())

        with patch("app.llm.LLM_BASE_URL", "https://example.test/v1"), \
             patch("app.llm.LLM_API_KEY", "test-key"), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            llm.chat([{"role": "user", "content": "hi"}], enable_search=True)

        self.assertTrue(captured["body"].get("enable_search"))

    def test_enable_search_absent_by_default(self):
        captured = {}

        def fake_urlopen(req, timeout=None, context=None):
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _FakeResponse(_fake_chat_payload())

        with patch("app.llm.LLM_BASE_URL", "https://example.test/v1"), \
             patch("app.llm.LLM_API_KEY", "test-key"), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            llm.chat([{"role": "user", "content": "hi"}])

        self.assertNotIn("enable_search", captured["body"])


if __name__ == "__main__":
    unittest.main()
