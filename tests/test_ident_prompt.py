# -*- coding: utf-8 -*-
import unittest

from app import agent, glossary


class IdentPromptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        glossary.load.cache_clear()

    def test_inscriptions_include_known_six(self):
        names = {t["zh"] for t in glossary.inscription_terms()}
        expected = {"回头是岸", "凌云寺", "海师洞", "载酒时游处", "苏园", "乐在其中"}
        self.assertEqual(names, expected)

    def test_visual_hints_include_dongfang_fodu(self):
        hints = dict(glossary.scene_visual_hints())
        self.assertIn("东方佛都摩崖石刻群", hints)
        self.assertIn("福寿", hints["东方佛都摩崖石刻群"])

    def test_ident_prompt_is_independent_of_local_glossary(self):
        prompt = agent._ident_prompt()
        self.assertNotIn("东方佛都", prompt)
        self.assertNotIn("回头是岸", prompt)
        self.assertNotIn("依山巨型坐佛", prompt)
        self.assertIn("candidates", prompt)

    def test_dongfang_fodu_term_unreviewed(self):
        term = next(t for t in glossary.all_terms() if t["id"] == "dongfang-fodu")
        self.assertEqual(term.get("reviewer", ""), "")
        self.assertIn("待", term.get("source", ""))


if __name__ == "__main__":
    unittest.main()
