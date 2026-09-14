# 识图准确率系统性治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 治理识图链路里让「陌生地标一律判 unknown」的系统性根因：候选/题刻白名单硬编码在 prompt 里、检索层在国内服务器可能完全打不通、unknown 呈现是一刀切、误判案例无沉淀渠道。

**Architecture:** 不引入新框架，只对现有 `app/glossary.py` / `app/agent.py` / `app/llm.py` / `app/static/app.js` 做外科手术式修改：把 prompt 里的硬编码列表改成从 `data/glossary.json` 动态生成；给 `llm.chat`/`chat_stream` 加 `enable_search` 开关对接阿里云 DashScope 兼容模式的联网搜索插件；unknown 场景强制给出「最佳候选 + 置信度」而不是空手判定；把本次 8.jpg 案例回写术语库并沉淀为回归用例。

**Tech Stack:** Python 3.12 / FastAPI / 现有 `unittest` + `unittest.mock`（不引入新依赖）/ 阿里云 DashScope 百炼 `compatible-mode/v1`。

## Global Constraints

- 不新增第三方依赖；`requirements.txt` 保持不变。
- 所有面向用户的文案用简体中文；候选/未审定内容必须显式标注「待人工核实 / 未审定」，不得让模型编造成确定事实（对应 `系统目标.md` 的人机边界）。
- 只改本次任务需要的文件，不顺手重构无关代码；沿用项目现有的 `unittest` 风格（`tests/test_match.py`、`tests/test_glossary_crud.py` 的写法），不引入 pytest。
- `enable_search` 会产生额外的模型调用成本和延迟，只在「术语库未锁定」的分支打开，已被术语库精确锁定的路径（`locked_by_glossary=True`）不打开，维持现有「精确命中优先，省流程」的设计。
- 本地 `.env` 里 `LLM_API_KEY` 为空，**无法在本地对 DashScope 联网搜索做端到端真机验证**；Task 2 只能做到「请求体正确拼装」的单元测试级别，真实搜索效果需要在配置了有效 Key 的环境（本机临时配置或部署机）里人工跑一次 `/api/analyze/stream` 验证。
- 提交信息遵循 `<type>(<scope>): <subject>` 格式，不添加任何署名/共同作者信息。

---

### Task 1: 术语库与识图 Prompt 去硬编码，补入「东方佛都」案例

**Files:**
- Modify: `data/glossary.json`
- Modify: `app/glossary.py`
- Modify: `app/agent.py:27-53`（`IDENT_PROMPT` 及 `KNOWN_FACTS`）
- Test: `tests/test_ident_prompt.py`（新建）

**Interfaces:**
- Produces: `glossary.inscription_terms() -> list[dict]`，`glossary.scene_visual_hints() -> list[tuple[str, str]]`（返回 `(label_zh, hint)`），`agent._ident_prompt() -> str`。
- 后续 Task 2/3 会继续调用 `agent._ident_prompt()`，不改变其无参签名。

- [ ] **Step 1: 写失败的测试**

```python
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

    def test_ident_prompt_contains_dynamic_content(self):
        prompt = agent._ident_prompt()
        self.assertIn("东方佛都", prompt)
        self.assertIn("回头是岸", prompt)
        self.assertIn("依山巨型坐佛", prompt)
        self.assertIn("candidates", prompt)

    def test_dongfang_fodu_term_unreviewed(self):
        term = next(t for t in glossary.all_terms() if t["id"] == "dongfang-fodu")
        self.assertEqual(term.get("reviewer", ""), "")
        self.assertIn("待", term.get("source", ""))


if __name__ == "__main__":
    unittest.main()
```

保存到 `tests/test_ident_prompt.py`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_ident_prompt -v`
Expected: FAIL —— `glossary.inscription_terms` / `glossary.scene_visual_hints` 不存在（`AttributeError`），`agent._ident_prompt` 不存在。

- [ ] **Step 3: 给 `lingyun-temple` 补 `scene` 字段**

在 `data/glossary.json` 里找到 `id: "lingyun-temple"` 的词条（约第 225 行），在 `"zh": "凌云寺"` 前加一行：

```json
      "id": "lingyun-temple",
      "pack": "tourism",
      "scene": "inscription",
      "zh": "凌云寺",
```

- [ ] **Step 4: 给 `scenes` 补 `visual_hint` 并新增 `dongfang_fodu` 场景**

在 `data/glossary.json` 的 `"scenes"` 对象里，给已有三个场景加 `visual_hint`，并新增 `dongfang_fodu`：

```json
  "scenes": {
    "leshan_buddha": {
      "label_zh": "乐山大佛 / 佛语造像",
      "packs": ["tourism", "campus"],
      "visual_hint": "依山巨型坐佛"
    },
    "lingyun": {
      "label_zh": "凌云寺 / 凌云山",
      "packs": ["tourism", "campus"],
      "visual_hint": "圆形大「佛」字龛"
    },
    "moruo": {
      "label_zh": "沫若 / 郭沫若相关",
      "packs": ["tourism", "campus"]
    },
    "jiayang_train": {
      "label_zh": "嘉阳小火车",
      "packs": ["tourism"]
    },
    "campus": {
      "label_zh": "乐山师范学院校园",
      "packs": ["campus", "tourism"]
    },
    "inscription": {
      "label_zh": "匾额 / 楹联 / 碑刻 / 佛语",
      "packs": ["tourism", "campus"]
    },
    "photo": {
      "label_zh": "图中景物（随手拍）",
      "packs": ["tourism", "campus"]
    },
    "unknown": {
      "label_zh": "无法确认",
      "packs": ["tourism", "campus"]
    },
    "xiashan_hu": {
      "label_zh": "下山虎 / 龙湫虎穴",
      "packs": ["tourism", "campus"],
      "visual_hint": "白虎雕像或崖壁虎形"
    },
    "dongfang_fodu": {
      "label_zh": "东方佛都摩崖石刻群",
      "packs": ["tourism"],
      "visual_hint": "圆形双龛大字（如福寿）配满壁经文小字，或桃形火焰背光坐佛加左右侍者像组合：多为乐山大佛景区毗邻的东方佛都摩崖石刻群造像点，专名与年代待人工核实"
    }
  },
```

（只新增/编辑上述字段，`terms` 数组保持原样，本步骤不动。）

- [ ] **Step 5: 在 `data/glossary.json` 的 `terms` 数组末尾追加「东方佛都」词条**

在文件末尾 `]` 前追加（注意补逗号）：

```json
    ,{
      "id": "dongfang-fodu",
      "pack": "tourism",
      "scene": "dongfang_fodu",
      "zh": "东方佛都",
      "en": "Oriental Buddha Capital",
      "ja": "東方仏都",
      "fr": "Capitale orientale du Bouddha",
      "es": "Capital Oriental de Buda",
      "ko": "둥팡포두",
      "th": "ตงฟางฝอตู",
      "aliases_zh": [],
      "aliases_en": ["Dongfang Fodu"],
      "aliases_ja": [],
      "aliases_fr": [],
      "aliases_es": [],
      "aliases_ko": [],
      "aliases_th": [],
      "region": "四川乐山",
      "source": "识图案例待老师最终审定（2026-09-14 福寿摩崖造像组合识别）"
    }
```

`reviewer` 字段留空——沿用项目里「`reviewer` 为空即未审定」的既有约定（`app/main.py` 的 `TermIn.reviewer` 默认空字符串），不需要新增状态字段。

- [ ] **Step 6: 在 `app/glossary.py` 新增两个查询函数**

在 `scene_for_term` 函数（约第 71 行）之后插入：

```python
def inscription_terms() -> list[dict]:
    return [t for t in all_terms() if scene_for_term(t) == "inscription"]


def scene_visual_hints() -> list[tuple[str, str]]:
    data = load()
    out = []
    for meta in (data.get("scenes") or {}).values():
        hint = (meta or {}).get("visual_hint")
        label = (meta or {}).get("label_zh")
        if hint and label:
            out.append((label, hint))
    return out
```

- [ ] **Step 7: 把 `app/agent.py` 的 `IDENT_PROMPT` 改成动态生成**

把 `app/agent.py:27-53` 的 `IDENT_PROMPT = """..."""` 整段替换为：

```python
IDENT_PROMPT_TEMPLATE = """你是乐师对外教学助手的识图模块。先识字，再判断地点。禁止拿外地热门景点硬套。

识字：
- 匾额、摩崖、对联默认从右到左读，再给从左到右对照。
- 繁体转简体。不要为了凑地名而旋转或倒置图片。
- 乐山常见题刻：{inscriptions}

看景（字不够时）：
{visual_hints}
- 不确定具体专名时，也必须在 candidates 里给出至少一个最佳猜测（name/region/confidence/why 都要填，confidence 可以很低），标注为待人工核实；只有连大致方向都判断不出来才整体判 unknown。不要写成三游洞、赤水丹霞、万峰林、阿弥陀佛、佛光普照。

只返回 JSON：
{{
  "in_photo": "一句话描述所见",
  "ocr_text": "图中文字，没有则空",
  "ocr_note": "读法，是否从右到左",
  "features": ["红色砂岩", "摩崖四字"],
  "search_query": "用于检索的中文关键词",
  "candidates": [{{"name":"回头是岸","region":"四川乐山","confidence":0.86,"why":"从右到左读四字"}}],
  "label_zh": "最可能的短名",
  "region": "省市区",
  "confidence": 0.86,
  "reason": "依据画面哪一部分",
  "scene": "photo"
}}"""


def _ident_prompt() -> str:
    inscriptions = "、".join(t["zh"] for t in glossary.inscription_terms()) or "（无）"
    hints = "\n".join(f"- {hint}：{label}" for label, hint in glossary.scene_visual_hints())
    return IDENT_PROMPT_TEMPLATE.format(inscriptions=inscriptions, visual_hints=hints or "- （无）")
```

然后在 `identify_from_image`（约第 222 行）里，把

```python
            {"role": "system", "content": IDENT_PROMPT},
```

改成

```python
            {"role": "system", "content": _ident_prompt()},
```

- [ ] **Step 8: 给 `KNOWN_FACTS` 追加福寿摩崖的已知口径**

在 `app/agent.py` 的 `KNOWN_FACTS`（约第 78-85 行）末尾、闭合的 `"""` 之前追加一行：

```python
- 东方佛都福寿摩崖造像：红砂岩崖壁摩崖组合，中央坐佛带桃形火焰背光，左右各立一尊侍者像，崖面满刻经文小字，两侧圆形龛内大字分刻「福」「寿」。多见于乐山大佛景区毗邻的东方佛都风景区内，具体造像年代与撰者待人工审定，讲解时须注明依据不足。
"""
```

- [ ] **Step 9: 运行测试确认通过**

Run: `python -m unittest tests.test_ident_prompt -v`
Expected: PASS（4 项测试全部通过）。

Run: `python -m unittest discover tests -v`
Expected: 全部既有测试（`test_match`、`test_glossary_crud`、`test_parse_json`、`test_sse`）保持 PASS，不因本次改动回归。

- [ ] **Step 10: 提交**

```bash
git add data/glossary.json app/glossary.py app/agent.py tests/test_ident_prompt.py
git commit -m "feat(glossary): 识图候选与题刻列表改为术语库动态生成，补入东方佛都待审定案例"
```

---

### Task 2: 识图与讲解调用接入阿里云联网搜索插件

**Files:**
- Modify: `app/llm.py`
- Modify: `app/agent.py`
- Test: `tests/test_llm_search.py`（新建）

**Interfaces:**
- Consumes: 无新依赖，沿用 `app.config.LLM_BASE_URL` / `LLM_API_KEY`。
- Produces: `llm.chat(messages, *, max_tokens=1200, timeout=180, retries=1, enable_search=False) -> str`；`llm.chat_stream(messages, *, max_tokens=1200, timeout=180, enable_search=False)`（生成器不变）。

- [ ] **Step 1: 写失败的测试**

```python
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
```

保存到 `tests/test_llm_search.py`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest tests.test_llm_search -v`
Expected: FAIL —— `TypeError: chat() got an unexpected keyword argument 'enable_search'`。

- [ ] **Step 3: 给 `llm.chat` 加 `enable_search` 参数**

把 `app/llm.py` 里的 `chat` 函数签名（第 53 行）：

```python
def chat(messages: list[dict], *, max_tokens: int = 1200, timeout: int = 180, retries: int = 1) -> str:
```

改成：

```python
def chat(messages: list[dict], *, max_tokens: int = 1200, timeout: int = 180, retries: int = 1, enable_search: bool = False) -> str:
```

把函数体内构造请求体的部分（第 57-64 行）：

```python
            payload = _request(
                f"{LLM_BASE_URL}/chat/completions",
                {
                    "model": LLM_MODEL,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                },
                timeout,
            )
```

改成：

```python
            body = {
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": max_tokens,
            }
            if enable_search:
                body["enable_search"] = True
            payload = _request(f"{LLM_BASE_URL}/chat/completions", body, timeout)
```

- [ ] **Step 4: 给 `llm.chat_stream` 同步加 `enable_search` 参数**

把 `chat_stream` 签名（第 141 行）：

```python
def chat_stream(messages: list[dict], *, max_tokens: int = 1200, timeout: int = 180):
```

改成：

```python
def chat_stream(messages: list[dict], *, max_tokens: int = 1200, timeout: int = 180, enable_search: bool = False):
```

把函数体内 `data = json.dumps({...}).encode("utf-8")`（第 144-153 行）里的 dict 字面量：

```python
    data = json.dumps(
        {
            "model": LLM_MODEL,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "stream": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")
```

改成：

```python
    body = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if enable_search:
        body["enable_search"] = True
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m unittest tests.test_llm_search -v`
Expected: PASS。

- [ ] **Step 6: 在 `agent.py` 里为未被术语库锁定的分支打开 `enable_search`**

在 `identify_from_image`（`app/agent.py` 约第 222-241 行）里，把调用 `llm.chat(...)` 的地方加上 `enable_search=True`：

```python
    raw = llm.chat(
        [
            {"role": "system", "content": _ident_prompt()},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": hint},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            },
        ],
        max_tokens=900,
        timeout=180,
        enable_search=True,
    )
```

在 `iter_write_story`（约第 251-297 行）的签名和调用处加一个 `enable_search` 透传参数：

```python
def iter_write_story(ident_raw: dict, raw: str, grounding: str, *, enable_search: bool = False):
```

把函数体里 `for piece in llm.chat_stream(messages, max_tokens=2200, timeout=180):` 改成：

```python
    for piece in llm.chat_stream(messages, max_tokens=2200, timeout=180, enable_search=enable_search):
```

对应地把 `write_story` 签名也加上并透传：

```python
def write_story(ident_raw: dict, raw: str, grounding: str, *, enable_search: bool = False) -> tuple[list[dict], dict[str, str], dict[str, list[str]]]:
    last = None
    for terms, locked, hits, _langs in iter_write_story(ident_raw, raw, grounding, enable_search=enable_search):
        last = (terms, locked, hits)
    if not last:
        raise RuntimeError("讲解未完成")
    return last
```

在 `iter_photo_progress`（约第 365 行）调用处，按「已被术语库精确锁定就不用再搜索」的既有逻辑传参：

```python
    for terms, locked, hits, langs in iter_write_story(ident_raw, raw, grounding, enable_search=not locked_by_glossary):
```

最后在 `explain_text`（约第 170-184 行）的 `llm.chat(...)` 调用里也加 `enable_search=True`（用户手动输入的地名同样没有术语库锁定时的实时检索兜底）：

```python
    raw = llm.chat(
        [
            {
                "role": "system",
                "content": TEXT_PROMPT.format(
                    query=q,
                    facts=KNOWN_FACTS,
                    term_table=glossary.term_table_for_prompt(terms),
                ),
            },
            {"role": "user", "content": q},
        ],
        max_tokens=2800,
        timeout=120,
        enable_search=True,
    )
```

- [ ] **Step 7: 运行全量测试确认无回归**

Run: `python -m unittest discover tests -v`
Expected: 全部 PASS。

- [ ] **Step 8: 提交**

```bash
git add app/llm.py app/agent.py tests/test_llm_search.py
git commit -m "feat(llm): 未被术语库锁定时接入阿里云联网搜索插件，替代不可达的境外维基检索"
```

> **人工验证（无法在本地无 Key 环境完成）：** 部署或本地配置好 `LLM_API_KEY` 后，重新上传 `8.jpg` 跑一次 `/api/analyze/stream`，确认 `candidates`/`in_photo` 里出现「东方佛都」相关信息，而不是继续判 unknown。

---

### Task 3: unknown 场景强制给出候选，前端标注「未审定」

**Files:**
- Modify: `app/static/app.js`

**Interfaces:**
- 不新增后端字段：复用 `public_session()` 已经返回的 `scene` / `label_zh` / `confidence`（`app/agent.py:473-506` 已包含这三个字段，无需改动）。

- [ ] **Step 1: 修改 `renderIdent` 加「未审定」提示**

把 `app/static/app.js:92-102` 的 `renderIdent` 函数：

```javascript
function renderIdent(data) {
  if (!data) return;
  const bits = [data.region ? `识别为「${data.label_zh}」（${data.region}）` : `识别为「${data.label_zh || "画面景物"}」`];
  if (data.in_photo) bits.push(data.in_photo);
  if (data.reason) bits.push(data.reason);
  $("ident").textContent = bits.join(" · ");
  if (data.ocr_text) {
    $("ocr").hidden = false;
    $("ocr").textContent = `图中文字：${data.ocr_text}${data.ocr_note ? "（" + data.ocr_note + "）" : ""}`;
  }
}
```

改成：

```javascript
function renderIdent(data) {
  if (!data) return;
  const bits = [data.region ? `识别为「${data.label_zh}」（${data.region}）` : `识别为「${data.label_zh || "画面景物"}」`];
  if (data.scene === "unknown" && data.label_zh && data.label_zh !== "无法确认") {
    const conf = data.confidence != null ? data.confidence : "低";
    bits.push(`未审定候选，置信度约 ${conf}，请人工核实`);
  }
  if (data.in_photo) bits.push(data.in_photo);
  if (data.reason) bits.push(data.reason);
  $("ident").textContent = bits.join(" · ");
  if (data.ocr_text) {
    $("ocr").hidden = false;
    $("ocr").textContent = `图中文字：${data.ocr_text}${data.ocr_note ? "（" + data.ocr_note + "）" : ""}`;
  }
}
```

- [ ] **Step 2: 人工验证（项目无前端测试框架，沿用现状不新增）**

Run: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`（需要本地配置好 `.env` 的 `LLM_API_KEY` 才能真正调通识图；若只想验证 UI 分支逻辑，可在浏览器控制台手动执行 `renderIdent({scene:"unknown", label_zh:"福寿摩崖造像", confidence:0.4})` 并检查页面顶部识别栏文案是否出现「未审定候选，置信度约 0.4，请人工核实」）。
Expected: 文案按预期出现，且原有「识别为」「图中文字」展示不受影响。

- [ ] **Step 3: 提交**

```bash
git add app/static/app.js
git commit -m "feat(web): unknown 场景展示最佳候选与置信度而非空白判定"
```

---

### Task 4: 沉淀 8.jpg 为回归用例，防止复发

**Files:**
- Modify: `tests/test_match.py`

**Interfaces:**
- 无新接口，复用已有的 `PHOTO_DIR = Path(r"C:\Users\Admin\Pictures\lsnu")` 约定（`tests/test_match.py:7`）。

- [ ] **Step 1: 追加回归测试**

在 `tests/test_match.py` 的 `test_photo_huitou`（第 54-59 行）之后追加：

```python
    @unittest.skipUnless((PHOTO_DIR / "8.jpg").exists(), "no lsnu photo fixtures")
    def test_photo_8_no_false_lock(self):
        from app import ocrutil

        texts = ocrutil.read_texts((PHOTO_DIR / "8.jpg").read_bytes())
        hits = match_terms(texts)
        names = [t["zh"] for t, _ in hits]
        self.assertNotIn("乐山大佛", names)
        self.assertNotIn("凌云寺", names)
        self.assertNotIn("下山虎", names)
```

这条测试锁定的是「福/寿单字不应被误锁到其他术语」这个已验证过的正确行为（本案例的正确治理路径是 Task 1/2 的动态 prompt + 联网搜索，不是靠术语库单字匹配），防止未来给术语库加词条时不小心让「福」「寿」这类高频字被某个术语的宽松别名吞掉。

- [ ] **Step 2: 运行测试**

Run: `python -m unittest tests.test_match -v`
Expected: 若本机存在 `C:\Users\Admin\Pictures\lsnu\8.jpg`（本次案例图片就在这里）则执行并 PASS；否则该用例自动 SKIP，不影响其它环境跑测试。

- [ ] **Step 3: 提交**

```bash
git add tests/test_match.py
git commit -m "test(match): 沉淀 8.jpg 案例，防止福寿单字被误锁进其它术语"
```

---

## Self-Review 记录

- **Spec 覆盖**：P0（出网诊断在人工验证环节提示，动态化 prompt 见 Task 1）、P1 检索层增强（Task 2）、P1 案例沉淀（Task 1 补词条 + Task 4 回归用例）、P2 unknown 呈现优化（Task 3）均有对应任务；图像局部裁剪增强（原方案里的 P2 图像项）不在本轮范围内，用户确认的三个决策点都已覆盖，图像清晰度优化留作后续独立小任务，不在此计划里强行塞入。
- **占位符检查**：所有步骤均给出完整代码/JSON/命令，无 TBD。
- **类型一致性**：`_ident_prompt()` 无参、`enable_search: bool` 在 `chat`/`chat_stream`/`iter_write_story`/`write_story` 间签名保持一致；`glossary.scene_visual_hints()` 返回 `(label, hint)` 的顺序与测试、prompt 拼接处一致。
