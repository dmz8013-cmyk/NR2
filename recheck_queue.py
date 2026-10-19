"""recheck_queue.py — 미확인 실명 발언 재검색 큐 (Postgres recheck_queue).

verify_pass 에서 '확인불가' 로 빠진 실명 발언 항목은 삭제 대신 여기 적재된다.
같은 family(general|politics) 의 다음 회차 생성 전에 재검색 → 일치(+시의성 통과)하면
해당 섹션에 자동 복귀, 2회 시도 후에도 미확인이면 폐기 + DM.
텔레 명령: /recheck_add <family> <section> <항목문장> · /recheck_list · /recheck_drop <id>
"""
import os
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("recheck_queue")
KST = ZoneInfo("Asia/Seoul")
FAMILIES = ("general", "politics")
MAX_ATTEMPTS = 2

DDL = """CREATE TABLE IF NOT EXISTS recheck_queue (
    id SERIAL PRIMARY KEY,
    family VARCHAR(16) NOT NULL,
    section VARCHAR(40),
    item_text TEXT NOT NULL,
    entities TEXT,
    first_run VARCHAR(40),
    attempts INT DEFAULT 0,
    status VARCHAR(16) DEFAULT 'pending',
    last_result TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
)"""


def family_of(briefing_type: str) -> str:
    return "politics" if (briefing_type or "").startswith("political") else "general"


def _conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2
        return psycopg2.connect(url)
    except Exception as e:
        logger.warning(f"[재검색큐] DB 연결 실패: {e}")
        return None


def ensure_table() -> bool:
    conn = _conn()
    if not conn:
        return False
    try:
        cur = conn.cursor(); cur.execute(DDL); conn.commit(); conn.close()
        return True
    except Exception as e:
        logger.warning(f"[재검색큐] 테이블 생성 실패: {e}")
        return False


def enqueue(family: str, section: str, item_text: str, entities=None, first_run: str = "") -> int | None:
    if family not in FAMILIES:
        family = family_of(family)
    conn = _conn()
    if not conn:
        return None
    try:
        cur = conn.cursor(); cur.execute(DDL)
        ent = json.dumps(entities, ensure_ascii=False) if isinstance(entities, (list, dict)) else (entities or "")
        cur.execute("""INSERT INTO recheck_queue (family, section, item_text, entities, first_run)
                       VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                    (family, (section or "")[:40], item_text.strip(), ent, first_run or datetime.now(KST).strftime("%Y-%m-%d %H:%M")))
        rid = cur.fetchone()[0]; conn.commit(); conn.close()
        logger.info(f"[재검색큐] 적재 #{rid} [{family}/{section}] {item_text[:40]}")
        return rid
    except Exception as e:
        logger.warning(f"[재검색큐] 적재 실패: {e}")
        return None


def list_items(family: str | None = None, status: str | None = "pending") -> list[dict]:
    conn = _conn()
    if not conn:
        return []
    try:
        cur = conn.cursor(); cur.execute(DDL)
        sql = "SELECT id, family, section, item_text, entities, first_run, attempts, status, last_result FROM recheck_queue WHERE 1=1"
        args = []
        if family:
            sql += " AND family=%s"; args.append(family)
        if status:
            sql += " AND status=%s"; args.append(status)
        sql += " ORDER BY id"
        cur.execute(sql, args)
        rows = [dict(zip(("id", "family", "section", "item_text", "entities", "first_run", "attempts", "status", "last_result"), r))
                for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        logger.warning(f"[재검색큐] 조회 실패: {e}")
        return []


def drop(item_id: int) -> bool:
    conn = _conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("UPDATE recheck_queue SET status='dropped', updated_at=NOW() WHERE id=%s AND status='pending'", (item_id,))
        ok = cur.rowcount > 0; conn.commit(); conn.close()
        return ok
    except Exception as e:
        logger.warning(f"[재검색큐] 삭제 실패: {e}")
        return False


def _mark(item_id: int, status: str, attempts: int, last_result: str) -> None:
    conn = _conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("UPDATE recheck_queue SET status=%s, attempts=%s, last_result=%s, updated_at=NOW() WHERE id=%s",
                    (status, attempts, (last_result or "")[:500], item_id))
        conn.commit(); conn.close()
    except Exception as e:
        logger.warning(f"[재검색큐] 상태 갱신 실패: {e}")


def process_queue(family: str, verify_fn, now: datetime | None = None,
                  dry_run: bool = False) -> tuple[list[tuple[str, str]], list[str], list[dict]]:
    """pending 항목 재검색. → (복귀 [(section, text)], 폐기 [text], 결과 상세).

    verify_fn(text) -> {verdict, corrected, newest_pub_date, searches}. 일치 + 발행일이 {오늘, 전일}
    + 발행 24h 이내여야 복귀. MAX_ATTEMPTS 회 후에도 미확인이면 폐기.
    (2026-10-19: 날짜만 보던 탓에 전일 오전 기사가 복귀하던 24h 누수 차단)"""
    from timeliness import allowed_dates, to_kst, within_max_age
    restored, discarded, details = [], [], []
    for it in list_items(family=family, status="pending"):
        attempts = (it.get("attempts") or 0) + 1
        try:
            res = verify_fn(it["item_text"]) or {}
        except Exception as e:
            res = {"verdict": "오류", "error": str(e)}
        verdict = res.get("verdict", "오류")
        newest = to_kst(res.get("newest_pub_date"))
        # 24h 하드 필터: 날짜({오늘,전일})만으로는 '전일 09:38'(27h)이 통과한다.
        timely = bool(newest) and newest.date() in allowed_dates(now) and within_max_age(newest, now)
        detail = {"id": it["id"], "text": it["item_text"], "verdict": verdict, "timely": timely, "attempts": attempts,
                  "searches": res.get("searches", 0)}
        details.append(detail)
        if verdict == "일치" and timely:
            text = (res.get("corrected") or "").strip() or it["item_text"]
            restored.append((it.get("section") or "", text))
            status, note = "restored", f"일치·발행 {newest:%m/%d}"
        elif verdict == "일치" and not timely:
            status, note = ("discarded" if attempts >= MAX_ATTEMPTS else "pending"), "일치하나 시의성 미달"
        elif verdict == "불일치":
            status, note = "discarded", f"불일치: {(res.get('corrected') or '')[:120]}"
        else:
            status, note = ("discarded" if attempts >= MAX_ATTEMPTS else "pending"), verdict
        if status == "discarded":
            discarded.append(it["item_text"])
        detail["status"] = status
        if not dry_run:
            _mark(it["id"], status, attempts, note)
    return restored, discarded, details


def insert_into_section(briefing: str, section: str, text: str) -> str:
    """섹션 헤더(이모지 줄) 아래 마지막 ▪ 뒤에 항목 삽입. 섹션 못 찾으면 첫 ▪ 그룹 끝에."""
    try:
        from briefing_layout import SECTION_HEADER_RE
    except Exception:
        import re
        SECTION_HEADER_RE = re.compile(r'^(🏛️|💰|🤖|🎯|📌|🇰🇷|🟦|🟥|🎸|🌐)')
    lines = briefing.split("\n")
    item = "▪ " + text.strip().lstrip("▪").strip()
    key = (section or "").strip()
    header_idx = None
    if key:
        for i, ln in enumerate(lines):
            if SECTION_HEADER_RE.match(ln.strip()) and key.split("/")[0][:3] in ln:
                header_idx = i
                break
    if header_idx is None:
        for i, ln in enumerate(lines):
            if SECTION_HEADER_RE.match(ln.strip()):
                header_idx = i
                break
    if header_idx is None:
        return briefing.rstrip("\n") + "\n" + item
    last_item = None
    for j in range(header_idx + 1, len(lines)):
        s = lines[j].strip()
        if SECTION_HEADER_RE.match(s) and j > header_idx:
            break
        if s.startswith("▪"):
            last_item = j
    at = (last_item + 1) if last_item is not None else (header_idx + 2 if header_idx + 1 < len(lines) and not lines[header_idx + 1].strip() else header_idx + 1)
    lines.insert(at, item)
    return "\n".join(lines)


def format_list(items: list[dict]) -> str:
    if not items:
        return "재검색 큐 비어 있음."
    out = []
    for it in items:
        out.append(f"#{it['id']} [{it['family']}/{it.get('section') or '-'}] 시도 {it.get('attempts', 0)}/{MAX_ATTEMPTS} · {it.get('status')}\n"
                   f"  {it['item_text'][:120]}" + (f"\n  ↳ {it['last_result'][:80]}" if it.get("last_result") else ""))
    return "\n".join(out)[:4000]
