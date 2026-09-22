import json
from unittest.mock import patch

import pytest

from app import agent, llm


def test_visual_prompt_has_no_local_glossary():
    with patch.object(agent.glossary, 'inscription_terms', side_effect=AssertionError('local bias')):
        prompt = agent._ident_prompt()
    assert '回头是岸' not in prompt
    assert '万峰林' not in prompt
    assert '优先' in prompt


def test_ident_prompt_uses_ip_scope_then_expands():
    hangzhou = agent._ident_prompt('浙江杭州')
    assert '浙江杭州' in hangzhou
    assert '优先' in hangzhou
    assert '扩大' in hangzhou
    leshan = agent._ident_prompt('四川乐山')
    assert '四川乐山' in leshan
    assert '杭州' not in leshan


def test_search_requires_actual_tool_execution():
    with patch.object(llm, '_request', return_value={'output': []}):
        with pytest.raises(RuntimeError, match='搜索'):
            llm.search_response('核验', 'image/jpeg', 'YWJj')


def test_search_keeps_provider_sources_not_model_invented_links():
    payload = {'status': 'completed', 'output': [
        {'type': 'web_search_call', 'status': 'completed', 'action': {'sources': [{'url': 'https://example.org/proof'}]}},
        {'type': 'message', 'content': [{'type': 'output_text', 'text': '{"label_zh":"新地点"}'}]},
    ]}
    with patch.object(llm, '_request', return_value=payload) as call:
        text, sources = llm.search_response('核验', 'image/jpeg', 'YWJj')
    assert sources == ['https://example.org/proof']
    assert json.loads(text)['label_zh'] == '新地点'
    assert call.call_args.args[1]['tool_choice'] == 'required'


def test_verify_ident_searches_ip_scope_first():
    with patch.object(llm, 'search_response', return_value=(json.dumps({'label_zh': '新地点', 'decision': 'possible'}), [])) as call:
        agent.verify_ident({'label_zh': '旧地点', 'features': ['双塔']}, 'image/jpeg', 'YWJj', scope='浙江杭州')
    prompt = call.call_args.args[0]
    assert '浙江杭州' in prompt
    assert '由近到远' in prompt


def test_verification_updates_label_and_uses_picture_features():
    initial = {'label_zh': '旧地点', 'features': ['双塔', '石桥'], 'candidates': []}
    with patch.object(llm, 'search_response', return_value=(json.dumps({'label_zh': '新地点', 'decision': 'probable'}), ['https://example.org'])) as call:
        result = agent.verify_ident(initial, 'image/jpeg', 'YWJj')
    assert result['label_zh'] == '新地点'
    assert '双塔' in call.call_args.args[0]
    assert '瀑布' not in call.call_args.args[0]


def test_chinese_delivered_before_translations_and_no_search():
    calls = []
    def stream(messages, **kwargs):
        calls.append((messages, kwargs))
        yield '中文正文' if len(calls) == 1 else 'Translation'
    with patch.object(llm, 'chat_stream', side_effect=stream):
        gen = agent.iter_write_story({'label_zh': '陌生地点'}, '{}', '')
        first = next(gen)
        assert first[3] == ['zh']
        assert len(calls) == 1
        results = list(gen)
    assert len(results) == 6
    assert all(not kw['enable_search'] for _, kw in calls)
    assert all('七语' not in messages[0]['content'] for messages, _ in calls)
    assert all('中文正文' in messages[-1]['content'] for messages, _ in calls[1:])


def test_story_prompt_tells_named_place_story_not_visual_forensics():
    calls = []
    def stream(messages, **kwargs):
        calls.append(messages)
        yield '故事'
    ident = {'label_zh': '回头是岸', 'ocr_text': '回头是岸', 'features': ['苔藓', '蕨类'], 'reason': '南方丹霞也有类似'}
    with patch.object(llm, 'chat_stream', side_effect=stream):
        next(agent.iter_write_story(ident, '{}', '南方多处丹霞亦有相同题刻'))
    system, user = calls[0][0]['content'], calls[0][1]['content']
    assert '导游' in system
    assert '回头是岸' in user
    assert '先说画面' not in user
    assert '保持地点的不确定性' not in system
    assert '苔藓' not in user
    assert '南方多处丹霞' not in user
    assert '不要写「尚难确定」' in user


def test_story_prompt_unknown_does_not_invent_place():
    calls = []
    def stream(messages, **kwargs):
        calls.append(messages)
        yield '未确认'
    with patch.object(llm, 'chat_stream', side_effect=stream):
        next(agent.iter_write_story({'label_zh': '无法确定'}, '{}', ''))
    user = calls[0][1]['content']
    assert '不要编造乐山' in user
    assert '手选场景' in user


def test_correction_options_skips_current_and_unknown():
    ident = {
        "label_zh": "回头是岸",
        "ocr_text": "回头是岸",
        "candidates": [
            {"name": "回头是岸"},
            {"name": "凌云寺"},
            {"name": "乐山大佛"},
            {"name": "嘉阳小火车"},
            {"name": "无法确定"},
        ],
    }
    names = [item["label_zh"] for item in agent.correction_options(ident)]
    assert "回头是岸" not in names
    assert "无法确定" not in names
    assert names[:2] == ["凌云寺", "乐山大佛"]
    assert len(names) <= 3


def test_relabel_keeps_session_and_updates_label():
    ident = {
        "scene": "photo",
        "label_zh": "旧名",
        "confidence": 0.4,
        "reason": "初判",
        "ocr_text": "",
        "candidates": [{"name": "凌云寺"}],
    }

    def story(data, *args, **kwargs):
        assert data["label_zh"] == "凌云寺"
        yield [], {"zh": "新讲解"}, {}, ["zh"]

    with patch.object(agent, "iter_write_story", side_effect=story):
        payload = agent.create_session(ident, [], {"zh": "旧讲解"}, {})
        sid = payload["session_id"]
        assert any(item["label_zh"] == "凌云寺" for item in payload["corrections"])
        out = agent.relabel(sid, "凌云寺")
    assert out["session_id"] == sid
    assert out["label_zh"] == "凌云寺"
    assert out["intro"]["zh"] == "新讲解"


def test_relabel_failure_keeps_previous_intro():
    ident = {
        "scene": "photo",
        "label_zh": "旧名",
        "confidence": 0.4,
        "reason": "初判",
        "ocr_text": "",
    }

    def boom(*args, **kwargs):
        raise RuntimeError("模型响应超时")
        yield None

    with patch.object(agent, "iter_write_story", side_effect=boom):
        payload = agent.create_session(ident, [], {"zh": "旧讲解"}, {})
        sid = payload["session_id"]
        with pytest.raises(RuntimeError, match="超时"):
            agent.relabel(sid, "峰林布依")
    assert agent.SESSIONS[sid]["intro"]["zh"] == "旧讲解"
    assert agent.SESSIONS[sid]["label_zh"] == "旧名"


def test_iter_relabel_emits_progress_before_done():
    ident = {
        "scene": "photo",
        "label_zh": "旧名",
        "confidence": 0.4,
        "reason": "初判",
        "ocr_text": "",
    }

    def story(data, *args, **kwargs):
        yield [], {"zh": "新讲解"}, {}, ["zh"]
        yield [], {"zh": "新讲解", "en": "new"}, {}, ["en"]

    with patch.object(agent, "iter_write_story", side_effect=story):
        payload = agent.create_session(ident, [], {"zh": "旧讲解"}, {})
        events = list(agent.iter_relabel(payload["session_id"], "峰林布依"))
    assert events[0]["type"] == "status"
    assert [ev["type"] for ev in events if ev["type"] in ("partial", "done")] == ["partial", "partial", "done"]
    assert events[-1]["result"]["label_zh"] == "峰林布依"
    assert events[-1]["result"]["intro"]["en"] == "new"


def test_failed_language_does_not_discard_other_languages():
    def stream(messages, **kwargs):
        if '日文' in messages[0]['content']:
            raise RuntimeError('timeout')
        yield '正文'
    with patch.object(llm, 'chat_stream', side_effect=stream):
        results = list(agent.iter_write_story({'label_zh': '陌生地点'}, '{}', ''))
    assert len(results) == 7
    assert results[-1][1]['en']
    assert '失败' in results[-1][1]['ja']


def test_verified_identity_reaches_session_and_story():
    initial = {'label_zh': '旧地点', 'scene': 'photo', 'confidence': 0.4, 'reason': '初判', 'features': ['双塔']}
    verified = {**initial, 'label_zh': '新地点', 'decision': 'probable', 'sources': ['https://example.org']}
    def story(data, *args, **kwargs):
        assert data['label_zh'] == '新地点'
        yield [], {'zh': '介绍'}, {}, ['zh']
    with patch.object(agent.ocrutil, 'read_texts', return_value=[]), \
         patch.object(agent, 'identify_from_image', return_value=(initial, initial, '{}')), \
         patch.object(agent, 'verify_ident', return_value=verified), \
         patch.object(agent, 'iter_write_story', side_effect=story):
        events = list(agent.iter_photo_progress('image/jpeg', 'YWJj', original=b'abc'))
    final = events[-1]['result']
    assert final['label_zh'] == '新地点'
    assert final['sources'] == ['https://example.org']
    assert final['decision'] == 'probable'


def test_search_failure_does_not_confirm_candidate():
    initial = {'label_zh': '旧地点', 'scene': 'photo', 'confidence': 0.9, 'reason': '初判'}
    with patch.object(agent.ocrutil, 'read_texts', return_value=[]), \
         patch.object(agent, 'identify_from_image', return_value=(initial, initial, '{}')), \
         patch.object(agent, 'verify_ident', side_effect=RuntimeError('搜索失败')), \
         patch.object(agent, 'iter_write_story', return_value=iter([([], {'zh': '待核实'}, {}, ['zh'])])):
        events = list(agent.iter_photo_progress('image/jpeg', 'YWJj', original=b'abc'))
    final = events[-1]['result']
    assert final['decision'] == 'possible'
    assert final['sources'] == []
    assert '未完成' in final['reason']


def test_unrelated_glossary_terms_not_sent_to_story():
    with patch.object(agent.glossary, 'all_terms', return_value=[{'zh': '本地景点'}, {'zh': '已识别地点'}]):
        assert agent.story_terms({'label_zh': '已识别地点'}) == [{'zh': '已识别地点'}]


def test_missing_cited_evidence_prevents_confirmation():
    with patch.object(llm, 'search_response', return_value=(json.dumps({'label_zh': '候选', 'decision': 'confirmed', 'evidence_urls': ['https://invented.test']}), ['https://real.test'])):
        result = agent.verify_ident({}, 'image/jpeg', 'YWJj')
    assert result['decision'] == 'possible'
    assert result['sources'] == []


@pytest.mark.parametrize('finish', ['length', None])
def test_incomplete_stream_is_not_reported_as_success(finish):
    from io import BytesIO
    class Response(BytesIO):
        headers = {'Content-Type': 'text/event-stream'}
    data = {'choices': [{'delta': {'content': 'partial'}, 'finish_reason': finish}]}
    response = Response(('data: ' + json.dumps(data) + '\n').encode())
    with patch.object(llm, 'LLM_API_KEY', 'test'), patch.object(llm, 'LLM_BASE_URL', 'https://example.test'), \
         patch('urllib.request.urlopen', return_value=response):
        with pytest.raises(RuntimeError):
            list(llm.chat_stream([]))
