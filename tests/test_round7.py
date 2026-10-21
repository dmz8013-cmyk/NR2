"""2026-10-21 13:00판 결함 5종 회귀 테스트.

실행: python -m pytest tests/test_round7.py -v
  결함1 출처 결속(URL·게시시각) · 결함2 24h 누수(인사류) ·
  결함3 직함/입장동사/여론조사 · 결함4 지방 단순일정 · 결함5 헤드라인
"""
import sys
import os
import types
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for m in ('feedparser', 'requests', 'anthropic'):
    try:
        __import__(m)
    except ImportError:
        sys.modules[m] = types.ModuleType(m)

import entity_registry as er
import grounding
import source_bind as sb

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 21, 13, 0, tzinfo=KST)


def _art(title, desc, hours_ago, link="https://news.example/x"):
    return {"title": title, "description": desc, "link": link,
            "pub_date": (NOW - timedelta(hours=hours_ago)).isoformat()}


# ── 결함 1: 출처 결속 ────────────────────────────────────────────────
POOL = [
    _art("국회 법사위, 공소청장 직무대행 출석 요구 의결", "법제사법위원회가 의결했다.", 3, "https://n/1"),
    _art("장동혁 대표 장외집회 예고", "국민의힘이 예고했다.", 5, "https://n/2"),
    _art("박병국 신임 과장 임용", "8월 인사 발령.", 1440, "https://n/3"),
]


def test_unsourced_item_dropped():
    """웹에서 찾을 수 없던 유형 — 풀에 근거가 없으면 제외."""
    out, bound, dropped = sb.bind("🟦 더불어민주당 🟦\n▪ 송영길 TF가 새 조직을 구성했다고 전해짐",
                                  POOL, now=NOW)
    assert "송영길" not in out
    assert any("근거 없음" in d for d in dropped)


def test_sourced_item_keeps_url_and_time():
    """살아남는 항목은 원문 URL·게시시각을 메타로 보존."""
    _, bound, _ = sb.bind("🟦 더불어민주당 🟦\n▪ 국회 법사위가 공소청장 직무대행 출석 요구를 의결함",
                          POOL, now=NOW)
    assert len(bound) == 1
    assert bound[0]["url"] == "https://n/1"
    assert bound[0]["pub"] and bound[0]["age_h"] <= 24


def test_korean_particle_does_not_break_matching():
    """'장외집회를' vs '장외집회' — 조사 때문에 정상 항목이 탈락하면 안 된다."""
    _, bound, dropped = sb.bind("🟥 국민의힘 🟥\n▪ 장동혁 국민의힘 대표가 장외집회를 예고함",
                                POOL, now=NOW)
    assert len(bound) == 1 and not dropped


def test_item_without_url_dropped():
    pool = [{"title": "국회 법사위 공소청장 출석 요구 의결", "description": "의결했다.",
             "pub_date": (NOW - timedelta(hours=2)).isoformat()}]        # link 없음
    out, _, dropped = sb.bind("🟦 더불어민주당 🟦\n▪ 국회 법사위가 공소청장 출석 요구를 의결함",
                              pool, now=NOW)
    assert any("URL 없음" in d for d in dropped) and "법사위" not in out


# ── 결함 2: 24h 누수 (5회째) ────────────────────────────────────────
def test_august_article_dropped_by_binding():
    """8월 기사(박병국 임용)가 근거여도 24h 초과면 제외."""
    out, _, dropped = sb.bind("🇰🇷 이재명 정부 🇰🇷\n▪ 박병국 과장이 임용됨", POOL, now=NOW)
    assert "박병국" not in out
    assert any("경과" in d for d in dropped)


def test_appointment_verbs_now_trigger_stale_event():
    """임용·임명류가 EVENT_VERB_RE 에 없어 사건시점 검사를 못 받던 구멍."""
    import verify_pass as vp
    old = (NOW - timedelta(days=60)).strftime("%Y-%m-%d")
    assert vp.stale_event("박병국 과장이 임용됨", old) is True
    assert vp.stale_event("박병국 과장이 취임함", old) is True


# ── 결함 3: 직함·입장동사·여론조사 ──────────────────────────────────
def test_party_leader_title_fixed():
    out, notes = er.enforce_titles("장동혁 의원이 장외집회를 예고함")
    assert "장동혁 국민의힘 대표가" in out and notes


def test_title_fix_keeps_particle_correct():
    assert "대표가" in er.enforce_titles("장동혁 의원이 발언함")[0]
    assert "대표는" in er.enforce_titles("김민석 의원은 발언함")[0]


def test_correct_title_untouched():
    assert er.enforce_titles("장동혁 대표가 발언함")[1] == []
    assert er.enforce_titles("정청래 전 대표가 발언함")[1] == []


def test_stance_verb_not_in_source_is_neutralized():
    """대통령이 '반박'한 것을 '비판'으로 쓴 유형."""
    src = [_art("대통령, 특검 절차 지적에 반박", "대통령은 적법한 과정이라는 주장에 반박했다.", 2)]
    out, notes = grounding.apply("🇰🇷 이재명 정부 🇰🇷\n▪ 대통령이 적법한 과정이라 비판함", src)
    assert "비판" not in out and any("입장 동사" in n for n in notes)


def test_poll_without_agency_dropped():
    out, notes = er.policy_gate("🟥 국민의힘 🟥\n▪ 정당 지지율이 42%로 나타남")
    assert "42%" not in out and any("여론조사" in n for n in notes)


def test_poll_with_agency_kept():
    out, _ = er.policy_gate("🟥 국민의힘 🟥\n▪ 리얼미터 조사에서 지지율 42% 기록")
    assert "42%" in out


# ── 결함 4: 지방 단순일정 ───────────────────────────────────────────
def test_local_routine_dropped():
    out, notes = er.policy_gate("🟦 더불어민주당 🟦\n▪ 김호진 시의원이 하수도 현장 점검에 나섬")
    assert "김호진" not in out and any("지방 단순일정" in n for n in notes)


def test_local_but_central_issue_kept():
    out, _ = er.policy_gate("🟦 더불어민주당 🟦\n▪ 김호진 시의원이 국정감사 자료 제출을 요구함")
    assert "김호진" in out


# ── 결함 5: 헤드라인 ────────────────────────────────────────────────
def test_headline_stage_verb_downgraded():
    src = [_art("정부, 전기요금 개편 검토 착수", "검토 중이라고 밝혔다.", 2)]
    out, notes = grounding.check_headline("정부 전기요금 개편 추진", src)
    assert "검토" in out and "추진" not in out and notes


def test_headline_bad_ending_trimmed():
    src = [_art("여야 예산 대치 지속", "대치가 이어지고 있다.", 2)]
    out, notes = grounding.check_headline("여야 대치 속 예산 국면 가다", src)
    assert not out.endswith("가다") and notes


def test_headline_untouched_when_grounded():
    src = [_art("정부, 전기요금 개편 검토 착수", "검토 중이라고 밝혔다.", 2)]
    out, notes = grounding.check_headline("정부 전기요금 개편 검토 착수", src)
    assert out == "정부 전기요금 개편 검토 착수" and notes == []


# ── 파이프라인 순서 회귀 ─────────────────────────────────────────────
def test_gates_run_after_generation_steps():
    """source_bind/policy_gate 가 enforce_rebuttal(마지막 생성 단계)보다 뒤에 있어야 한다."""
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "political_briefing.py"), encoding="utf-8").read()
    assert src.index("enforce_rebuttal") < src.index("source_bind.bind")
    assert src.index("enforce_rebuttal") < src.index("_er.policy_gate")
    assert src.index("fill_empty_sections") < src.index("source_bind.bind")
