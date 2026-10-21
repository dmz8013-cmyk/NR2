"""2026-10-19 13:00판 결함 5종 회귀 테스트.

실행: python -m pytest tests/test_round6.py -v
  결함1 주체 기준 섹션 귀속 · 결함2 동사 과장 · 결함3 원문 밖 수치 ·
  결함4 외신 고유명사 프롬프트 규칙 · 결함5 24h 하드 필터
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

import entity_registry as er
import grounding
import timeliness as tl

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 19, 13, 0, tzinfo=KST)


# ── 결함 1: 섹션은 '기사에 나온 정당'이 아니라 '주체의 소속' ──────────────
def test_prosecutor_goes_to_legal_not_party():
    """공소청장(검찰) → 민주당 오분류 재발 방지."""
    sec, _ = er.section_for_item("공소청장 직무대행 이정현이 수사 지휘 방침을 밝힘")
    assert sec == "법조"


def test_registered_mp_party_is_fixed():
    """박지원(민주당 의원) → 비교섭 오분류 재발 방지."""
    assert er.mp_party("박지원") == "더불어민주당"
    sec, _ = er.section_for_item("박지원 의원이 정부 예산안 처리를 비판")
    assert sec == "더불어민주당"


def test_subject_wins_over_mentioned_party():
    """한강버스 의혹 제기(민주당 김남근) → 국민의힘 오분류 재발 방지."""
    sec, _ = er.section_for_item(
        "김남근 의원이 한강버스 적자 의혹을 제기하며 오세훈 서울시장과 국민의힘을 겨냥")
    assert sec == "더불어민주당"


def test_gamsa_classified_by_questioning_mp():
    sec, why = er.section_for_item("국정감사에서 김용민 의원이 대검에 자료 제출을 요구")
    assert sec == "더불어민주당" and "국감" in why


def test_gamsa_agency_answer_goes_to_legal():
    sec, _ = er.section_for_item("국감에서 공소청장이 수사 경위를 답변")
    assert sec == "법조"


def test_unknown_subject_keeps_original():
    assert er.section_for_item("정부가 내년 예산 기조를 설명")[0] != "더불어민주당"


# ── 결함 2: 동사 과장 ────────────────────────────────────────────────
SRC_AUDIT = [{"title": "감사원, 공공기관 확정손실 1조2000억원 집계",
              "description": "감사원이 공공기관 확정손실을 1조2000억원으로 집계했다고 밝혔다. 심사 절차 지적도 나왔다."}]


def test_overstated_verb_replaced_with_source_verb():
    out, notes = grounding.apply(
        "🇰🇷 이재명 정부 🇰🇷\n▪ 감사원이 공공기관 확정손실 1조2000억원을 적발", SRC_AUDIT)
    assert "적발" not in out and "집계" in out
    assert any("적발" in n for n in notes)


def test_fabricated_frame_modifier_removed():
    out, _ = grounding.apply(
        "🇰🇷 이재명 정부 🇰🇷\n▪ 감사원이 확정손실 1조2000억원을 집계, 졸속 심사 의혹도 제기됨", SRC_AUDIT)
    assert "졸속" not in out


def test_verb_kept_when_present_in_source():
    src = [{"title": "경찰, 불법 도박장 적발", "description": "경찰이 불법 도박장을 적발했다."}]
    out, _ = grounding.apply("🟦 더불어민주당 🟦\n▪ 경찰이 불법 도박장을 적발", src)
    assert "적발" in out


# ── 결함 3: 원문에 없는 수치 ──────────────────────────────────────────
SRC_SHIP = [{"title": "조선업체 건조대금 분쟁…선수금 반환 소송",
             "description": "건조대금 지급을 둘러싼 분쟁이 이어지고 있다. 업체는 선수금 반환을 요구했다."}]


def test_number_absent_from_source_is_removed():
    out, notes = grounding.apply(
        "🌐 법조 및 국제 🌐\n▪ 조선업체가 건조대금 10% 미지급을 이유로 선수금 반환 소송을 제기함", SRC_SHIP)
    assert "10%" not in out
    assert any("10%" in n for n in notes)


def test_number_present_in_source_is_kept():
    out, _ = grounding.apply(
        "🇰🇷 이재명 정부 🇰🇷\n▪ 감사원이 확정손실 1조2000억원을 집계", SRC_AUDIT)
    assert "1조2000억원" in out


def test_unmatched_item_is_left_alone():
    """매칭 원문이 없으면 건드리지 않는다(출처 매칭 가드가 따로 처리)."""
    out, notes = grounding.apply("🟥 국민의힘 🟥\n▪ 전혀 다른 주제의 항목 임의 서술 999건", SRC_SHIP)
    assert "999건" in out and notes == []


# ── 결함 4: 외신 고유명사 ────────────────────────────────────────────
def test_foreign_title_rule_in_prompt():
    import political_briefing as pb
    src = open(pb.__file__, encoding="utf-8").read()
    assert "외신 고유명사" in src and "가지야마" in src


def test_foreign_names_registered():
    assert er.foreign_names().get("가지야마 히로시") == "자민당 총무회장"


# ── 결함 5: 24h 하드 필터 ────────────────────────────────────────────
def test_previous_day_morning_is_over_24h():
    """10/18 09:38 기사가 10/19 13:00판에 섞이던 누수."""
    assert tl.within_max_age("2026-10-18T09:38:00+09:00", NOW) is False
    assert round(tl.age_hours("2026-10-18T09:38:00+09:00", NOW), 1) == 27.4


def test_previous_day_evening_passes():
    assert tl.within_max_age("2026-10-18T22:30:00+09:00", NOW) is True


def test_missing_time_is_excluded():
    assert tl.within_max_age(None, NOW) is False


def test_allowed_dates_alone_would_have_let_it_through():
    """날짜 기준만으로는 통과하던 것을 시간 기준이 막는다는 회귀 증명."""
    d = datetime(2026, 10, 18, 9, 38, tzinfo=KST)
    assert d.date() in tl.allowed_dates(NOW)          # 날짜 기준: 통과
    assert tl.within_max_age(d, NOW) is False          # 시간 기준: 차단


def test_recheck_queue_applies_hard_filter():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "recheck_queue.py"), encoding="utf-8").read()
    assert "within_max_age" in src


def test_stale_event_uses_hours_when_timestamped():
    """시각이 있으면 24h 기준, 날짜만이면 {오늘,전일} 기준.

    allowed_dates()가 실행 시점을 쓰므로 날짜를 하드코딩하면 다음 날 깨진다 —
    '지금'에서 역산한다(2026-10-21 수정).
    """
    import verify_pass as vp
    from datetime import timedelta
    now = datetime.now(KST)
    over_24h = (now - timedelta(hours=27)).isoformat()       # 전일이지만 24h 초과
    within_24h = (now - timedelta(hours=14)).isoformat()     # 전일이고 24h 이내
    yesterday_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    assert vp.stale_event("신제품을 공개했음", over_24h) is True
    assert vp.stale_event("신제품을 공개했음", within_24h) is False
    assert vp.stale_event("신제품을 공개했음", yesterday_date) is False   # 날짜만 → 날짜 의미 유지
