# -*- coding: utf-8 -*-
import unittest
from pathlib import Path

from app.glossary import load, match_terms

PHOTO_DIR = Path(r"C:\Users\Admin\Pictures\lsnu")


class MatchTermsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load.cache_clear()

    def _top(self, *texts: str) -> str:
        hits = match_terms(list(texts))
        return hits[0][0]["zh"] if hits else ""

    def test_rtl_huitou(self):
        self.assertEqual(self._top("岸是"), "回头是岸")

    def test_traditional_huitou(self):
        self.assertEqual(self._top("回頭是岸"), "回头是岸")

    def test_rtl_lingyun(self):
        self.assertEqual(self._top("寺雲淩"), "凌云寺")

    def test_rtl_haitong(self):
        self.assertEqual(self._top("洞师海"), "海师洞")

    def test_fuzzy_haitong(self):
        self.assertEqual(self._top("门师海"), "海师洞")

    def test_zaijiu_reversed_blob(self):
        self.assertEqual(self._top("處游時酒载坡东藕"), "载酒时游处")

    def test_zaijiu_partial_ocr(self):
        self.assertEqual(self._top("店进時酒载坡东"), "载酒时游处")

    def test_su_garden(self):
        self.assertEqual(self._top("圆蘇"), "苏园")

    def test_no_sanyou(self):
        hits = match_terms(["三游洞"])
        names = [t["zh"] for t, _ in hits]
        self.assertNotIn("回头是岸", names)

    def test_no_foguang(self):
        hits = match_terms(["佛光普照", "阿弥陀佛"])
        names = [t["zh"] for t, _ in hits]
        self.assertNotIn("回头是岸", names)
        self.assertNotIn("乐山大佛", names)

    @unittest.skipUnless((PHOTO_DIR / "3.jpg").exists(), "no lsnu photo fixtures")
    def test_photo_huitou(self):
        from app import ocrutil

        texts = ocrutil.read_texts((PHOTO_DIR / "3.jpg").read_bytes())
        self.assertEqual(self._top(*texts), "回头是岸")

    @unittest.skipUnless((PHOTO_DIR / "8.jpg").exists(), "no lsnu photo fixtures")
    def test_photo_8_no_false_lock(self):
        from app import ocrutil

        texts = ocrutil.read_texts((PHOTO_DIR / "8.jpg").read_bytes())
        hits = match_terms(texts)
        names = [t["zh"] for t, _ in hits]
        self.assertNotIn("乐山大佛", names)
        self.assertNotIn("凌云寺", names)
        self.assertNotIn("下山虎", names)


if __name__ == "__main__":
    unittest.main()
