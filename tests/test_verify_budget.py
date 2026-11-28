"""검증 패스 검색 상한 차등(2026-11-28). 실행: python3 -m pytest tests/test_verify_budget.py"""
import os
import sys
import tempfile
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import verify_pass as vp


def test_searches_for_high_risk_keeps_two():
    for reasons in (["기록 주장: 사상 최대"], ["수치 출처 필요"], ["수치 방향: 상회"],
                    ["미등재 인명+직함: 홍길동 장관", "실명 발언: 홍길동"]):
        assert vp.searches_for(reasons) == 2, reasons


def test_searches_for_others_use_one():
    for reasons in (["실명 발언: 김민석"], ["수치+단정 종결"], ["상태변화 동사: 가결"], ["잔여 검색"]):
        assert vp.searches_for(reasons) == 1, reasons


def test_env_overrides_restore_old_behavior():
    os.environ["VERIFY_MAX_SEARCHES"] = "2"
    os.environ["VERIFY_MAX_SEARCHES_HIGH"] = "3"
    try:
        assert vp.searches_for(["잔여 검색"]) == 2
        assert vp.searches_for(["수치 출처 필요"]) == 3
    finally:
        os.environ.pop("VERIFY_MAX_SEARCHES")
        os.environ.pop("VERIFY_MAX_SEARCHES_HIGH")


class _FakeClient:
    """모든 검증 호출에 '일치' JSON 을 돌려주고 tools.max_uses 를 기록한다."""
    seen = []

    def __init__(self, *a, **k):
        self.messages = self

    def create(self, **kw):
        _FakeClient.seen.append((kw["messages"][0]["content"][-80:], kw["tools"][0]["max_uses"]))
        text = ('{"verdict": "일치", "corrected": "", "matched_name": true, '
                '"matched_keywords": ["가", "나"], "newest_pub_date": "", "person_exists": true, '
                '"direction_ok": true, "source_org": "", "event_date": ""}')
        return NS(content=[NS(type="text", text=text)],
                  usage=NS(server_tool_use=NS(web_search_requests=kw["tools"][0]["max_uses"])))


def test_run_passes_budget_to_web_search_tool():
    briefing = ("🏛️ 정치\n"
                "▪ 코스피가 사상 최대 거래대금을 기록했다.\n"       # 기록 주장 → 필수 → 2회
                "▪ 국회 본회의에서 예산안이 가결됐다.\n")         # 상태변화 → 1회
    orig = (vp.anthropic.Anthropic, vp.CACHE_PATH, os.environ.get("ANTHROPIC_API_KEY"))
    vp.anthropic.Anthropic = _FakeClient
    vp.CACHE_PATH = os.path.join(tempfile.mkdtemp(), "c.json")
    os.environ["ANTHROPIC_API_KEY"] = "test"
    _FakeClient.seen = []
    try:
        _, stats, _ = vp.run_verify_pass_ex(briefing, "ai_morning", enqueue=False)
    finally:
        vp.anthropic.Anthropic, vp.CACHE_PATH = orig[0], orig[1]
        if orig[2] is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = orig[2]
    budgets = sorted(m for _, m in _FakeClient.seen)
    assert budgets == [1, 2], _FakeClient.seen
    assert stats["budget_high"] == 1 and stats["budget_low"] == 1 and stats["searches"] == 3
