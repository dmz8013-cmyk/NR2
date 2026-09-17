"""렌더 전 콘텐츠 규칙(여론조사 병기) + 장소 고정값 테스트. 실행: python3 tests/test_content_rules.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from content_rules import check_poll_disclosure, check_issue
from fixed_facts import check_text

def test_poll_missing_all():
    v = check_poll_disclosure("이재명 대통령 지지율 58%로 상승")
    assert v and v[0]["id"] == "여론조사_병기" and "조사기관" in v[0]["found"] and "조사기간" in v[0]["found"]

def test_poll_complete():
    t = "한국갤럽이 9~11일 전화면접으로 조사한 결과 대통령 지지율 58%"
    assert check_poll_disclosure(t) == []

def test_poll_partial():
    v = check_poll_disclosure("리얼미터 조사 지지율 52.3%")
    assert v and v[0]["found"] == "누락: 조사방식·조사기간"

def test_not_poll():
    assert check_poll_disclosure("코스피 17% 급등") == []
    assert check_poll_disclosure("지지율 급등세라는 평가") == []   # 수치 없음

def test_check_issue_joins_fields():
    iss = {"title": "지지율 60% 돌파", "subtitle": "갤럽 조사", "bullets": ["ARS 조사"], "desc": "12~14일 조사 결과예요."}
    assert check_issue(iss) == []
    iss["desc"] = "상승세예요."
    assert check_issue(iss)[0]["found"] == "누락: 조사기간"

def test_place_rules():
    assert [v["id"] for v in check_text("용산 대통령실에서 브리핑")] == ["청와대_영빈관"]
    assert [v["id"] for v in check_text("영빈관 집무실에서 회의")] == ["청와대_영빈관"]
    assert check_text("청와대에서 국무회의를 주재했어요. 영빈관 국빈 만찬") == []

if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn(); print(f"PASS {name}")
            except AssertionError as e:
                fails += 1; print(f"FAIL {name}: {e}")
    sys.exit(1 if fails else 0)
