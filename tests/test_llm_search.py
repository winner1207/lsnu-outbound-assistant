# -*- coding: utf-8 -*-
import json
import unittest
import urllib.error
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


def _http_400(url="https://example.test/v1/chat/completions"):
    return urllib.error.HTTPError(url, 400, "Bad Request", None, BytesIO(b'{"error":"invalid enable_search"}'))


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


class EnableSearchFallbackTest(unittest.TestCase):
    def test_chat_retries_without_search_on_http_400(self):
        calls = []

        def fake_urlopen(req, timeout=None, context=None):
            body = json.loads(req.data.decode("utf-8"))
            calls.append(body)
            if len(calls) == 1:
                raise _http_400()
            return _FakeResponse(_fake_chat_payload())

        with patch("app.llm.LLM_BASE_URL", "https://example.test/v1"), \
             patch("app.llm.LLM_API_KEY", "test-key"), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            result = llm.chat([{"role": "user", "content": "hi"}], enable_search=True)

        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].get("enable_search"))
        self.assertNotIn("enable_search", calls[1])

    def test_chat_false_http_400_not_retried(self):
        calls = []

        def fake_urlopen(req, timeout=None, context=None):
            body = json.loads(req.data.decode("utf-8"))
            calls.append(body)
            raise _http_400()

        with patch("app.llm.LLM_BASE_URL", "https://example.test/v1"), \
             patch("app.llm.LLM_API_KEY", "test-key"), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(RuntimeError):
                llm.chat([{"role": "user", "content": "hi"}], enable_search=False)

        self.assertEqual(len(calls), 1)

    def test_stream_retries_without_search_on_http_400(self):
        calls = []

        class _FakeStreamResponse:
            def __init__(self):
                self.headers = {"Content-Type": "text/event-stream"}
                self._buf = b'data: {"choices":[{"delta":{"content":"ok"}}]}\ndata: [DONE]\n'

            def read(self, n=None):
                if n is None:
                    chunk, self._buf = self._buf, b""
                    return chunk
                chunk, self._buf = self._buf[:n], self._buf[n:]
                return chunk

            def close(self):
                pass

        def fake_urlopen(req, timeout=None, context=None):
            body = json.loads(req.data.decode("utf-8"))
            calls.append(body)
            if len(calls) == 1:
                raise _http_400()
            return _FakeStreamResponse()

        with patch("app.llm.LLM_BASE_URL", "https://example.test/v1"), \
             patch("app.llm.LLM_API_KEY", "test-key"), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            pieces = list(llm.chat_stream([{"role": "user", "content": "hi"}], enable_search=True))

        self.assertEqual("".join(pieces), "ok")
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0].get("enable_search"))
        self.assertNotIn("enable_search", calls[1])

    def test_stream_false_http_400_not_retried(self):
        calls = []

        def fake_urlopen(req, timeout=None, context=None):
            body = json.loads(req.data.decode("utf-8"))
            calls.append(body)
            raise _http_400()

        with patch("app.llm.LLM_BASE_URL", "https://example.test/v1"), \
             patch("app.llm.LLM_API_KEY", "test-key"), \
             patch("urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(RuntimeError):
                list(llm.chat_stream([{"role": "user", "content": "hi"}], enable_search=False))

        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
