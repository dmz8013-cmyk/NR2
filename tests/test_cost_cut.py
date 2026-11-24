"""API 비용 절감 패치(2026-11-24) 테스트. 실행: python3 tests/test_cost_cut.py"""
import os
import sys
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import api_usage
import score_cascade
import url_dedup


def _resp(text, stop="end_turn"):
    return NS(content=[NS(type="text", text=text)], stop_reason=stop,
              usage=NS(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0,
                       cache_read_input_tokens=0, server_tool_use=None))


class FakeClient:
    """model 별 응답을 정해 두고 호출 기록을 남긴다."""
    def __init__(self, by_model):
        self.by_model, self.calls = by_model, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self.by_model[kw["model"]]


def _parse(r):
    import json
    t = r.content[0].text
    return json.loads(t[t.find("{"):t.rfind("}") + 1])


def _run(haiku_text, sonnet_text='{"score": 6}', haiku_stop="end_turn"):
    os.environ.pop("SCORE_CASCADE_ENABLED", None)
    os.environ.pop("SCORE_CASCADE_BAND", None)
    c = FakeClient({"claude-haiku-5-5": _resp(haiku_text, haiku_stop),
                    "claude-sonnet-5-5": _resp(sonnet_text)})
    r, model, parsed = score_cascade.score(c, content=[{"type": "text", "text": "x"}],
                                           parse=_parse, max_tokens=600)
    return c, model, parsed


def test_cascade_low_score_stays_on_haiku():
    c, model, p = _run('{"score": 3}')
    assert model == "claude-haiku-5-5" and p["score"] == 3 and len(c.calls) == 1
    assert c.calls[0]["thinking"] == {"type": "disabled"} and c.calls[0]["max_tokens"] == 600


def test_cascade_high_score_stays_on_haiku():
    c, model, p = _run('{"score": 9}')
    assert model == "claude-haiku-5-5" and len(c.calls) == 1


def test_cascade_band_escalates_to_sonnet():
    for s in (5, 7, 8):
        c, model, p = _run('{"score": %d}' % s, '{"score": 7}')
        assert model == "claude-sonnet-5-5" and p["score"] == 7 and len(c.calls) == 2
        assert c.calls[1]["thinking"] == {"type": "between_tools"}


def test_cascade_parse_failure_and_truncation_escalate():
    c, model, _ = _run("not json")
    assert model == "claude-sonnet-5-5"
    c, model, _ = _run('{"score": 2}', haiku_stop="max_tokens")
    assert model == "claude-sonnet-5-5"


def test_cascade_switch_off_is_sonnet_only():
    os.environ["SCORE_CASCADE_ENABLED"] = "false"
    try:
        c = FakeClient({"claude-sonnet-5-5": _resp('{"score": 2}')})
        _, model, _ = score_cascade.score(c, content=[], parse=_parse, max_tokens=500)
        assert model == "claude-sonnet-5-5" and len(c.calls) == 1
    finally:
        os.environ.pop("SCORE_CASCADE_ENABLED", None)


def test_cascade_fast_model_error_falls_back():
    class Boom(FakeClient):
        def create(self, **kw):
            self.calls.append(kw)
            if kw["model"] == "claude-haiku-5-5":
                raise RuntimeError("400 bad param")
            return _resp('{"score": 4}')
    c = Boom({})
    _, model, p = score_cascade.score(c, content=[], parse=_parse, max_tokens=600)
    assert model == "claude-sonnet-5-5" and p["score"] == 4 and len(c.calls) == 2


def test_cost_cache_read_and_web_search():
    f = {"in": 0, "out": 0, "cw": 0, "cr": 1_000_000, "ws": 0}
    assert abs(api_usage.cost_usd("claude-sonnet-5-5", f) - 0.10) < 1e-9   # 0.05x × $2
    assert abs(api_usage.cost_usd("claude-haiku-4-5", f) - 0.10) < 1e-9    # 0.1x × $1
    f = {"in": 0, "out": 0, "cw": 0, "cr": 0, "ws": 128}
    assert abs(api_usage.cost_usd("claude-haiku-4-5", f) - 1.28) < 1e-9
    assert api_usage._fields({"input_tokens": 3, "server_tool_use": {"web_search_requests": 2}})["ws"] == 2


def test_install_records_every_call_with_caller_label():
    from anthropic.resources.messages import Messages
    recorded = []
    orig_record, orig_create = api_usage.record, Messages.create
    Messages.create = lambda self, **kw: _resp("ok")
    api_usage._INSTALLED = False
    api_usage.record = lambda label, model, usage, day=None: recorded.append((label, model))
    try:
        assert api_usage.install()
        import anthropic
        anthropic.Anthropic(api_key="x").messages.create(model="claude-haiku-5-5", max_tokens=5, messages=[])
    finally:
        Messages.create = orig_create
        api_usage.record = orig_record
        api_usage._INSTALLED = False
    assert recorded == [("test_cost_cut.test_install_records_every_call_with_caller_label@claude-haiku-5-5",
                         "claude-haiku-5-5")]


def test_url_normalize_and_unique():
    a = "http://www.Example.com/news/1/?utm_source=x&id=3#top"
    b = "https://example.com/news/1?id=3&fbclid=zz"
    assert url_dedup.normalize(a) == url_dedup.normalize(b)
    assert url_dedup.normalize("https://ex.com/a?id=1") != url_dedup.normalize("https://ex.com/a?id=2")
    seen = set()
    l1, d1 = url_dedup.unique([{"link": a}, {"link": b}, {"title": "no link"}], "link", seen)
    l2, d2 = url_dedup.unique([{"link": b}], "link", seen)
    assert (len(l1), d1, len(l2), d2) == (2, 1, 0, 1)


def test_aesa_prompt_and_parser():
    import aesa_monitoring_bot as bot
    assert '"reason"' not in bot.PROMPT_FIXED and bot.SCORE_MAX_TOKENS == 600
    assert bot._parse_score_json('xx {"score": 7, "lenses": ["A"]} yy')["score"] == 7
    assert bot._parse_score_json('{"score": 8, "lenses": ["A"], "korean_summary": "잘')["score"] == 8
    assert bot._parse_score_json("no json") is None


if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print(f"PASS {name}")
            except AssertionError as e:
                fails += 1; print(f"FAIL {name}: {e}")
            except Exception as e:
                fails += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
