"""2026-10-25 18:00 저녁판 결함 + [1-A]·[1-F] 구조 변경 회귀 테스트.

실행: python -m pytest tests/test_round8.py -v
"""
import sys
import os
import types
import inspect
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
import gate

KST = ZoneInfo("Asia/Seoul")
NOW = datetime(2026, 10, 25, 18, 0, tzinfo=KST)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(name):
    return open(os.path.join(ROOT, name), encoding="utf-8").read()


# ── [1-A] 게이트 fail-closed ────────────────────────────────────
def test_generation_steps_each_have_own_try():
    """생성 단계 하나가 터져도 게이트까지 건너뛰면 안 된다."""
    s = _src("political_briefing.py")
    assert "[섹션가드:{label}] 실패 — 건너뛰고 계속" in s


def test_gate_called_outside_generation_try():
    """gate.enforce 는 생성 단계 try 블록 밖에서 호출돼야 한다."""
    s = _src("political_briefing.py")
    block = s[s.index("# ── 생성 단계"):s.index("# ── 정리·서식")]
    gate_line = [l for l in block.split("\n") if "gate.enforce" in l][0]
    assert gate_line.startswith("        briefing, _ginfo")      # 8칸 = 최상위 try 안
    assert "최종 관문 — try 밖" in block


def test_gate_alerts_when_nothing_bound():
    assert "출처 결속 0건" in _src("gate.py")


# ── [1-F] 결속 결과 DB 저장 ─────────────────────────────────────
def test_bind_results_persisted():
    s = _src("gate.py")
    assert "CREATE TABLE IF NOT EXISTS source_bind_log" in s
    assert "'bound'" in s and "'dropped'" in s


def test_persist_failure_does_not_raise():
    """DB 불가 환경에서도 예외가 밖으로 나가면 안 된다."""
    assert gate._persist("ai_evening", [{"body": "x", "url": "u"}], ["사유: y"]) in (True, False)


# ── [1] 아침/저녁도 24h 결속 게이트를 탄다 ───────────────────────
def test_ai_briefing_calls_gate():
    s = _src("ai_briefing.py")
    assert "gate.enforce" in s
    assert s.index("run_verify_pass_ex") < s.index("gate.enforce") < s.index("apply_layout")


def test_over_24h_item_dropped_for_general_briefing():
    """10/24 10:21 포스코 파업이 10/25 18:00판에 들어가던 유형."""
    pool = [{"title": "포스코 노조 파업 돌입 철강 생산 차질", "link": "https://n/1",
             "published": (NOW - timedelta(hours=32)).isoformat()}]
    out, bound, dropped = sb.bind("💰 경제/산업\n▪ 포스코 노조가 파업에 돌입해 철강 생산 차질 발생",
                                  pool, now=NOW)
    assert "포스코" not in out and any("경과" in d for d in dropped) and not bound


def test_within_24h_item_kept_for_general_briefing():
    pool = [{"title": "중국 희토류 수출 통제 발표", "link": "https://n/2",
             "published": (NOW - timedelta(hours=5)).isoformat()}]
    out, bound, _ = sb.bind("💰 경제/산업\n▪ 중국이 희토류 수출 통제를 발표", pool, now=NOW)
    assert "희토류" in out and bound[0]["url"] == "https://n/2"


# ── [2] 정치인 정책 공방은 정치/시사로 ──────────────────────────
def test_politician_dispute_moved_to_politics():
    b = ("🏛️ 정치/시사\n▪ 국회가 예산안 심사를 시작함\n\n"
         "💰 경제/산업\n▪ 추미애 경기도지사와 이준석 개혁신당 대표가 소방 재정을 두고 공방")
    out, notes = er.enforce_general_sections(b)
    pol = out[out.index("🏛️"):out.index("💰")]
    assert "추미애" in pol and notes


def test_non_dispute_item_stays_in_topic_section():
    b = "💰 경제/산업\n▪ 이재명 대통령이 반도체 투자 계획을 발표"
    out, notes = er.enforce_general_sections(b)
    assert notes == [] and "반도체" in out


def test_minister_not_treated_as_party_politician():
    assert er.is_politician("추미애") is True          # 경기도지사
    assert er.is_politician("이준석") is True          # 개혁신당 대표
    assert er.is_politician("정동영") is False         # 통일부 장관
    assert er.is_politician("조희대") is False         # 대법원장


def test_general_sections_only_for_ai_types():
    assert 'startswith("ai_")' in _src("gate.py")


# ── [3] 논평형 서술 ─────────────────────────────────────────────
SRC_POSCO = [{"title": "포스코 노조 파업 돌입", "description": "포스코 노조가 파업에 돌입했다."}]


def test_commentary_clause_removed_fact_kept():
    out, notes = grounding.apply(
        "💰 경제/산업\n▪ 포스코 노조가 파업에 돌입, 철강 업계의 구조적 약세가 드러나고 있음", SRC_POSCO)
    assert "구조적" not in out and "파업에 돌입" in out
    assert any("논평형" in n for n in notes)


def test_speculation_clause_removed():
    src = [{"title": "중국 희토류 수출 통제", "description": "중국이 희토류 수출 통제를 발표했다."}]
    out, _ = grounding.apply("💰 경제/산업\n▪ 중국이 희토류 수출 통제를 발표, 무기화 가능성이 제기되고 있음", src)
    assert "가능성이 제기" not in out and "희토류" in out


def test_commentary_kept_when_in_source():
    src = [{"title": "조선 수주 본격화", "description": "업계는 수주가 본격화되고 있다고 밝혔다."}]
    out, notes = grounding.apply("💰 경제/산업\n▪ 조선 수주가 본격화되고 있음", src)
    assert "본격화" in out and not any("논평형" in n for n in notes)


def test_clause_threshold_keeps_short_korean_fact():
    """'포스코 노조가 파업에 돌입'(14자)이 임계값 1자 차이로 날아가면 안 된다."""
    assert grounding._strip_clause("포스코 노조가 파업에 돌입, 구조적 약세가 드러남", "구조적 약세")
