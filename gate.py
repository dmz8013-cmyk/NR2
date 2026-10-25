"""gate.py — 발행 직전 최종 관문 (2026-10-25).

브리핑 4종(아침·저녁·정치 13시·22시)이 **같은 게이트 하나**를 통과하도록 묶는다.

  정책 게이트(직함·지방 단순일정·여론조사 기관) → 원문 대조(과장·논평·수치)
  → 출처 결속(원문 URL·게시시각 보존, 근거 없음·24h 초과 제외) → DB 기록

설계 원칙
  · **fail-closed**: 앞 단계가 터져도 결속은 반드시 돈다. 호출부는 이 함수를
    생성 단계(enforce_breaking / fill_empty_sections / enforce_rebuttal)보다
    **뒤에서**, 그리고 그 단계들의 try 블록 **밖에서** 불러야 한다.
    (2026-10-21~25: 생성 단계 예외가 게이트 전체를 건너뛰게 만들던 구조 버그)
  · **감사 추적**: 항목별 결속 결과를 source_bind_log 에 남긴다. 로그 보존이
    짧아 사후 추적이 불가능하던 문제(10/25 13:00판) 해소.
  · 어떤 실패도 발행을 막지 않는다. 단 결속이 전멸하면 관리자 경보.
"""
import logging

logger = logging.getLogger("gate")

DDL = """CREATE TABLE IF NOT EXISTS source_bind_log (
    id SERIAL PRIMARY KEY,
    run_at        TIMESTAMP DEFAULT NOW(),
    briefing_type VARCHAR(32),
    status        VARCHAR(12),
    body          TEXT,
    url           TEXT,
    source        VARCHAR(120),
    pub_label     VARCHAR(20),
    age_h         REAL,
    overlap       INT,
    reason        TEXT
)"""


def _persist(briefing_type: str, bound: list[dict], dropped: list[str]) -> bool:
    """항목별 결속 결과 적재. 실패는 로그만 — 발행에 영향 없음."""
    try:
        from g2b_tracker import db_conn
        conn = db_conn()
        if not conn:
            return False
        cur = conn.cursor()
        cur.execute(DDL)
        for b in bound:
            cur.execute("""INSERT INTO source_bind_log
                (briefing_type, status, body, url, source, pub_label, age_h, overlap)
                VALUES (%s,'bound',%s,%s,%s,%s,%s,%s)""",
                        (briefing_type, b.get("body"), b.get("url"), (b.get("source") or "")[:120],
                         b.get("pub"), b.get("age_h"), b.get("overlap")))
        for d in dropped:
            reason, _, body = d.partition(": ")
            cur.execute("""INSERT INTO source_bind_log
                (briefing_type, status, body, reason) VALUES (%s,'dropped',%s,%s)""",
                        (briefing_type, body or d, reason))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"[게이트] 결속 기록 적재 실패(무시): {e}")
        return False


def _alert(briefing_type: str, msg: str) -> None:
    try:
        from ai_briefing import _alert_zero_collection
        _alert_zero_collection(briefing_type, msg)
    except Exception as e:
        logger.warning(f"[게이트] 경보 실패(무시): {e}")


def _count_items(text: str) -> int:
    return sum(1 for ln in text.split("\n")
               if ln.strip().startswith("▪") and "금일 주요 보도 없음" not in ln)


def enforce(briefing: str, pool: list[dict], briefing_type: str,
            report=None) -> tuple[str, dict]:
    """→ (텍스트, {policy_notes, grounding_notes, bound_items, unbound_dropped}).

    report 를 주면 같은 필드를 report 에도 채운다(회차 DM 용).
    """
    info = {"policy_notes": [], "grounding_notes": [], "bound_items": [], "unbound_dropped": []}
    before = _count_items(briefing)

    try:
        import entity_registry as _er
        briefing, info["policy_notes"] = _er.policy_gate(briefing)
        # 아침/저녁은 섹션 체계가 달라(🏛️ 정치/시사·💰 경제/산업·🤖 AI/기술·🎯 기타)
        # 정치인 정책 공방이 주제 섹션에 섞인다 → 정치/시사로 이동 (2026-10-25)
        if (briefing_type or "").startswith("ai_"):
            briefing, _gs = _er.enforce_general_sections(briefing)
            info["policy_notes"] += _gs
    except Exception as e:
        logger.warning(f"[게이트] 정책 단계 실패(계속): {e}")

    try:
        import grounding
        briefing, info["grounding_notes"] = grounding.apply(briefing, pool)
    except Exception as e:
        logger.warning(f"[게이트] 원문 대조 실패(계속): {e}")

    try:
        import source_bind
        briefing, info["bound_items"], info["unbound_dropped"] = source_bind.bind(briefing, pool)
    except Exception as e:
        logger.error(f"[게이트] 출처 결속 실패 — 미결속 상태로 발행: {e}")
        _alert(briefing_type, f"출처 결속 단계 예외 — 24h·근거 검증 없이 발행됨: {str(e)[:120]}")

    _persist(briefing_type, info["bound_items"], info["unbound_dropped"])

    after = _count_items(briefing)
    # 아침/저녁 풀은 기사 본문(description)이 없어 제목만으로 매칭된다 — 정치 브리핑보다
    # 겹침이 얇아 과다 제외 위험이 있다. 전멸·대량 제외는 즉시 알린다 (2026-10-25).
    if before and not info["bound_items"]:
        _alert(briefing_type, f"출처 결속 0건 (게이트 전 {before}항목) — 근거 확인 불가")
    elif before and after / before < 0.4:
        _alert(briefing_type,
               f"출처 결속 대량 제외 — {before}항목 중 {before - after}건 탈락 "
               f"(잔여 {after}). 매칭 임계값 점검 필요")
    logger.info(f"[게이트] {briefing_type}: 항목 {before}→{after} · 결속 {len(info['bound_items'])} "
                f"· 제외 {len(info['unbound_dropped'])} · 정책 {len(info['policy_notes'])} "
                f"· 원문대조 {len(info['grounding_notes'])}")

    if report is not None:
        report.policy_notes = info["policy_notes"]
        report.grounding_notes = list(getattr(report, "grounding_notes", [])) + info["grounding_notes"]
        report.bound_items = info["bound_items"]
        report.unbound_dropped = info["unbound_dropped"]
    return briefing, info
