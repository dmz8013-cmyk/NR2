"""고정값 사전(config/fixed_facts.json) 대조 테스트.

실행: python3 tests/test_fixed_facts.py  (pytest 도 가능)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fixed_facts import check_text, load_fixed_facts, fixed_facts_context

def _ids(text):
    return sorted(v["id"] for v in check_text(text))

def test_rules_load():
    ids = {r["id"] for r in load_fixed_facts()}
    assert {"교섭단체_요건", "한은_기준금리", "연준_기준금리", "한동훈", "천하람", "워시_연준의장"} <= ids
    assert "20석" in fixed_facts_context()

def test_negotiation_group_wrong_seats():
    assert _ids("교섭단체 요건인 30석을 채우지 못했어요.") == ["교섭단체_요건"]
    assert _ids("교섭단체 구성 요건은 20석이에요.") == []
    assert _ids("20석이 안 되면 교섭단체가 될 수 없어요.") == []

def test_rates():
    assert _ids("한국은행이 기준금리를 연 3.25%로 올렸어요.") == ["한은_기준금리"]
    assert _ids("한국은행이 기준금리를 연 3.00%로 동결했어요.") == []
    assert _ids("연준은 기준금리를 4.25~4.50%로 유지했어요.") == ["연준_기준금리"]
    assert _ids("연준은 기준금리를 3.75~4.00%로 유지했어요.") == []

def test_persons():
    assert _ids("천하람 조국혁신당 원내대표가 밝혔어요.") == ["천하람"]
    assert _ids("천하람 개혁신당 원내대표가 밝혔어요.") == []
    assert _ids("한동훈 국민의힘 대표가 말했어요.") == ["한동훈"]
    assert _ids("한동훈 국민의힘 전 대표가 말했어요.") == []
    assert _ids("한동훈 무소속 의원이 말했어요.") == []
    assert _ids("김민석 총리가 발표했어요.") == ["김민석"]
    assert _ids("김민석 전 총리 시절 이야기예요.") == []
    assert _ids("김민석 더불어민주당 대표가 발표했어요.") == []
    assert _ids("한병도 대표가 말했어요.") == ["한병도"]
    assert _ids("한병도 원내대표가 말했어요.") == []
    assert _ids("장동혁 원내대표가 말했어요.") == ["장동혁"]
    assert _ids("장동혁 국민의힘 대표가 말했어요.") == []
    assert _ids("정점식 대표가 말했어요.") == ["정점식"]
    assert _ids("정점식 국민의힘 원내대표가 말했어요.") == []
    assert _ids("파월 연준 의장이 말했어요.") == ["워시_연준의장"]
    assert _ids("파월 전 연준 의장이 말했어요.") == []
    assert _ids("워시 연준 의장이 말했어요.") == []

def test_multiple_violations_in_card_text():
    text = "교섭단체 30석 요건\n천하람 조국혁신당 원내대표"
    assert _ids(text) == ["교섭단체_요건", "천하람"]

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
