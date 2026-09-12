# -*- coding: utf-8 -*-
import time
import unittest

from app.sseutil import iter_with_keepalive, sse


class KeepaliveTest(unittest.TestCase):
    def test_emits_status_while_blocked(self):
        def producer():
            time.sleep(0.35)
            yield sse({"type": "done", "step": "deliver", "message": "讲解完成"})

        chunks = list(iter_with_keepalive(producer, interval=0.1))
        self.assertTrue(any("仍在处理" in c for c in chunks))
        self.assertTrue(any("讲解完成" in c for c in chunks))
        self.assertEqual(chunks[-1], sse({"type": "done", "step": "deliver", "message": "讲解完成"}))

    def test_keeps_last_step_on_tick(self):
        def producer():
            yield sse({"type": "status", "step": "story", "message": "正在撰写"})
            time.sleep(0.25)
            yield sse({"type": "done", "step": "deliver"})

        chunks = list(iter_with_keepalive(producer, interval=0.1))
        ticks = [c for c in chunks if "仍在处理" in c]
        self.assertTrue(ticks)
        self.assertIn('"step": "story"', ticks[0])

    def test_error_from_producer(self):
        def producer():
            raise RuntimeError("模型响应超时")
            yield sse({"type": "done"})

        chunks = list(iter_with_keepalive(producer, interval=0.1))
        self.assertEqual(len(chunks), 1)
        self.assertIn("模型响应超时", chunks[0])
        self.assertIn('"type": "error"', chunks[0])


if __name__ == "__main__":
    unittest.main()
