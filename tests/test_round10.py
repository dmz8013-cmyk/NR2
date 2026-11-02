"""2026-11-02 ㅂㅂㅂ 11/2 오류 기반 A~E 내용검사 테스트.

실행: python -m pytest tests/test_round10.py -v
  A 인용 실존 · B 소스·사건 날짜 · C 직함 사전 · D 증감 방향 · E 따옴표 짝
"""
import sys
import os
import types
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ('feedparser', 'requests', 'anthropic'):
    try:
        __import__(m)
    except ImportError:
        sys.modules[m] = types.ModuleType(m)

import quote_guard as qg
import src_age_guard as sag
import entity_registry as er
import grounding as gr
import gate

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 11, 2, 6, 0, tzinfo=KST)
SRC = ('김민석 더불어민주당 대표는 "조희대 탄핵은 계획대로 차근차근 진행"하겠다고 밝혔다. '
       '민주당은 국정조사도 함께 추진한다는 방침을 재확인했다.')


# ── A. 인용 실존 ───────────────────────────────────────────
def test_a_real_quote_kept():
    body = '김민석 대표 "조희대 탄핵은 계획대로 차근차근 진행"…방침 재확인함'
    out, notes = qg.check(body, SRC)
    assert out == body and notes == []


def test_a_fabricated_quote_stripped():
    body = '홍준표 전 대구시장이 예산안을 "재정 도박"이라고 비판하며 전면 재검토를 요구함'
    out, notes = qg.check(body, SRC)
    assert '"재정 도박"' not in out and "재정 도박" not in out
    assert out and any("원문 없음" in n for n in notes)


def test_a_item_dropped_when_only_quote_remains():
    out, notes = qg.check('장동혁 대표 "선거용 현금인출기"', SRC)
    assert out == "" and any("항목 삭제" in n for n in notes)


def test_a_holds_judgement_when_source_too_short():
    out, notes = qg.check('김민석 대표 "대단히 부정적" 평가함', "제목만 있음")
    assert out != "" and any("판정 보류" in n for n in notes)


LONG_SRC = ('이재명 대통령은 2일 국회에서 여야 대표를 만나 "경쟁이 전쟁되면 안돼. 합리적 경쟁하자"고 '
            '말했다. 이 대통령은 "오히려 국채비율도 우려했던 것과 달리 48%정도 오히려 떨어지고 있기 '
            '때문에, 재정 부채 문제는 걱정할 필요가 크게 없다"고 덧붙였다. 시정연설은 2027년도 예산안 '
            '820조 9000억 원 규모를 설명하는 자리였다. 여야 대표는 각각 입장을 밝혔다.')


def test_a_paraphrase_only_unquoted():
    # 발언은 실재하나 표현이 의역된 경우 — 내용을 지우지 않고 인용부호만 뗀다
    body = '대통령이 여야 대표를 만나 "경쟁이 전쟁되면 안 된다"며 협력을 촉구함'
    out, notes = qg.check(body, LONG_SRC)
    assert "경쟁이 전쟁되면 안 된다" in out and '"경쟁이' not in out
    assert any("인용부호 해제" in n for n in notes)


def test_a_absent_quote_deleted_even_with_long_source():
    body = '오세훈 서울시장이 이재명 정부가 "절대군주가 된다"며 강하게 비판함'
    out, notes = qg.check(body, LONG_SRC)
    assert out == "" and any("원문 없음" in n for n in notes)


def test_a_threshold_tiers():
    assert qg.threshold(LONG_SRC) == qg.MIN_RATIO
    assert qg.threshold("짧은 RSS 요약 한 줄") == qg.LOW_RATIO


def test_a_partial_ratio_fallback_matches_substring():
    assert qg.partial_ratio("계획대로 차근차근 진행", SRC) >= 85
    assert qg.partial_ratio("선거용 현금인출기", SRC) < 85


# ── E. 따옴표 짝 ───────────────────────────────────────────
def test_e_odd_quote_drops_item():
    out, notes = qg.check('국민의힘은 예산을 "선거용 현금인출기', SRC)
    assert out == "" and any("따옴표 홀수" in n for n in notes)


def test_e_even_quotes_pass_parity():
    assert not qg.parity_broken('"가" 그리고 "나"')
    assert qg.parity_broken('"가" 그리고 "나')


# ── B. 소스·사건 날짜 ──────────────────────────────────────
FRESH = {"title": "김준혁 의원 자료 공개", "pub_date_kst": "2026-11-01T22:00:00+09:00"}
STALE = {"title": "포스코 노조 파업 돌입", "pub_date_kst": "2026-10-30T10:00:00+09:00"}
FOLLOWUP = {"title": "[후속] 포스코 파업 파장 확산", "pub_date_kst": "2026-10-30T10:00:00+09:00"}


def test_b_src_over_36h_dropped():
    assert "36h" in (sag.check("포스코 노조가 파업에 돌입함", STALE, NOW) or "")


def test_b_followup_exempt():
    assert sag.check("포스코 파업 후속 영향이 확산됨", FOLLOWUP, NOW) is None


def test_b_old_event_date_dropped():
    r = sag.check("김준혁 의원이 10월 7일 국정감사에서 받은 자료를 공개함", FRESH, NOW)
    assert r and "10/07" in r and "26일" in r


def test_b_recent_event_date_kept():
    assert sag.check("김준혁 의원이 11월 1일 자료를 공개함", FRESH, NOW) is None


def test_b_future_schedule_not_treated_as_stale():
    assert sag.check("정부가 11월 20일 개막 예정인 행사를 준비함", FRESH, NOW) is None


def test_b_future_marker_must_be_near_date():
    # 날짜와 무관한 '추진'이 뒤에 있어도 낡은 날짜는 면제되지 않는다
    r = sag.check("김준혁 의원이 10월 7일 국감 자료를 바탕으로 법 개정을 추진함", FRESH, NOW)
    assert r and "10/07" in r


# ── C. 직함 사전 ───────────────────────────────────────────
def test_c_fact_sheet_titles_merged():
    assert er.load_registry(refresh=True)["직함"].get("박범계") == "더불어민주당 대통합추진단장"


def test_c_typo_title_corrected():
    out, notes = er.enforce_titles("박범계 대통통추진단장이 통합 방안을 발표함")
    assert "대통합추진단장" in out and "대통통" not in out and notes


def test_c_predicate_not_swallowed_as_title():
    # '발표함' 은 '표' 로 끝나지만 직함이 아니다 — 서술어까지 치환하면 안 된다
    out, notes = er.enforce_titles("박범계 대통통추진단장이 발표함")
    assert out == "박범계 더불어민주당 대통합추진단장이 발표함", out
    assert notes


def test_c_near_title_keeps_particle():
    out, _ = er.enforce_titles("강신철 국방부 차관이 회동에 참석함")
    assert out == "강신철 국방부 장관이 회동에 참석함"


def test_c_correct_title_untouched():
    for t in ("강신철 국방부 장관이 회동에 참석함",
              "박범계 더불어민주당 대통합추진단장이 발표함",
              "김민석 대표가 국정조사를 추진함"):
        assert er.enforce_titles(t) == (t, [])


def test_c_former_title_untouched():
    t = "박범계 전 법무부 장관이 발언함"
    assert er.enforce_titles(t) == (t, [])


def test_c_non_title_word_untouched():
    t = "김민석 측근이 발언함"
    assert er.enforce_titles(t) == (t, [])


# ── D. 증감 방향 ───────────────────────────────────────────
YEARS = "2021년 820명, 2022년 950명, 2023년 1,066명, 2024년 870명으로 집계됐다"


def test_d_year_series_parsed():
    assert gr.year_series(YEARS) == [(2021, 820.0), (2022, 950.0), (2023, 1066.0), (2024, 870.0)]


def test_d_wrong_direction_stripped():
    out, notes = gr.check_trend("김준혁 의원이 2023년 1,066명으로 급증했다고 밝힘", YEARS)
    assert "급증" not in out and "1,066명" in out and "했다고" not in out
    assert any("재판정" in n for n in notes)


def test_d_fragment_without_predicate_dropped():
    # 증감 표현을 떼면 술어가 없어지는 항목은 조각으로 남기지 않고 지운다
    out, notes = gr.check_trend("김준혁 의원 자료에 따르면 2023년 1,066명으로 급증", YEARS)
    assert out == "" and any("항목 삭제" in n for n in notes)


def test_d_intensifier_demoted_without_comparison():
    out, notes = gr.check_trend("2023년 1,066명으로 급증함", "")
    assert "증가" in out and "급증" not in out and notes


def test_d_two_numbers_keep_intensifier():
    out, notes = gr.check_trend("지난해 820명에서 올해 1,066명으로 급증함", "")
    assert "급증" in out and notes == []


def test_d_year_is_not_a_comparison_number():
    assert len(gr._compare_numbers("2023년 1,066명")) == 1


def test_d_matching_direction_kept():
    out, notes = gr.check_trend("2024년 870명으로 감소함", YEARS)
    assert "감소" in out and notes == []


def test_d_wired_into_check_direction():
    out, notes = gr.check_direction("2023년 1,066명으로 급증함", YEARS)
    assert "급증" not in out and any(n.startswith("D ") for n in notes)


# ── 게이트 통합: A~E 건수 ──────────────────────────────────
def test_gate_counts_a_to_e():
    items = ['▪ 홍준표 전 대구시장이 예산안을 "재정 도박"이라고 비판하며 재검토를 요구함',
             '▪ 국민의힘은 예산을 "선거용 현금인출기',
             '▪ 김준혁 의원이 10월 7일 국정감사에서 받은 자료를 공개함',
             '▪ 박범계 대통통추진단장이 2023년 1,066명으로 급증했다고 밝힘']
    briefing = "🏛️ 정치/시사\n" + "\n".join(items)
    pool = [{"title": "홍준표 전 대구시장 예산안 전면 재검토 요구", "description": SRC,
             "link": "http://a/1", "pub_date_kst": "2026-11-02T04:00:00+09:00"},
            {"title": "국민의힘 예산 공방", "description": SRC, "link": "http://a/2",
             "pub_date_kst": "2026-11-02T04:00:00+09:00"},
            {"title": "김준혁 의원 자료 공개", "description": "국정감사 자료를 공개했다. " + YEARS,
             "link": "http://a/3", "pub_date_kst": "2026-11-02T04:00:00+09:00"},
            {"title": "박범계 통합 방안", "description": "통합 방안을 발표했다. " + YEARS,
             "link": "http://a/4", "pub_date_kst": "2026-11-02T04:00:00+09:00"}]
    out, info = gate.enforce(briefing, pool, "ai_아침")
    c = info["check_counts"]
    assert c["A"] >= 1 and c["B"] == 1 and c["C"] == 1 and c["D"] == 1 and c["E"] == 1, c
    assert "재정 도박" not in out          # A 날조 인용 제거
    assert "선거용 현금인출기" not in out   # E 홀수 따옴표 항목 삭제
    assert "10월 7일" not in out           # B 낡은 사건 날짜 항목 삭제
    assert "대통합추진단장" in out          # C 직함 교정
    assert "급증" not in out               # D 방향 재판정


def test_gate_labels_cover_all_checks():
    assert sorted(gate.CHECK_LABELS) == ["A", "B", "C", "D", "E"]
