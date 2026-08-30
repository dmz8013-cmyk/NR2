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


def build_summary_card() -> str | None:
    """오늘 신규 적재분 요약 카드 (▪ 포맷). 신규 0건이면 None."""
    conn = db_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        # 오늘 수집된 '예' 판정 신규 건
        cur.execute("""
            SELECT bid_name, gov_name, est_price FROM ai_projects
            WHERE collected_at::date = CURRENT_DATE AND ai_verdict = '예'
              AND gov_name <> '미분류'
            ORDER BY COALESCE(est_price, 0) DESC LIMIT 5""")
        top5 = cur.fetchall()
        cur.execute("""SELECT COUNT(*) FROM ai_projects
                       WHERE collected_at::date = CURRENT_DATE AND ai_verdict='예' AND gov_name <> '미분류'""")
        today_n = cur.fetchone()[0]
        cur.execute("""SELECT COUNT(*), COALESCE(SUM(est_price),0) FROM ai_projects
                       WHERE ai_verdict='예' AND gov_name <> '미분류'""")
        total_n, total_amt = cur.fetchone()
        conn.close()
    except Exception as ex:
        logger.warning(f"[데일리] 카드 집계 실패: {ex}")
        return None

    if today_n == 0:
        return None

    def _fmt_amt(v):
        if not v:
            return "금액 미공개"
        if v >= 100_000_000:
            return f"{v / 100_000_000:.1f}억"
        return f"{v // 10_000:,}만원"

    lines = [f"🤖 오늘의 지자체 AI 발주 {today_n}건", ""]
    for name, gov, price in top5:
        lines.append(f"▪ [{gov}] {name[:50]}")
        lines.append(f"　→ 추정가격 {_fmt_amt(price)}")
    lines += ["", f"📊 누적 집계: {total_n}건 · 추정 {_fmt_amt(total_amt)}",
              "(나라장터 발주 공고 기준 — 예산 편성액과 다름)"]
    return "\n".join(lines)


def send_card(card: str) -> None:
    """관리자 미리보기 항상 + 발행 플래그 ON 시에만 정보방 발송."""
    try:
        from app.utils.telegram_notify import send_telegram_message, send_to_admin
        publish = os.environ.get(PUBLISH_FLAG_ENV, "false").lower() == "true"
        send_to_admin("🔍 <b>[검수용] AI 행정 트래커 카드</b>\n"
                      f"(정보방 발행: {'ON' if publish else 'OFF — 플래그로 제어'})\n\n" + card)
        if publish:
            send_telegram_message(card, chat_id=PUBLIC_CHANNEL)
            logger.info("[데일리] 정보방 발행 완료")
        else:
            logger.info(f"[데일리] 발행 플래그 OFF — 관리자 미리보기만 발송 "
                        f"({PUBLISH_FLAG_ENV}=true 로 활성화)")
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
        logger.info(f"[데일리] 수집 통계: {stats}")
        try:
            match_contracts(limit=30)
        except Exception as ex:
            logger.warning(f"[데일리] 계약 매칭 실패(무시): {ex}")
        card = build_summary_card()
        if card:
            send_card(card)
        else:
            logger.info("[데일리] 오늘 신규 '예' 판정 없음 — 카드 생략")
    except Exception as e:
        logger.error(f"[데일리] 파이프라인 오류(다음 실행에 재시도): {e}", exc_info=True)


if __name__ == "__main__":
    run_daily()
