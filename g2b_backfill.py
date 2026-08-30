"""
g2b_backfill.py — 나라장터 AI 사업 공고 백필 (2026-01-01 ~ 오늘, 월 단위)

파이프라인 (월×오퍼레이션×페이지 단위):
  입찰공고 조회(용역 기본 + 물품·공사) → 1차 키워드 필터 → 지자체 매핑
  → 2차 Haiku 판정(예/아니오/애매) → ai_projects upsert
  → (가능한 건만) 계약정보 API로 계약금액 매칭

운영 규칙:
  - 일 호출한도 1,000 준수: g2b_state 카운터, 한도 임박 시 체크포인트 저장 후 종료
  - 이어받기: g2b_state['backfill_checkpoint'] = {"month","op","page"} 부터 재개
  - API 장애·개별 건 실패는 스킵+로그 — 파이프라인 중단 없음
  - G2B_API_KEY 환경변수 필수 (없으면 안내 후 종료)

사용:
  python g2b_backfill.py                # 체크포인트부터 전체 백필
  python g2b_backfill.py --month 202601 # 특정 월만 (드라이런용)
  python g2b_backfill.py --no-contract  # 계약 매칭 생략
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, date

import requests

from g2b_tracker import (
    G2B_API_KEY_ENV, G2B_BASE, G2B_OPS, CNTRCT_BASE, CNTRCT_OP,
    init_db, state_get, state_set, bump_api_calls, under_call_limit,
    map_org, keyword_hit, judge_ai_project, upsert_project, db_conn, KST,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("g2b_backfill")

ROWS_PER_PAGE = 500
CHECKPOINT_KEY = "backfill_checkpoint"


# ══════════════════════════════════════════════════
#  API 호출
# ══════════════════════════════════════════════════
def _api_get(base: str, op: str, params: dict) -> dict | None:
    """공공데이터포털 GET. 한도 카운트 + 실패 시 None(스킵)."""
    key = os.environ.get(G2B_API_KEY_ENV)
    if not key:
        raise EnvironmentError(f"{G2B_API_KEY_ENV} 환경변수가 없습니다.")
    if not under_call_limit():
        return {"_limit": True}
    p = {"serviceKey": key, "type": "json", **params}
    try:
        bump_api_calls()
        r = requests.get(f"{base}/{op}", params=p, timeout=30)
        if r.status_code != 200:
            logger.warning(f"[백필] HTTP {r.status_code} — 스킵: {op} p={params.get('pageNo')}")
            return None
        return r.json()
    except Exception as e:
        logger.warning(f"[백필] API 오류 — 스킵: {op} {e}")
        return None


def _items(resp: dict) -> tuple[list, int]:
    """응답에서 (items, totalCount) 추출 — 스키마 변형에 관대하게."""
    try:
        body = resp["response"]["body"]
        items = body.get("items") or []
        if isinstance(items, dict):  # {"item": [...]} 형태 대응
            items = items.get("item") or []
        if isinstance(items, dict):
            items = [items]
        return items, int(body.get("totalCount") or 0)
    except Exception:
        return [], 0


def _month_range(yyyymm: str) -> tuple[str, str]:
    y, m = int(yyyymm[:4]), int(yyyymm[4:])
    start = f"{y:04d}{m:02d}010000"
    if m == 12:
        ny, nm = y + 1, 1
    else:
        ny, nm = y, m + 1
    # 월말 = 다음달 1일 직전
    import calendar
    last = calendar.monthrange(y, m)[1]
    end = f"{y:04d}{m:02d}{last:02d}2359"
    return start, end


def _months(from_yyyymm: str = "202601") -> list[str]:
    out, today = [], datetime.now(KST)
    y, m = int(from_yyyymm[:4]), int(from_yyyymm[4:])
    while (y, m) <= (today.year, today.month):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ══════════════════════════════════════════════════
#  1개월 × 1오퍼레이션 처리
# ══════════════════════════════════════════════════
def process_month_op(yyyymm: str, src_type: str, start_page: int = 1,
                     stats: dict | None = None) -> tuple[bool, int]:
    """(완료 여부, 마지막 페이지). 한도 도달 시 (False, page) 반환."""
    stats = stats if stats is not None else {}
    op = G2B_OPS[src_type]
    s, e = _month_range(yyyymm)
    page = start_page
    while True:
        resp = _api_get(G2B_BASE, op, {
            "inqryDiv": "1", "inqryBgnDt": s, "inqryEndDt": e,
            "pageNo": page, "numOfRows": ROWS_PER_PAGE,
        })
        if resp is None:                       # 이 페이지 실패 → 다음 페이지 시도 대신 중단(순서 보존)
            logger.warning(f"[백필] {yyyymm}/{src_type} p{page} 실패 — 해당 월 중단(스킵)")
            return True, page                  # 월 자체는 스킵 처리(파이프라인 계속)
        if resp.get("_limit"):
            return False, page                 # 한도 → 체크포인트
        items, total = _items(resp)
        stats["fetched"] = stats.get("fetched", 0) + len(items)

        for it in items:
            try:
                _process_item(it, src_type, stats)
            except Exception as ex:
                stats["errors"] = stats.get("errors", 0) + 1
                logger.warning(f"[백필] 건 처리 실패 — 스킵: {ex}")

        if page * ROWS_PER_PAGE >= total or not items:
            return True, page
        page += 1
        time.sleep(0.3)   # 예의상 간격


def _process_item(it: dict, src_type: str, stats: dict) -> None:
    bid_name = (it.get("bidNtceNm") or "").strip()
    if not keyword_hit(bid_name):
        return
    stats["keyword_hit"] = stats.get("keyword_hit", 0) + 1

    bid_no = f"{it.get('bidNtceNo', '')}-{it.get('bidNtceOrd', '00')}"
    org_name = (it.get("dminsttNm") or it.get("ntceInsttNm") or "").strip()

    # 이미 적재된 건은 판정 재호출 생략
    conn = db_conn()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM ai_projects WHERE bid_no=%s", (bid_no,))
            exists = cur.fetchone()
            conn.close()
            if exists:
                stats["dup"] = stats.get("dup", 0) + 1
                return
        except Exception:
            pass

    gov = map_org(org_name)
    verdict, reason = judge_ai_project(bid_name, org_name)
    stats[f"verdict_{verdict}"] = stats.get(f"verdict_{verdict}", 0) + 1

    def _num(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    notice_date = None
    raw_dt = (it.get("bidNtceDt") or "")[:10].replace("/", "-")
    if len(raw_dt) == 10:
        notice_date = raw_dt

    upsert_project({
        "bid_no": bid_no, "bid_name": bid_name[:500], "org_name": org_name,
        "gov_level": gov["gov_level"], "gov_name": gov["gov_name"],
        "org_tag": gov["org_tag"],
        "est_price": _num(it.get("presmptPrce")),
        "notice_date": notice_date,
        "contract_amount": None,
        "status": (it.get("ntceKindNm") or "공고")[:20],
        "ai_verdict": verdict, "ai_reason": reason, "src_type": src_type,
    })
    stats["saved"] = stats.get("saved", 0) + 1


# ══════════════════════════════════════════════════
#  계약금액 매칭 (가능한 건만 — 실패 무시)
# ══════════════════════════════════════════════════
def match_contracts(limit: int = 100) -> int:
    """계약금액 미기입 '예' 판정 건에 대해 계약정보 API 조회. 성공 건수 반환."""
    conn = db_conn()
    if not conn:
        return 0
    try:
        cur = conn.cursor()
        cur.execute("""SELECT bid_no FROM ai_projects
                       WHERE contract_amount IS NULL AND ai_verdict='예'
                       ORDER BY notice_date DESC LIMIT %s""", (limit,))
        targets = [r[0] for r in cur.fetchall()]
        conn.close()
    except Exception:
        return 0

    matched = 0
    for bid_no in targets:
        if not under_call_limit():
            break
        raw_no = bid_no.split("-")[0]
        resp = _api_get(CNTRCT_BASE, CNTRCT_OP, {
            "inqryDiv": "3", "bidNtceNo": raw_no, "pageNo": 1, "numOfRows": 5,
        })
        if not resp or resp.get("_limit"):
            continue
        items, _ = _items(resp)
        for c in items:
            amt = c.get("cntrctAmt") or c.get("thtmCntrctAmt")
            try:
                amt = int(float(amt))
            except (TypeError, ValueError):
                continue
            conn = db_conn()
            if conn:
                try:
                    cur = conn.cursor()
                    cur.execute("UPDATE ai_projects SET contract_amount=%s, status='계약' WHERE bid_no=%s",
                                (amt, bid_no))
                    conn.commit()
                    conn.close()
                    matched += 1
                except Exception:
                    pass
            break
        time.sleep(0.3)
    logger.info(f"[백필] 계약 매칭 {matched}건")
    return matched


# ══════════════════════════════════════════════════
#  메인
# ══════════════════════════════════════════════════
def run_backfill(only_month: str | None = None, do_contract: bool = True) -> dict:
    if not os.environ.get(G2B_API_KEY_ENV):
        logger.error(f"[백필] {G2B_API_KEY_ENV} 미설정 — 키 등록 후 재실행하세요.")
        return {"error": "no_api_key"}
    init_db()

    months = [only_month] if only_month else _months("202601")
    ops = list(G2B_OPS.keys())        # 용역(기본) → 물품 → 공사

    # 체크포인트 로드 (특정 월 지정 시 무시)
    cp = None
    if not only_month:
        try:
            cp = json.loads(state_get(CHECKPOINT_KEY) or "null")
        except Exception:
            cp = None

    stats: dict = {}
    started = False
    for month in months:
        for op in ops:
            page = 1
            if cp and not started:
                if month == cp["month"] and op == cp["op"]:
                    page, started = cp["page"], True
                elif month == cp["month"] or months.index(month) >= months.index(cp["month"]):
                    if month != cp["month"] or ops.index(op) >= ops.index(cp["op"]):
                        started = True
                    else:
                        continue
                else:
                    continue
            logger.info(f"[백필] {month} {op} p{page}~ 시작 (오늘 호출 잔여 확인 중)")
            done, last_page = process_month_op(month, op, page, stats)
            if not done:
                state_set(CHECKPOINT_KEY, json.dumps(
                    {"month": month, "op": op, "page": last_page}))
                logger.warning(f"[백필] 일 호출한도 임박 — 체크포인트 저장 후 종료: "
                               f"{month}/{op}/p{last_page}")
                stats["stopped_at_limit"] = True
                return stats
    # 전체 완료 → 체크포인트 제거
    if not only_month:
        state_set(CHECKPOINT_KEY, "null")

    if do_contract:
        stats["contracts"] = match_contracts()
    logger.info(f"[백필] 완료: {stats}")
    return stats


if __name__ == "__main__":
    only = None
    if "--month" in sys.argv:
        only = sys.argv[sys.argv.index("--month") + 1]
    stats = run_backfill(only_month=only, do_contract="--no-contract" not in sys.argv)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
