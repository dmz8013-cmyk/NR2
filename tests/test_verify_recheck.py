"""verify_pass 태깅·우선순위·상한 + recheck_queue 섹션 삽입 테스트. 실행: python3 tests/test_verify_recheck.py"""
import sys, os, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ("anthropic", "psycopg2"):
    try: __import__(m)
    except ImportError: sys.modules[m] = types.ModuleType(m)
from verify_pass import tag_item, _load_known_names, person_names, priority_of, max_verify_for, keywords_of
from recheck_queue import insert_into_section, family_of
KNOWN = _load_known_names()

def test_named_statement_tagged():
    r = tag_item("김준혁 의원이 '암살자(들)' 국감 진행의 위압성 지적…차분한 진행 요청", KNOWN)
    assert any(x.startswith("실명 발언: 김준혁") for x in r) and any(x.startswith("미등재 인명+직함: 김준혁 의원") for x in r)
    assert priority_of(r) == 0

def test_unknown_person_title_in_middle():
    r = tag_item("김지용 검찰 부국장 '과한 주장 제어' 발언으로 범여권 쪼개짐", KNOWN)
    assert "미등재 인명+직함: 김지용 부국장" in r

def test_org_not_person():
    r = tag_item("국회 법사위 위원장이 법안 상정을 촉구", KNOWN)
    assert not any(x.startswith("미등재") for x in r) and not any(x.startswith("실명") for x in r)
    assert person_names("여권의 '감금' 비판에 의원이 '제청권' 주장", KNOWN) == []

def test_known_name_speech_priority_and_keywords():
    t = "정점식 원내대표가 김현지 청와대 제1부속실장 국감 출석 촉구"
    r = tag_item(t, KNOWN)
    assert r == ["실명 발언: 정점식·김현지"] and priority_of(r) == 1
    kw = keywords_of(t, ["정점식", "김현지"])
    assert "정점식" not in kw and "국감" in kw and len(kw) <= 6

def test_participle_not_person():
    r = tag_item("박충권 의원이 지뢰 폭발을 '불의의 사고'로 규정한 대통령에 책임 추궁", KNOWN)
    assert not any("규정한" in x for x in r) and any(x.startswith("실명 발언: 박충권") for x in r)
    from verify_pass import _sane_correction
    o = "김준혁 의원이 영화 '암살자(들)' 국감 진행의 과도한 위압성 지적…차분한 진행 요청"
    assert _sane_correction(o, "김준혁 의원이 국감 진행의 위압성을 지적하고 차분한 진행을 요청", KNOWN)
    assert not _sane_correction(o, "위원장의 위압적인 회의 진행에 지나치게 위압적인 목소리로는", KNOWN)


def test_caps():
    os.environ.pop("VERIFY_MAX_POLITICS", None)
    assert max_verify_for("political_afternoon") == 14 and max_verify_for("political_evening") == 14
    os.environ["VERIFY_MAX_POLITICS"] = "10"
    assert max_verify_for("political_evening") == 10 and max_verify_for("ai_morning") == 8
    os.environ["VERIFY_MAX_POLITICS"] = "abc"
    assert max_verify_for("political_evening") == 14
    os.environ.pop("VERIFY_MAX_POLITICS", None)
    assert max_verify_for("ai_morning") == 8 and max_verify_for("ai_evening") == 8
    assert family_of("political_evening") == "politics" and family_of("ai_morning") == "general"

def test_insert_into_section():
    b = "제목\n\n🇰🇷 이재명 정부 🇰🇷\n\n▪ a\n▪ b\n\n⸻⸻⸻⸻\n\n🟦 더불어민주당 🟦\n\n▪ c\n\n⸻⸻⸻⸻\n\n🟥 국민의힘 🟥\n\n▪ d"
    out = insert_into_section(b, "더불어민주당", "복귀 항목")
    lines = out.split("\n")
    i = lines.index("▪ c")
    assert lines[i + 1] == "▪ 복귀 항목" and out.count("▪ 복귀 항목") == 1
    out2 = insert_into_section(b, "없는섹션", "x")
    assert out2.split("\n").index("▪ x") == out2.split("\n").index("▪ b") + 1

if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try: fn(); print(f"PASS {name}")
            except AssertionError as e: fails += 1; print(f"FAIL {name}: {e}")
            except Exception as e: fails += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
