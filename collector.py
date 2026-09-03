"""
collector.py — AI 거두 워치 Phase 2: xAI 자동 수집기

xAI Live Search(X 소스)로 워치리스트 150명의 게시물을 티어별 주기로 수집:
  T1 매시 정각(06~23시) · T2 06/18시 · T3 06시  (창: watchlist rules.window_hours)
  → 필터(리포스트·이모지 답글·Congrats·링크 없음 제거) → post_url 중복 스킵
  → leader_posts 에 pending(published=FALSE, score NULL) 적재
07:00 daily_edit: 전일 07시 이후 누적분을 Phase 1 편집 파이프라인(채점→카드→
  verify_pass→관리자 미리보기)으로 — 발행은 /leaders_ok 수동 승인 그대로.
매월 1일 07:30 monthly_report: 핸들별 30일 통계 CSV → 관리자 DM.

안전:
  - XAI_API_KEY 미설정 → 모든 수집 함수 조용히 스킵 (수동 모드만 동작)
  - 일일 호출 상한 LEADERS_MAX_CALLS(기본 40) 초과 → 중단 + 관리자 DM 1회
  - 배치당 핸들 최대 20, 검색 소스 상한 LEADERS_MAX_SOURCES(기본 10)
  - 모든 실패는 스킵+로그, 스케줄러/발행 중단 경로 없음
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import requests

from g2b_tracker import db_conn, state_get, state_set
from leader_watch import (
    load_watchlist, init_leader_db, score_items, build_card,
    _send_admin, admin_chat_id, DRAFT_STATE_KEY, MIN_SCORE, MAX_ITEMS, WATCHLIST_PATH,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("leader_collector")

KST = ZoneInfo("Asia/Seoul")
# 2026-09: Live Search(chat/completions+search_parameters) 폐기(HTTP 410) →
# Agent Tools API(/v1/responses + x_search 도구)로 전환
XAI_URL = "https://api.x.ai/v1/responses"
XAI_MODEL = os.environ.get("XAI_MODEL", "grok-4.6")
BATCH_SIZE = 20                                   # 쿼리당 핸들 상한 (스펙)
CALLS_KEY_PREFIX = "leaders_api_calls_"
COST_KEY_PREFIX = "leaders_cost_ticks_"        # 일별 / 월별(YYYY-MM) usd_ticks 누적
LIMIT_ALERT_PREFIX = "leaders_limit_alert_"

CONGRATS_RE = re.compile(r"congrat|축하|🎉\s*$|happy\s+(birthday|anniversary)", re.I)
EMOJI_ONLY_RE = re.compile(r"^[\W\s\U0001F000-\U0001FAFF]+$")


def _max_calls() -> int:
    # 기본 20: T1 4회×2배치 + T2 2회×4배치 + T3 1회×3배치 = 19회/일
    try:
        return int(os.environ.get("LEADERS_MAX_CALLS", "20"))
    except ValueError:
        return 20


def _calls_today() -> int:
    try:
        return int(state_get(CALLS_KEY_PREFIX + date.today().isoformat()) or 0)
    except (TypeError, ValueError):
        return 0


def _bump_calls() -> int:
    n = _calls_today() + 1
    state_set(CALLS_KEY_PREFIX + date.today().isoformat(), str(n))
    return n


def _check_budget() -> bool:
    """상한 이내면 True. 초과 시 관리자 DM 1회 후 False."""
    if _calls_today() < _max_calls():
        return True
    alert_key = LIMIT_ALERT_PREFIX + date.today().isoformat()
    if state_get(alert_key) != "1":
        state_set(alert_key, "1")
        _send_admin(f"⚠️ <b>거두 워치 수집 중단</b>\n"
                    f"일일 xAI 호출 상한({_max_calls()}) 도달 — 내일 자정 리셋.\n"
                    f"상한 조정: LEADERS_MAX_CALLS 환경변수")
    return False


def _watch_rules() -> dict:
    try:
        with open(WATCHLIST_PATH, encoding="utf-8") as f:
            return json.load(f).get("rules", {})
    except Exception:
        return {}


# ══════════════════════════════════════════════════
#  1. xAI Live Search 호출
# ══════════════════════════════════════════════════
COLLECT_PROMPT = """TASK: X posts by {handles} in last {hours}h.
OUTPUT: JSON array ONLY. No prose, no markdown, no explanation. Empty -> []
Schema per item:
{{"handle":"no @","ts":"ISO8601","text":"full post text","url":"https://x.com/...",
  "metrics":{{"views":int|null,"likes":int|null,"reposts":int|null}},
  "is_reply":bool,"is_repost":bool}}
Exclude: pure reposts, items without URL. Quote-posts: own comment only as text."""


def _xai_search(handles: list[str], window_hours: int) -> list[dict] | None:
    """핸들 배치 1회 검색. 키 없음/실패 시 None(스킵)."""
    key = os.environ.get("XAI_API_KEY")
    if not key:
        return None
    if not _check_budget():
        return None
    now = datetime.now(KST)
    frm = (now - timedelta(hours=window_hours)).astimezone(ZoneInfo("UTC"))
    to = now.astimezone(ZoneInfo("UTC"))

    def _payload(date_only: bool) -> dict:
        tool = {"type": "x_search", "allowed_x_handles": handles}
        if date_only:
            tool["from_date"] = frm.strftime("%Y-%m-%d")
            tool["to_date"] = to.strftime("%Y-%m-%d")
        else:
            tool["from_date"] = frm.strftime("%Y-%m-%dT%H:%M:%SZ")
            tool["to_date"] = to.strftime("%Y-%m-%dT%H:%M:%SZ")
        p = {
            "model": XAI_MODEL,
            "input": [{"role": "user", "content": COLLECT_PROMPT.format(
                hours=window_hours, handles=", ".join("@" + h for h in handles))}],
            "tools": [tool],
        }
        if not date_only:
            # 실측: effort low 로 추론 토큰 41%·도구 호출 절반 감소, 결과 동일
            # (400 폴백 경로에서는 제거 — 비추론 모델 오버라이드 대비)
            p["reasoning"] = {"effort": "low"}
        return p

    def _extract_text(data: dict) -> str:
        parts = []
        for item in data.get("output", []) or []:
            for c in (item.get("content") or []):
                if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                    parts.append(c.get("text", ""))
        return "\n".join(parts) or str(data.get("output_text") or "")

    try:
        _bump_calls()
        r = requests.post(XAI_URL, json=_payload(date_only=False), timeout=180,
                          headers={"Authorization": f"Bearer {key}"})
        if r.status_code == 400:
            # 날짜 형식 미수용 폴백: date-only ISO8601
            r = requests.post(XAI_URL, json=_payload(date_only=True), timeout=180,
                              headers={"Authorization": f"Bearer {key}"})
        if r.status_code != 200:
            logger.warning(f"[수집] xAI HTTP {r.status_code}: {r.text[:300]}")
            return None
        data = r.json()
        usage = data.get("usage")
        if usage:
            logger.info(f"[수집] usage: {json.dumps(usage, ensure_ascii=False)[:300]}")
            try:
                ticks = int(usage.get("cost_in_usd_ticks") or 0)
                for k in (COST_KEY_PREFIX + date.today().isoformat(),
                          COST_KEY_PREFIX + date.today().strftime("%Y-%m")):
                    state_set(k, str(int(state_get(k) or 0) + ticks))
            except Exception:
                pass
        content = _extract_text(data)
        s, e = content.find("["), content.rfind("]")
        if s == -1 or e <= s:
            return []
        posts = json.loads(content[s:e + 1])
        return posts if isinstance(posts, list) else []
    except Exception as ex:
        logger.warning(f"[수집] xAI 호출 실패 스킵: {ex}")
        return None


# ══════════════════════════════════════════════════
#  2. 필터 + 적재
# ══════════════════════════════════════════════════
def _passes_filters(p: dict, rules: dict) -> bool:
    text = (p.get("text") or "").strip()
    url = (p.get("url") or "").strip()
    if rules.get("require_link", True) and not url.startswith("http"):
        return False
    if rules.get("drop_reposts", True) and (p.get("is_repost") or text.startswith("RT @")):
        return False
    if rules.get("drop_emoji_only_replies", True) and p.get("is_reply") \
            and (not text or EMOJI_ONLY_RE.fullmatch(text)):
        return False
    if rules.get("drop_congrats", True) and len(text) < 80 and CONGRATS_RE.search(text):
        return False
    return bool(text)


def _store_pending(posts: list[dict], tier: int) -> int:
    """필터 통과분을 pending 으로 적재 (post_url UNIQUE 중복 스킵)."""
    conn = db_conn()
    if not conn:
        return 0
    wl = {p["handle"].lower(): p for p in load_watchlist()}
    saved = 0
    try:
        cur = conn.cursor()
        for p in posts:
            handle = (p.get("handle") or "").lstrip("@")
            person = wl.get(handle.lower())
            cur.execute("""
                INSERT INTO leader_posts
                  (date, handle, name, tier, post_url, raw_text, metrics_json,
                   lens, bias_label, published)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'거두',%s,FALSE)
                ON CONFLICT (post_url) DO NOTHING
            """, (datetime.now(KST).date(), handle,
                  (person or {}).get("name") or handle,
                  (person or {}).get("tier") or tier,
                  p["url"], (p.get("text") or "")[:2000],
                  json.dumps(p.get("metrics") or {}, ensure_ascii=False),
                  (person or {}).get("bias_label")))
            saved += cur.rowcount
        conn.commit()
        conn.close()
    except Exception as ex:
        logger.warning(f"[수집] 적재 실패 스킵: {ex}")
        try:
            conn.close()
        except Exception:
            pass
    return saved


def collect_tier(tier: int) -> None:
    """티어별 수집 1회 — 스케줄러 진입점. 어떤 실패도 던지지 않음."""
    try:
        if not os.environ.get("XAI_API_KEY"):
            logger.info(f"[수집] XAI_API_KEY 미설정 — T{tier} 스킵(수동 모드)")
            return
        init_leader_db()
        rules = _watch_rules()
        window = (rules.get("window_hours") or {}).get(f"T{tier}", 24)
        handles = [p["handle"] for p in load_watchlist() if p.get("tier") == tier]
        total_new, total_raw = 0, 0
        for i in range(0, len(handles), BATCH_SIZE):
            batch = handles[i:i + BATCH_SIZE]
            posts = _xai_search(batch, window)
            if posts is None:
                break                          # 키 없음/상한/오류 — 이번 회차 중단
            total_raw += len(posts)
            good = [p for p in posts if _passes_filters(p, rules)]
            total_new += _store_pending(good, tier)
        logger.info(f"[수집] T{tier} 완료 — 원시 {total_raw} → 신규 적재 {total_new} "
                    f"(오늘 호출 {_calls_today()}/{_max_calls()})")
    except Exception as e:
        logger.error(f"[수집] T{tier} 오류(다음 회차 재시도): {e}", exc_info=True)


def _cost_line() -> str:
    """전일 호출·비용 + 이달 누적 한 줄 (1 tick = 1e-10 USD)."""
    try:
        y = (date.today() - timedelta(days=1)).isoformat()
        calls = int(state_get(CALLS_KEY_PREFIX + y) or 0)
        d_usd = int(state_get(COST_KEY_PREFIX + y) or 0) * 1e-10
        m_usd = int(state_get(COST_KEY_PREFIX + date.today().strftime("%Y-%m")) or 0) * 1e-10
        return f"💸 전일 호출 {calls}회 · ${d_usd:.2f} / 이달 누적 ${m_usd:.2f}"
    except Exception:
        return ""


# ══════════════════════════════════════════════════
#  3. 07:00 일일 편집 — Phase 1 파이프라인으로 인계
# ══════════════════════════════════════════════════
def daily_edit() -> None:
    """전일 07:00 이후 pending 누적분 → 채점→카드→verify→관리자 미리보기."""
    try:
        init_leader_db()
        conn = db_conn()
        if not conn:
            return
        since = datetime.now(KST) - timedelta(hours=24)
        cur = conn.cursor()
        cur.execute("""SELECT handle, name, tier, post_url, raw_text, bias_label
                       FROM leader_posts
                       WHERE score IS NULL AND NOT published AND created_at >= %s
                         AND raw_text IS NOT NULL""", (since,))
        rows = cur.fetchall()
        conn.close()
        if not rows:
            logger.info("[편집] pending 0건 — 미리보기 생략")
            return

        wl = {p["handle"].lower(): p for p in load_watchlist()}
        items = []
        for handle, name, tier, url, raw, bias in rows:
            person = wl.get((handle or "").lower(), {})
            items.append({"handle": handle, "name": name,
                          "affil": person.get("affil", ""), "tier": tier,
                          "bias_label": bias, "matched": bool(person),
                          "summary_raw": raw, "post_url": url})

        scored = score_items(items)
        # 채점 결과를 DB에 기록 (통과·오탐 통계용 — 월간 리포트 근거)
        conn = db_conn()
        if conn:
            try:
                cur = conn.cursor()
                for it in scored:
                    cur.execute("""UPDATE leader_posts SET score=%s, summary_ko=%s
                                   WHERE post_url=%s""",
                                (it.get("score", 0), it.get("summary_ko", ""),
                                 it["post_url"]))
                conn.commit()
                conn.close()
            except Exception:
                pass

        passed = sorted([i for i in scored if i.get("score", 0) >= MIN_SCORE],
                        key=lambda x: -x["score"])[:MAX_ITEMS]
        if not passed:
            _send_admin(f"ℹ️ 거두 워치 07시 편집 — 수집 {len(rows)}건 중 "
                        f"{MIN_SCORE}점 이상 0건. 오늘 발행 없음.\n" + _cost_line())
            return

        today = datetime.now(KST).strftime("%Y-%m-%d")
        card = build_card(passed, datetime.now(KST).strftime("%m/%d"))
        try:
            from verify_pass import run_verify_pass
            card = run_verify_pass(card, briefing_type="leader_watch")
        except Exception as ve:
            logger.warning(f"[편집] verify_pass 스킵: {ve}")

        state_set(DRAFT_STATE_KEY, json.dumps(
            {"date": today, "card": card, "items": passed}, ensure_ascii=False))
        _send_admin("🔍 <b>[미리보기] AI 거두 워치 (자동 수집)</b>\n"
                    f"(수집 {len(rows)} → 통과 {len(passed)})\n"
                    + _cost_line() + "\n"
                    "승인: /leaders_ok · 폐기: /leaders_no\n\n" + card)
        logger.info(f"[편집] 미리보기 발송 — 통과 {len(passed)}/{len(rows)}")
    except Exception as e:
        logger.error(f"[편집] 실패: {e}", exc_info=True)
        _send_admin(f"❌ <b>거두 워치 07시 편집 실패</b>\n{str(e)[:300]}")


# ══════════════════════════════════════════════════
#  4. 월간 리뉴얼 리포트 (매월 1일 07:30)
# ══════════════════════════════════════════════════
def monthly_report() -> None:
    """핸들별 30일 게시·통과·평균 파급·오탐 → 관리자 DM + CSV."""
    try:
        conn = db_conn()
        if not conn:
            return
        cur = conn.cursor()
        cur.execute("""
            SELECT handle, MAX(name), COUNT(*),
                   COUNT(*) FILTER (WHERE score >= %s),
                   COUNT(*) FILTER (WHERE score IS NOT NULL AND score < %s),
                   AVG(NULLIF((metrics_json::json->>'views'), '')::bigint)
            FROM leader_posts
            WHERE created_at >= NOW() - INTERVAL '30 days'
            GROUP BY handle ORDER BY 3 DESC""", (MIN_SCORE, MIN_SCORE))
        rows = cur.fetchall()
        conn.close()
        if not rows:
            _send_admin("ℹ️ 거두 워치 월간 리포트 — 지난 30일 수집 데이터 없음.")
            return

        import csv
        path = "/tmp/leader_watch_monthly.csv"
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(["핸들", "이름", "30일 게시수", "통과수(7+)", "오탐수", "평균 조회수"])
            for r in rows:
                w.writerow([r[0], r[1], r[2], r[3], r[4],
                            int(r[5]) if r[5] else ""])

        top = "\n".join(f"· @{r[0]} 게시 {r[2]} / 통과 {r[3]}" for r in rows[:10])
        _send_admin("📊 <b>거두 워치 월간 리뉴얼 리포트</b>\n"
                    f"활성 핸들 {len(rows)}개 (상위 10)\n{top}\n\n"
                    "강등·승격 기준은 watchlist_2026-09.md §5 — CSV 첨부 전송 중")
        # CSV 파일 전송
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if token:
            with open(path, "rb") as f:
                requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                              data={"chat_id": admin_chat_id()},
                              files={"document": ("leader_watch_monthly.csv", f)},
                              timeout=60)
    except Exception as e:
        logger.error(f"[월간] 리포트 실패: {e}", exc_info=True)
        _send_admin(f"❌ 거두 워치 월간 리포트 실패\n{str(e)[:200]}")


if __name__ == "__main__":
    import sys
    if "--edit" in sys.argv:
        daily_edit()
    elif "--monthly" in sys.argv:
        monthly_report()
    else:
        collect_tier(int(sys.argv[sys.argv.index("--tier") + 1]) if "--tier" in sys.argv else 1)
