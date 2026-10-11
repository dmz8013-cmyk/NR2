"""4차 보강 테스트 — 기보도 새 전개 규칙, 코인 상한, 예측시장, 스포츠 주체, 사건 시점, 당일 일정 시제, 사전. 실행: python3 tests/test_round4.py"""
import sys, os, types
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ("anthropic", "psycopg2", "feedparser", "requests"):
    try: __import__(m)
    except ImportError: sys.modules[m] = types.ModuleType(m)
import prior_coverage as pc
from briefing_guards import enforce_coin_cap, enforce_prediction_market
from sports_names import check_subject_conflicts, fix_subject_conflicts, fix_team_names, load_players
from verify_pass import stale_event, _section_of
from ai_briefing import is_future_completion

NEW = "윤호중 행안부 장관의 지시로 중수청이 임은정 청장에 대한 감찰을 진행하게 됨. 임은정 중수청 초대 청장이 감찰 대상이 되는 상황으로, 중수청 출범 후 기강 논란과 함께 기관의 독립성·공정성 문제가 제기되는 중."
PRIOR = [{"type": "ai_evening", "created_at": datetime(2026, 10, 11, 18, 0), "text": "임은정 중수청 초대 청장이 중수청 자체에 대한 감찰을 받게 됐다고 밝혔음. 임 청장은 관련 논란에 대해 \"안타깝고 서글프지만 잘 대처하겠다\"고 발언했음."},
         {"type": "political_afternoon", "created_at": datetime(2026, 10, 11, 13, 0), "text": "윤호중 행정안전부 장관, 임은정 광주중수청장 감찰 지시…\"중수청을 정치기관으로 착각, 검찰의 잘못된 관행 우려\""}]

def test_prior_imeunjeong_excluded_now():
    out, ex, kept = pc.filter_prior_coverage("🏛️ 정치/시사\n\n▪ " + NEW + "\n▪ 한미약품이 신약 허가를 받았음.", PRIOR)
    assert len(ex) == 1 and ex[0].startswith("윤호중") and kept == [] and "한미약품" in out

def test_new_development_rules():
    assert not pc.is_new_development("A가 중수청 출범 후 논란 제기", "A가 논란을 제기했음")      # '출범'은 표지어 아님
    assert pc.is_new_development("A가 '즉각 사퇴하라'고 발언", "A가 발언했음")                   # 새 인용
    assert pc.is_new_development("법안이 가결됐음", "법안이 상정됐음")                            # 새 결정
    assert pc.is_new_development("예산 12억 원, 3건 통보", "예산 집행 부적정 통보")                # 새 수치 2개
    assert pc.same_person_event(NEW, PRIOR[1]["text"])

def test_coin_cap():
    b = ("💰 경제/산업\n\n▪ 한은이 금리를 동결했음.\n📈 시세(Upbit 기준): 비트코인 1억원\n\n⸻⸻⸻⸻\n\n🤖 AI/기술\n\n"
         "▪ 비트코인 8만 달러 도달 계약 실현 확률 63%.\n▪ 암호화폐 시장에서 24시간 동안 2,089만 달러 규모의 레버리지 포지션 청산이 발생함.\n▪ NVIDIA GPU 구조 공개됨.")
    out, dropped, moved = enforce_coin_cap(b)
    assert len(dropped) == 1 and dropped[0].startswith("암호화폐 시장") and len(moved) == 1
    lines = out.split("\n"); i_e = lines.index("💰 경제/산업"); i_ai = next(i for i, l in enumerate(lines) if l.startswith("🤖"))
    assert any("8만 달러" in l for l in lines[i_e:i_ai]) and not any("비트코인 8만" in l for l in lines[i_ai:]) and "NVIDIA" in out
    assert "📈 시세" in out

def test_prediction_market_guard():
    b = "🤖 AI/기술\n\n▪ 비트코인 8만 달러 도달 계약 실현 확률 63%. 지난주 13포인트 상승.\n▪ NVIDIA GPU 구조 공개됨."
    out, dropped = enforce_prediction_market(b, ["폴리마켓 '비트코인 8만 달러 하락' 계약 확률 63%로 상승"])
    assert len(dropped) == 1 and "8만 달러" not in out and "NVIDIA" in out
    out2, d2 = enforce_prediction_market(b, ["비트코인 8만 달러 도달 확률 63%…폴리마켓"])
    assert d2 == [] and "8만 달러" in out2

def test_sports_subject_conflict():
    assert load_players().get("한동희") == "롯데 자이언츠"
    b = "🎯 기타\n\n▪ 롯데 자이언츠가 KIA 타이거즈를 상대로 한동희의 만루포로 무너지면서 3위 싸움의 판도가 바뀔 전망."
    c = check_subject_conflicts(b)
    assert len(c) == 1 and c[0]["player"] == "한동희" and c[0]["team"] == "롯데 자이언츠"
    assert check_subject_conflicts("▪ KIA 타이거즈가 한동희의 만루포로 무너지면서 패배.") == []   # KIA 가 롯데 한동희에게 무너짐 = 정상
    out, notes = fix_subject_conflicts(b, None)
    assert "한동희" not in out and notes and "삭제" in notes[0]

def test_kovo_soop():
    out, fixes = fix_team_names("▪ 여수 코보컵 개막으로 여자배구 신생팀 숲의 신고식. 신규 진출팀의 리그 적응 시작.")
    assert "SOOP의 신고식" in out and "숲" not in out and fixes
    out2, f2 = fix_team_names("▪ 산림청이 도시 숲 조성 예산을 늘렸음.")
    assert f2 == [] and "숲" in out2

def test_stale_event_and_section_none():
    assert stale_event("NVIDIA GPU가 GPT-6 Astra 가속 구조가 공개됨.", "2026-10-01")
    assert not stale_event("NVIDIA GPU가 GPT-6 Astra 가속 구조가 공개됨.", datetime.now().strftime("%Y-%m-%d"))
    assert not stale_event("코스피가 상승 마감했음.", "2026-10-01")   # 공개·발표류 아님
    assert _section_of(["🏛️ 정치/시사", None, "▪ a", None, "▪ b"], 4).startswith("정치")

def test_morning_schedule_tense():
    t = "국정감사 2주차 행정안전위원회 경찰청 국감과 외교통일위원회 주미대사관 국감 진행. 야당이 경찰청 개혁과 외교 현안 중심으로 질의."
    assert is_future_completion(t, morning=True) and not is_future_completion(t, morning=False)
    assert not is_future_completion("행안위 경찰청 국감이 오늘 열릴 예정.", morning=True)

if __name__ == "__main__":
    import inspect
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try: fn(); print(f"PASS {name}")
            except AssertionError as e: fails += 1; print(f"FAIL {name}: {e}")
            except Exception as e: fails += 1; print(f"ERROR {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
