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


CHECK_LABELS = {"A": "인용 실존", "B": "소스·사건 날짜", "C": "직함 사전",
                "D": "증감 방향", "E": "따옴표 짝", "F": "빈 출처 잔여물",
                "G": "헤드라인 정합"}
# F 는 게이트 입구에서, G 는 게이트 뒤 헤드라인 단계에서 센다 — 게이트가 집계하는
# 범위는 A~F 다. G 는 호출부(political_briefing)가 report.check_counts 에 더한다.
GATE_CHECKS = ("A", "B", "C", "D", "E", "F")


def _opt(name: str):
    """가드 모듈 선택적 로드 — 없거나 깨져도 발행은 진행한다."""
    try:
        return __import__(name)
    except Exception as e:
        logger.warning(f"[내용검사] {name} 로드 실패(건너뜀): {e}")
        return None


def _content_checks(briefing: str, pool: list[dict], bound: list[dict]
                    ) -> tuple[str, list[str], dict]:
    """결속된 항목을 원문과 1:1 로 대조한다. → (텍스트, 메모, A~E 건수).

    2026-10-30: 시제 승격·수치 방향·여론조사 4종·회의체 조합
    2026-11-02: A 인용 실존 · B 소스·사건 날짜 · D 증감 방향 · E 따옴표 짝
                (C 직함 사전은 정책게이트에서 돌고 건수만 여기서 합산)
    """
    import grounding as gr
    tense_guard = _opt("tense_guard")
    quote_guard = _opt("quote_guard")
    src_age_guard = _opt("src_age_guard")
    counts = {k: 0 for k in ("A", "B", "C", "D", "E")}
    by_body = {b["body"]: b for b in bound}
    lines = briefing.split("\n")
    notes: list[str] = []
    for i, ln in enumerate(lines):
        s = (ln or "").strip()
        if not s.startswith("▪"):
            continue
        body = s.lstrip("▪").strip()
        b = by_body.get(body)
        if not b:
            continue
        art = next((a for a in pool if (a.get("link") or a.get("url")) == b.get("url")), None)
        src = f"{art.get('title','')} {art.get('description') or ''}" if art else ""

        # E(따옴표 짝) → A(인용 실존). 잘린 문장은 인용 대조가 무의미하므로 E 가 먼저다.
        if quote_guard is not None:
            new, qnotes = quote_guard.check(body, src)
            for n in qnotes:
                notes.append(n)
                if "따옴표 홀수" in n:
                    counts["E"] += 1
                elif n.startswith("A ") and "판정 보류" not in n:
                    counts["A"] += 1          # 인용 삭제·인용부호 해제 모두 A 발동
            if new == "":
                lines[i] = None
                continue
            body = new

        # B — 결속 기사 36h 초과 · 항목이 말하는 사건이 7일 초과
        if src_age_guard is not None and art is not None:
            reason = src_age_guard.check(body, art)
            if reason:
                notes.append(f"{reason} — 삭제: {body[:36]}")
                counts["B"] += 1
                lines[i] = None
                continue

        if tense_guard is not None:
            new, note = tense_guard.check(body, src)
            if note:
                notes.append(f"시제: {note}")
                if new == "":
                    lines[i] = None
                    continue
                body = new

        new, dnotes = gr.check_direction(body, src)
        notes += [f"수치방향: {n}" for n in dnotes]
        counts["D"] += sum(1 for n in dnotes if n.startswith("D "))
        if new == "":
            lines[i] = None
            continue
        body = new

        new, pnote = gr.augment_poll(body, src)
        if pnote:
            notes.append(f"{pnote} ({body[:30]}…)")
            if new == "":
                lines[i] = None
                continue
            body = new

        bad = gr.check_forum(body, src)
        if bad:
            notes.append(f"회의체 불일치 {'·'.join(bad)} — 삭제: {body[:36]}")
            lines[i] = None
            continue

        lines[i] = "▪ " + body
    if notes:
        logger.warning(f"[내용검사] {len(notes)}건: {notes[:4]}")
    return "\n".join(l for l in lines if l is not None), notes, counts


def enforce(briefing: str, pool: list[dict], briefing_type: str,
            report=None) -> tuple[str, dict]:
    """→ (텍스트, {policy_notes, grounding_notes, bound_items, unbound_dropped}).

    report 를 주면 같은 필드를 report 에도 채운다(회차 DM 용).
    """
    info = {"policy_notes": [], "grounding_notes": [], "bound_items": [], "unbound_dropped": [],
            "content_notes": [], "check_counts": {k: 0 for k in GATE_CHECKS}}
    before = _count_items(briefing)

    # F — 빈 출처 표기 잔여물. 다른 검사보다 **먼저** 떼야 한다: 항목 끝의 `{}` 가
    #     남아 있으면 결속 본문·토큰·따옴표 짝 판정까지 전부 오염된다 (2026-11-03).
    _srg = _opt("src_render_guard")
    if _srg is not None:
        briefing, _nempty, _nitems = _srg.clean(briefing)
        info["check_counts"]["F"] = _nempty
        info["src_empty"] = _nempty
        if _nempty:
            info["content_notes"].append(f"F 빈 출처 표기 제거 {_nempty}/{_nitems}항목")
        if _srg.over_rate(_nempty, _nitems):
            _alert(briefing_type,
                   f"빈 출처 표기 {_nempty}/{_nitems}항목 — 출처 결속·태그 경로 점검 필요")

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

    # 시제·방향·여론조사·회의체 — 결속 기사와 1:1 로 대조해야 하므로 bind 결과를 쓴다
    try:
        import source_bind
        briefing, info["bound_items"], info["unbound_dropped"] = source_bind.bind(briefing, pool)
        # F 는 게이트 입구에서 이미 세어 넣었다 — 덮어쓰지 말고 합친다.
        briefing, _cnotes, _ccounts = _content_checks(briefing, pool, info["bound_items"])
        info["content_notes"] += _cnotes
        info["check_counts"].update(_ccounts)
        try:
            import briefing_dedup
            briefing, _dn = briefing_dedup.dedup(briefing, info["bound_items"])
            info["content_notes"] += [f"병합: {n}" for n in _dn]
        except Exception as de:
            logger.warning(f"[병합] 실패(계속): {de}")
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
    info["check_counts"]["C"] = sum(1 for n in info["policy_notes"] if "직함 교정" in n)
    logger.warning("[내용검사] " + " · ".join(
        f"{k}({CHECK_LABELS[k]})={info['check_counts'][k]}" for k in GATE_CHECKS)
        + f" · src_empty: {info.get('src_empty', 0)}")
    logger.info(f"[게이트] {briefing_type}: 항목 {before}→{after} · 결속 {len(info['bound_items'])} "
                f"· 제외 {len(info['unbound_dropped'])} · 정책 {len(info['policy_notes'])} "
                f"· 원문대조 {len(info['grounding_notes'])}")

    if report is not None:
        report.policy_notes = info["policy_notes"]
        report.grounding_notes = list(getattr(report, "grounding_notes", [])) + info["grounding_notes"]
        report.bound_items = info["bound_items"]
        report.unbound_dropped = info["unbound_dropped"]
        report.content_notes = info["content_notes"]
        report.check_counts = info["check_counts"]
    return briefing, info
