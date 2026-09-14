# -*- coding: utf-8 -*-
import unittest

from app.llm import extract_lang_fields


class ExtractLangFieldsTest(unittest.TestCase):
    def test_zh_ready_before_en_finished(self):
        buf = '{"zh":"这是乐山大佛。","en":"Leshan'
        got = extract_lang_fields(buf, ("zh", "en", "ja"))
        self.assertEqual(got["zh"], "这是乐山大佛。")
        self.assertNotIn("en", got)

    def test_escaped_quotes(self):
        buf = '{"zh":"名为\\"回头是岸\\"的题刻。","en":"ok"}'
        got = extract_lang_fields(buf, ("zh", "en"))
        self.assertEqual(got["zh"], '名为"回头是岸"的题刻。')
        self.assertEqual(got["en"], "ok")

    def test_order_zh_then_ja(self):
        buf = '{"zh":"中文","en":"English","ja":"日本語"}'
        got = extract_lang_fields(buf, ("zh", "en", "ja"))
        self.assertEqual(got, {"zh": "中文", "en": "English", "ja": "日本語"})


if __name__ == "__main__":
    unittest.main()
