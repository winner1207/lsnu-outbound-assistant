# -*- coding: utf-8 -*-
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.glossary import create_term, delete_term, load, match_terms, update_term

FIXTURE = Path(__file__).resolve().parent / "_glossary_crud.json"


class GlossaryCrudTest(unittest.TestCase):
    def setUp(self):
        self.path = FIXTURE
        self.path.write_text(
            json.dumps(
                {
                    "scenes": {"photo": {"label_zh": "图中景物", "packs": ["tourism"]}},
                    "terms": [
                        {
                            "id": "leshan-giant-buddha",
                            "pack": "tourism",
                            "zh": "乐山大佛",
                            "en": "Leshan Giant Buddha",
                            "aliases_en": ["Leshan Buddha"],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.patcher = patch("app.glossary.GLOSSARY_PATH", self.path)
        self.patcher.start()
        load.cache_clear()

    def tearDown(self):
        self.patcher.stop()
        load.cache_clear()
        for path in (self.path, self.path.with_name(self.path.name + ".tmp")):
            if path.exists():
                path.unlink()

    def test_create_then_match_rtl(self):
        term = create_term(
            {
                "zh": "回头是岸",
                "en": "Repentance is the shore",
                "aliases_zh": ["回頭是岸"],
                "region": "四川乐山凌云山",
            }
        )
        self.assertTrue(term["id"].startswith("term-"))
        self.assertEqual(match_terms(["岸是"])[0][0]["zh"], "回头是岸")

    def test_duplicate_zh_rejected(self):
        with self.assertRaises(ValueError):
            create_term({"zh": "乐山大佛", "en": "x"})

    def test_update_keeps_other_aliases(self):
        created = create_term({"zh": "苏园", "en": "Su Garden", "aliases_zh": ["蘇園"]})
        data = json.loads(self.path.read_text(encoding="utf-8"))
        for item in data["terms"]:
            if item["id"] == created["id"]:
                item["aliases_en"] = ["Su Yuan"]
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        load.cache_clear()
        updated = update_term(
            created["id"],
            {"zh": "苏园", "en": "Su Garden", "aliases_zh": ["蘇園", "苏苑"]},
        )
        self.assertEqual(updated["aliases_en"], ["Su Yuan"])
        self.assertEqual(updated["aliases_zh"], ["蘇園", "苏苑"])

    def test_delete_removes_match(self):
        created = create_term({"zh": "海师洞", "aliases_zh": ["海師洞"]})
        self.assertTrue(match_terms(["洞师海"]))
        delete_term(created["id"])
        names = [t["zh"] for t, _ in match_terms(["洞师海"])]
        self.assertNotIn("海师洞", names)

    def test_missing_delete(self):
        with self.assertRaises(KeyError):
            delete_term("no-such-term")


if __name__ == "__main__":
    unittest.main()
