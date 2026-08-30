"""
g2b_daily.py — AI 행정 트래커 일일 수집 (전일 공고분)

매일 07:30 KST 스케줄러 실행:
  전일 공고 조회(용역+물품+공사) → 키워드 → 매핑 → Haiku 판정 → 적재
  → 계약 매칭(소량) → 텔레그램 요약 카드 생성

텔레그램 발송 정책:
  - 관리자 DM 미리보기: 항상 (검수용)
  - 정보방(@gazzzza2025) 발행: 환경변수 G2B_PUBLISH_TELEGRAM=true 일 때만
    (기본 OFF — 관리자 검수 후 켠다)

안전: 모든 실패는 스킵+로그. 기존 브리핑/AESA 기능과 완전 독립.
"""

import os
import logging
from datetime import datetime, timedelta

from g2b_tracker import (
    G2B_API_KEY_ENV, G2B_OPS, init_db, map_org, keyword_hit,
    judge_ai_project, upsert_project, db_conn, under_call_limit, KST,
    reconcile_duplicates,
)
from g2b_backfill import _api_get, _items, match_contracts, G2B_BASE, ROWS_PER_PAGE, _process_item

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("g2b_daily")

PUBLISH_FLAG_ENV = "G2B_PUBLISH_TELEGRAM"      # 기본 OFF — 검수 후 true 로
PUBLIC_CHANNEL = "@gazzzza2025"


def collect_yesterday() -> dict:
    """전일(00:00~23:59) 공고 수집 파이프라인. 실패는 스킵."""
    stats: dict = {}
    y = datetime.now(KST) - timedelta(days=1)
    s = y.strftime("%Y%m%d0000")
    e = y.strftime("%Y%m%d2359")

    for src_type, op in G2B_OPS.items():
        page = 1
        while under_call_limit():
            resp = _api_get(G2B_BASE, op, {
                "inqryDiv": "1", "inqryBgnDt": s, "inqryEndDt": e,
                "pageNo": page, "numOfRows": ROWS_PER_PAGE,
            })
            if not resp or resp.get("_limit"):
                break
            items, total = _items(resp)
            for it in items:
                try:
                    _process_item(it, src_type, stats)
                except Exception as ex:
                    logger.warning(f"[데일리] 건 처리 실패 — 스킵: {ex}")
            if page * ROWS_PER_PAGE >= total or not items:
                break
            page += 1
    return stats


def _fmt_amt(v):
    if not v:
        return "금액 미공개"
    if v >= 100_000_000:
        return f"{v / 100_000_000:.1f}억"
    return f"{v // 10_000:,}만원"


TRACKER_FOOTER = "📊 전국 244개 지자체 누적 현황 → nr2.kr/ai-tracker"


def build_daily_report(contract_updates: list[dict] | None = None) -> str:
    """일보 카드 — 전일 등록·변경된 지자체 AI 공고 브리핑.

    0건인 날도 '전일 신규 발주 없음'으로 항상 문자열을 반환한다(매일 발송).
    신규 공고는 광역/기초 구분·금액순 전건 나열 — 발송 측에서 4096자 분할.
    """
    y = (datetime.now(KST) - timedelta(days=1)).date()
    header = f"🤖 지자체 AI 발주 일보 | {y.strftime('%Y.%m.%d')}(전일) 기준"

    new_rows, cancel_rows = [], []
    conn = db_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT gov_level, gov_name, bid_name, est_price, org_tag, src_type
                FROM ai_projects
                WHERE notice_date = %s AND ai_verdict='예' AND gov_name <> '미분류'
                  AND is_latest AND status NOT LIKE '%%취소%%'
                ORDER BY COALESCE(est_price,0) DESC""", (y,))
            new_rows = cur.fetchall()
            cur.execute("""
                SELECT gov_name, bid_name FROM ai_projects
                WHERE notice_date = %s AND ai_verdict='예' AND gov_name <> '미분류'
                  AND is_latest AND status LIKE '%%취소%%'""", (y,))
            cancel_rows = cur.fetchall()
        except Exception as ex:
            logger.warning(f"[일보] 집계 실패: {ex}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    lines = [header, ""]
    if new_rows:
        lines.append(f"▪ 신규 공고 {len(new_rows)}건 (금액순)")
        for lvl, gov, name, price, tag, src in new_rows:
            tag_s = f"·{tag}" if tag and tag != "지자체" else ""
            lines.append(f"[{lvl}{tag_s}] {gov} | {name} | {_fmt_amt(price)}")
    else:
        lines.append("▪ 전일 신규 발주 없음")

    if cancel_rows:
        lines += ["", f"▪ 취소 공고 {len(cancel_rows)}건"]
        for gov, name in cancel_rows:
            lines.append(f"[{gov}] {name[:60]}")

    if contract_updates:
        lines += ["", f"▪ 계약 확인 {len(contract_updates)}건"]
        for c in contract_updates:
            lines.append(f"[{c['gov_name']}] {c['bid_name'][:50]} — 계약 {_fmt_amt(c['amount'])}")

    lines += ["", TRACKER_FOOTER]
    return "\n".join(lines)


def send_card(card: str) -> None:
    """관리자 미리보기 항상 + 발행 플래그 ON 시에만 정보방 발송.

    일보가 전건 나열이라 길 수 있음 — 4096자 초과 시 줄 단위 분할 발송.
    """
    try:
        from app.utils.telegram_notify import send_telegram_message, send_to_admin
        from ai_briefing import _split_text
        publish = os.environ.get(PUBLISH_FLAG_ENV, "false").lower() == "true"

        preview_head = ("🔍 <b>[검수용] AI 행정 트래커 일보</b>\n"
                        f"(정보방 발행: {'ON' if publish else 'OFF — 플래그로 제어'})\n\n")
        chunks = _split_text(preview_head + card, limit=4000)
        for ch in chunks:
            send_to_admin(ch)
        if publish:
            for ch in _split_text(card, limit=4000):
                send_telegram_message(ch, chat_id=PUBLIC_CHANNEL)
            logger.info("[데일리] 정보방 발행 완료")
        else:
            logger.info(f"[데일리] 발행 플래그 OFF — 관리자 미리보기만 "
                        f"({len(chunks)}개 메시지, {PUBLISH_FLAG_ENV}=true 로 활성화)")
    except Exception as ex:
        logger.warning(f"[데일리] 텔레그램 발송 실패(무시): {ex}")


def run_daily() -> None:
    """스케줄러 진입점 — 어떤 실패도 밖으로 던지지 않는다."""
    try:
        if not os.environ.get(G2B_API_KEY_ENV):
            logger.warning(f"[데일리] {G2B_API_KEY_ENV} 미설정 — 수집 생략")
            return
        init_db()
        stats = collect_yesterday()
        reconcile_duplicates()   # 변경·정정 재공고 차수 정리 (멱등)
        logger.info(f"[데일리] 수집 통계: {stats}")
        contract_updates = []
        try:
            contract_updates = match_contracts(limit=30)
        except Exception as ex:
            logger.warning(f"[데일리] 계약 매칭 실패(무시): {ex}")
        # 일보는 0건인 날도 항상 발송
        send_card(build_daily_report(contract_updates))
    except Exception as e:
        logger.error(f"[데일리] 파이프라인 오류(다음 실행에 재시도): {e}", exc_info=True)


if __name__ == "__main__":
    run_daily()
