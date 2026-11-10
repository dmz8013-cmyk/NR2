"""4슬롯 공통 발행 관문(publish_guard) 회귀 — 11/9 18:00 흥국생명·삼성라이온즈, 11/10 13:00 김민석·이주영."""
import os, sys
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import publish_guard as pg
import tense_guard as tg

KST = ZoneInfo("Asia/Seoul")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PINK = "인천 흥국생명 핑크스파이더스가 시즌 경기서 패배했으나 최고시청률 7% 기록."
LIONS = "한국시리즈 우승팀인 삼성 라이온즈의 주가가 우승 후 하락하면서 개인투자자들의 아쉬움이 나타나고 있음."
JKN = "신인감독 김연경2 5회 분당 최고 7%…원더독스 역전승 예능 프로그램 신인감독 김연경2 5회에서 원더독스가 흥국생명을 상대로 역전승"
TOP = "‘신인감독 김연경2’ 필승 원더독스, 흥국생명 상대로 5세트 끝 역전승 MBC ‘신인감독 김연경2’ 5회에서 분당 최고 시청률 7.0%"
ASIAE = "\"한국시리즈 우승 기념 삼성 바겐세일 중\"…개미들 씁쓸한 주가 급락 밈 삼성 라이온즈가 12년 만에 한국시리즈 정상에 오르자"
HK = "\"삼성 우승 세일이죠?\"…삼전 개미들 '웃픈 반응' 터졌다 삼성전자 주가 하락에 온라인상에서 자조적 반응"


def test_program_name_inserted_unquoted_source():
    new, note = pg.check_program(PINK, JKN)
    assert note and new.startswith("'신인감독 김연경2' 방송에서")


def test_program_name_inserted_quoted_source():
    new, note = pg.check_program(PINK, TOP)
    assert "신인감독 김연경2" in new


def test_program_name_missing_drops():
    new, note = pg.check_program(PINK, "흥국생명 핑크스파이더스 패배 시청률 7%")
    assert new == "" and "확인 불가" in note


def test_stock_team_replaced_by_listed():
    new, note = pg.check_stock(LIONS, HK)
    assert "삼성 라이온즈 관련 삼성전자 주가가" in new


def test_stock_no_listed_name_drops():
    new, note = pg.check_stock(LIONS, ASIAE)
    assert new == "" and "상장 종목명 없음" in note


def test_stock_listed_kept():
    item = "삼성전자 주가가 일주일 새 14% 하락."
    assert pg.check_stock(item, HK) == (item, None)


def test_new_tense_verbs():
    fut = "11월 10일 국회 토론회를 개최한다. 서명옥 의원 등이 공동 주최한다."
    assert tg.check("이주영 의원 등 의료기관 조사방안 토론회 공동 주최", fut)[0].endswith("공동 주최 예정")
    assert tg.check("의원 공동주최로 토론회 개최…학회 참석", fut)[0].startswith("의원 공동주최로 토론회 개최 예정")
    new, _ = tg.check("의료계 토론회 국회서 열려.", "토론회가 10일 국회에서 열린다.")
    assert new == "의료계 토론회 국회서 열릴 예정."
    item = "특검, 선관위 압수수색 진행."
    assert tg.check(item, "특검이 압수수색을 진행 중이며 결과 발표가 예정돼 있다.") == (item, None)


def test_final_pass_24h_and_undated():
    now = datetime(2026, 11, 9, 18, 0, tzinfo=KST)
    pool = [{"title": "신인감독 김연경2 5회 분당 최고 7% 원더독스 흥국생명 역전승", "link": "https://x/1",
             "description": "예능 프로그램 신인감독 김연경2 5회", "published": "2026-11-09T13:22:53+09:00"},
            {"title": "삼전 개미들 삼성 우승 세일 주가 하락 반응", "link": "https://x/2",
             "published": "2026-11-07T10:00:00+09:00"},
            {"title": "이강인 아틀레티코 바르셀로나 역전패 선제골 패스", "link": "https://x/3"}]
    text = ("▪ 원더독스가 흥국생명에 역전승, 최고 시청률 7% 기록.\n"
            "▪ 삼성 우승 세일 밈 속 삼전 주가 하락에 개미 반응.\n"
            "▪ 이강인이 선제골 패스, 아틀레티코는 바르셀로나에 역전패.")
    import timeliness
    queued, orig = [], timeliness.queue_undated
    timeliness.queue_undated = lambda ex, fam: queued.extend(ex) or len(ex)
    try:
        out, notes = pg.final_pass(text, pool, "ai_evening", now=now)
    finally:
        timeliness.queue_undated = orig
    assert "신인감독 김연경2" in out and "삼전" not in out and "이강인" not in out
    assert any("24h 초과" in n for n in notes) and queued and queued[0]["title"].startswith("[날짜미상]")


def test_prompt_rules_shared_not_duplicated():
    for f in ("political_briefing.py", "ai_briefing.py"):
        s = open(os.path.join(ROOT, f), encoding="utf8").read()
        assert "{pg_rules}" in s and "[주어 검증]" not in s and "[날짜 표현]" not in s
    r = pg.prompt_rules("11/10")
    for k in ("[날짜 표현]", "[주어 검증]", "[시제 검증]", "[방송 프로그램명]", "[주가 종목명]"):
        assert k in r


def test_final_pass_runs_last_before_layout():
    pol = open(os.path.join(ROOT, "political_briefing.py"), encoding="utf8").read()
    # 문체 재작성 뒤, 헤드라인 재생성 앞 — 지운 항목이 제목으로 남지 않게
    assert pol.index("style_fix.fix_style") < pol.index("publish_guard.final_pass") < pol.index("regenerate_headline(briefing, _gc)") < pol.index("briefing = apply_layout(briefing)")
    ai = open(os.path.join(ROOT, "ai_briefing.py"), encoding="utf8").read()
    assert ai.index("gate.enforce(") < ai.index("publish_guard.final_pass") < ai.index("regenerate_headline(briefing, _cl3)") < ai.index("briefing = apply_layout(briefing)")


def test_final_pass_outside_try_of_style_block():
    pol = open(os.path.join(ROOT, "political_briefing.py"), encoding="utf8").read()
    i = pol.index("        import publish_guard")
    line_start = pol.rfind("\n", 0, pol.rfind("try:", 0, i)) + 1
    assert pol[line_start:pol.index("try:", line_start)] == "    "   # 관문 try 는 함수 최상위 들여쓰기


KIM_TITLE = "이성윤 민주당 최고위원, 김민석 대표에 \"신천지 의혹 책임져야\""
KIM_SRC = KIM_TITLE + " 더불어민주당 이성윤 최고위원은 김민석 대표의 신천지 의혹 제기를 '성공한 정치공작'이라고 비판했다."


def test_subject_inversion_dropped():
    new, note = pg.check_subject("김민석 대표, 신천지 관련 의혹 제기…최고위원들 강력 비판 이어짐.", KIM_TITLE, KIM_SRC)
    assert new == "" and "주어 역전" in note


def test_subject_correct_kept():
    item = "이성윤 최고위원, 김민석 대표의 신천지 의혹 제기를 '성공한 정치공작'이라 비판."
    assert pg.check_subject(item, KIM_TITLE, KIM_SRC) == (item, None)


def test_subject_non_accusation_untouched():
    item = "김민석 대표, 경북 비전 선포식에서 민생 강조."
    assert pg.check_subject(item, KIM_TITLE, KIM_SRC) == (item, None)
