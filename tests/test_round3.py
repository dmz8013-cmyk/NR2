"""3차 보강 테스트 — 기록·출처 태깅/우선순위/상한, 구단명 교정, 기보도 제거, 미래 완료형. 실행: python3 tests/test_round3.py"""
import sys, os, types
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ("anthropic", "psycopg2", "feedparser", "requests"):
    try: __import__(m)
    except ImportError: sys.modules[m] = types.ModuleType(m)
from verify_pass import tag_item, _load_known_names, priority_of, max_verify_for, is_mandatory, _with_source
from sports_names import fix_team_names
from prior_coverage import filter_prior_coverage, is_new_development
from ai_briefing import is_future_completion
KNOWN = _load_known_names()

def test_record_claim_mandatory():
    r = tag_item("최원준 선수가 204안타 기록으로 한국 야구 역사에 새로운 이정표를 세움. KT 위즈는 8연승 달성.", KNOWN)
    assert any(x.startswith("기록 주장") for x in r) and is_mandatory(r)
    assert not is_mandatory(["실명 발언: 홍길동"])

def test_source_needed_tagging():
    r = tag_item("비트와이즈의 XRP 현물 ETF가 하루 1055만 달러의 자금 유입을 기록했음.", KNOWN)
    assert "수치 출처 필요" in r and is_mandatory(r)
    r2 = tag_item("SoSoValue 집계 기준 XRP 현물 ETF에 1055만 달러가 유입됐음.", KNOWN)
    assert "수치 출처 필요" not in r2
    r3 = tag_item("중국의 9월 외환보유액이 3조 4002억 달러 수준으로 집계되어 전월 대비 1.11% 감소했음.", KNOWN)
    assert "수치 출처 필요" in r3

def test_priorities_by_family():
    assert priority_of(["수치+단정 종결"], "ai_morning") == 1 and priority_of(["실명 발언: a"], "ai_morning") == 2
    assert priority_of(["실명 발언: a"], "political_evening") == 1 and priority_of(["기록 주장: 최다"], "political_evening") == 2
    assert priority_of(["미등재 인명+직함: x 의원"], "ai_morning") == 0 and priority_of(["상태변화 동사: 가결"], "ai_morning") == 3

def test_general_cap_env():
    os.environ.pop("VERIFY_MAX_GENERAL", None)
    assert max_verify_for("ai_morning") == 14
    os.environ["VERIFY_MAX_GENERAL"] = "8"
    assert max_verify_for("ai_evening") == 8
    os.environ.pop("VERIFY_MAX_GENERAL", None)

def test_with_source():
    assert _with_source("XRP ETF가 1055만 달러 유입을 기록했음.", "", "SoSoValue") == "XRP ETF가 1055만 달러 유입을 기록했음 (SoSoValue 집계)."
    assert _with_source("A가 1055만 달러 유입.", "SoSoValue 집계 기준 A가 1055만 달러 유입.", "SoSoValue").startswith("SoSoValue")

def test_team_name_fix():
    t = "🎯 기타\n\n▪ 프로농구 KCC 크루저가 킹 선수의 29점 활약으로 가스공사를 103-98으로 제압했음. 가스공사는 3연패.\n▪ KIA 타이거즈가 롯데 자이언츠를 완파했음."
    out, fixes = fix_team_names(t)
    assert "부산 KCC 이지스" in out and "대구 한국가스공사 페가수스를 103-98" in out and "KCC 크루저" not in out
    assert len(fixes) == 1 and "KCC 크루저→부산 KCC 이지스" in fixes[0]
    out2, f2 = fix_team_names("▪ 한국가스공사가 LNG 요금을 인상했음.")   # 농구 맥락 없음 → 손대지 않음
    assert f2 == [] and "페가수스" not in out2

def test_prior_coverage():
    prior = [{"type": "ai_evening", "created_at": datetime(2026, 10, 7, 18, 1), "text": "윤석열 전 대통령이 명태균 관련 혐의 2심에서 무죄 판결을 받았음. 재판부는 입증 부족으로 판단했음."},
             {"type": "ai_evening", "created_at": datetime(2026, 10, 7, 18, 1), "text": "누리호 5차 발사가 성공해 위성 분리를 확인했음."}]
    b = "🏛️ 정치/시사\n\n▪ 윤석열 전 대통령이 명태균 여론조사업체 운영 이력 인물 관련 혐의로 2심 무죄 판정. 재판부는 입증 부족 판단.\n▪ 누리호가 주탑재 위성 5기의 지상국 교신에 성공하면서 발사 '최종 성공'을 확정했음.\n▪ 한미약품이 국산 최초 GLP-1 비만약 허가를 획득했음."
    out, ex, kept = filter_prior_coverage(b, prior)
    assert len(ex) == 1 and ex[0].startswith("윤석열") and "윤석열" not in out
    assert len(kept) == 1 and kept[0].startswith("누리호") and "한미약품" in out
    assert is_new_development("법안이 가결됐음", "법안이 상정됐음") and not is_new_development("법안 상정 1건 2건", "법안이 상정됐음")

def test_ambiguous_title_names():
    for t in ("중국의 9월 외환보유액이 3조 4002억 달러로 집계되어 감소폭이 시장 예상치를 상회했음.",
              "암호화폐 시장의 보안 이슈로 유로폴이 경고했음.", "여자배구 국가대표팀이 리그 감독 체제를 재정비했음."):
        assert not any(x.startswith("미등재") or x.startswith("실명") for x in tag_item(t, KNOWN)), t
    assert "미등재 인명+직함: 오세훈 시장" in tag_item("오세훈 시장이 부동산 정책을 지적했음.", KNOWN)

def test_launch_tag_and_untagged_fill():
    r = tag_item("미국·국내 주식 기반 토큰이 아비트럼 네트워크의 유니스왑 앱에 신규 출시됐음.", KNOWN)
    assert any(x.startswith("출시 주장") for x in r) and priority_of(r, "ai_morning") == 1
    assert priority_of(["잔여 검색"], "ai_morning") == 4

def test_correction_guard_rumor():
    from verify_pass import _sane_correction
    o = "KCC가 가스공사를 103-98로 제압했음."
    assert not _sane_correction(o, "KCC가 가스공사를 98-103으로 제압한 것으로 전해졌다.", KNOWN)

def test_future_completion():
    assert is_future_completion("현대차그룹 이달 남양 연구소에서 '미래차 10년' 비전 발표. 전기차·수소연료 기술 개발 방향과 투자 계획 공개.")
    assert not is_future_completion("현대차그룹이 이달 남양 연구소에서 '미래차 10년' 비전을 발표할 예정.")
    assert not is_future_completion("한미약품이 국산 최초 비만약 허가를 획득했음.")

if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try: fn(); print(f"PASS {name}")
            except AssertionError as e: fails += 1; print(f"FAIL {name}: {e}")
            except Exception as e: fails += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
