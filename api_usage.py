"""api_usage.py — Anthropic 호출 토큰·캐시·비용 일별 집계 (2026-10-21 B안).

모델 교체(Sonnet 4.6 → 5.5)와 프롬프트 캐싱의 효과를 사후 확인하기 위한 계측.
호출부에서 `record(module, model, resp.usage)` 한 줄만 부르면 된다.

  · 로그: 회차마다 캐시 적중률·비용 한 줄 (railway logs 로 즉시 확인)
  · 집계: g2b_state 에 `apiuse:<YYYY-MM-DD>:<module>` JSON 누적
          (로그 보존 기간이 짧아 24h 비교는 이쪽을 근거로 삼는다)

어떤 실패도 본 파이프라인을 막지 않는다 — 계측은 전부 try/except 삼킴.
"""
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("api_usage")
KST = ZoneInfo("Asia/Seoul")
KEY_PREFIX = "apiuse:"

# $/MTok (input, output). 캐시 쓰기 1.25x(5분 TTL), 읽기는 모델별 배수(입력가 기준).
# 공식 요금표: 캐시 읽기 0.1x, 단 Opus 5.5·Sonnet 5.5 는 0.05x (2026-11-16 확인).
PRICES = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10
CACHE_READ_MULT_BY_MODEL = {"claude-sonnet-5-5": 0.05, "claude-opus-5-5": 0.05}
WEB_SEARCH_USD = 10.0 / 1000          # $10 / 1,000 검색 (토큰 별도)


def _get(obj, name):
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _fields(usage) -> dict:
    g = (lambda n: int(_get(usage, n) or 0))
    stu = _get(usage, "server_tool_use")
    return {"in": g("input_tokens"), "out": g("output_tokens"),
            "cw": g("cache_creation_input_tokens"), "cr": g("cache_read_input_tokens"),
            "ws": int(_get(stu, "web_search_requests") or 0)}


def cost_usd(model: str, f: dict) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    rmult = CACHE_READ_MULT_BY_MODEL.get(model, CACHE_READ_MULT)
    return ((f["in"] + f["cw"] * CACHE_WRITE_MULT + f["cr"] * rmult) * pin
            + f["out"] * pout) / 1e6 + f.get("ws", 0) * WEB_SEARCH_USD


def record(module: str, model: str, usage, day: str | None = None) -> dict:
    """1회 호출 사용량 누적. → 이번 호출의 {in,out,cw,cr,usd} (실패 시 빈 dict)."""
    try:
        f = _fields(usage)
        f["usd"] = cost_usd(model, f)
        day = day or datetime.now(KST).strftime("%Y-%m-%d")
        key = f"{KEY_PREFIX}{day}:{module}"
        from g2b_tracker import state_get, state_set
        try:
            acc = json.loads(state_get(key) or "{}")
        except Exception:
            acc = {}
        acc["model"] = model
        acc["calls"] = int(acc.get("calls", 0)) + 1
        for k in ("in", "out", "cw", "cr", "ws"):
            acc[k] = int(acc.get(k, 0)) + f[k]
        acc["usd"] = round(float(acc.get("usd", 0.0)) + f["usd"], 6)
        state_set(key, json.dumps(acc))
        return f
    except Exception as e:
        logger.debug(f"[사용량] 기록 실패(무시): {e}")
        return {}


def summary_line(module: str, day: str | None = None) -> str:
    """'AESA 1,240회 · 캐시적중 86% · 입력 1.3M(캐시 1.1M) · 출력 0.4M · $2.41'"""
    try:
        day = day or datetime.now(KST).strftime("%Y-%m-%d")
        from g2b_tracker import state_get
        a = json.loads(state_get(f"{KEY_PREFIX}{day}:{module}") or "{}")
        if not a:
            return f"{module} {day}: 기록 없음"
        billed_in = a.get("in", 0) + a.get("cw", 0) + a.get("cr", 0)
        hit = (100 * a.get("cr", 0) / billed_in) if billed_in else 0.0
        return (f"{module} {day}: {a.get('calls', 0):,}회 · 캐시적중 {hit:.0f}% "
                f"· 입력 {billed_in/1e6:.2f}M(캐시읽기 {a.get('cr', 0)/1e6:.2f}M) "
                f"· 출력 {a.get('out', 0)/1e6:.2f}M · ${a.get('usd', 0):.2f} "
                f"[{a.get('model', '?')}]")
    except Exception as e:
        return f"{module} 집계 실패: {e}"


def log_summary(module: str, day: str | None = None) -> None:
    logger.info("[사용량] " + summary_line(module, day))


# ══════════════════════════════════════════════════
#  전 호출 자동 계측 (2026-11-24)
# ══════════════════════════════════════════════════
# 호출부 25곳에 record() 를 하나씩 심는 대신, SDK 의 Messages.create 를 한 번 감싸
# 모든 호출을 '호출한 파일.함수@모델' 키로 기록한다. 스케줄러·웹앱 시작 시 install().
# raw HTTP 호출(app/routes/bias.py)은 응답 JSON 의 usage 로 record() 를 직접 부른다.
_INSTALLED = False
_SKIP_FILES = ("anthropic", "api_usage", "score_cascade", "httpx", "httpcore", "functools")


def caller_label(depth_limit: int = 25) -> str:
    """SDK·계측 모듈 바깥의 첫 호출 프레임 → 'aesa_monitoring_bot.process_rss_feeds'."""
    import os
    import sys
    f = sys._getframe(1)
    for _ in range(depth_limit):
        if f is None:
            break
        path = f.f_code.co_filename or ""
        stem = os.path.splitext(os.path.basename(path))[0]
        if not any(k in path for k in ("/anthropic/", "/httpx", "/httpcore")) \
                and stem not in _SKIP_FILES:
            return f"{stem}.{f.f_code.co_name}"
        f = f.f_back
    return "unknown"


def label_for(model: str, label: str | None = None) -> str:
    return f"{label or caller_label()}@{model}"


def install() -> bool:
    """Messages.create 를 감싸 모든 동기 호출의 usage 를 기록. 여러 번 불러도 1회만 적용."""
    global _INSTALLED
    if _INSTALLED:
        return True
    try:
        import functools
        from anthropic.resources.messages import Messages
        orig = Messages.create

        @functools.wraps(orig)
        def create(self, *args, **kwargs):
            resp = orig(self, *args, **kwargs)
            try:
                model = kwargs.get("model") or getattr(resp, "model", "") or "?"
                usage = getattr(resp, "usage", None)
                if usage is not None:
                    record(label_for(model), model, usage)
            except Exception:
                pass
            return resp

        Messages.create = create
        _INSTALLED = True
        logger.info("[사용량] Anthropic 전 호출 자동 계측 활성화")
        return True
    except Exception as e:
        logger.warning(f"[사용량] 자동 계측 설치 실패(무시): {e}")
        return False


def day_totals(day: str | None = None) -> tuple[dict, dict]:
    """→ (합계 {calls,in,out,cw,cr,ws,usd}, 모듈별 {label: acc}). g2b_state 의 당일 키 전부."""
    day = day or datetime.now(KST).strftime("%Y-%m-%d")
    total = {"calls": 0, "in": 0, "out": 0, "cw": 0, "cr": 0, "ws": 0, "usd": 0.0}
    per = {}
    try:
        from g2b_tracker import db_conn
        conn = db_conn()
        if not conn:
            return total, per
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM g2b_state WHERE key LIKE %s",
                    (f"{KEY_PREFIX}{day}:%",))
        rows = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.warning(f"[사용량] 일 합계 조회 실패: {e}")
        return total, per
    for key, val in rows:
        try:
            a = val if isinstance(val, dict) else json.loads(val or "{}")
        except Exception:
            continue
        per[key.split(":", 2)[2]] = a
        for k in ("calls", "in", "out", "cw", "cr", "ws"):
            total[k] += int(a.get(k, 0) or 0)
        total["usd"] += float(a.get("usd", 0) or 0)
    return total, per


def daily_line(day: str | None = None) -> str:
    """하루 한 줄: '[API일계] 2026-11-24 호출 1,234회 · 입력 2.10M(캐시읽기 1.40M) · 출력 0.41M · 검색 128건 · $3.21 · 상위 …'"""
    day = day or datetime.now(KST).strftime("%Y-%m-%d")
    t, per = day_totals(day)
    top = sorted(per.items(), key=lambda kv: -float(kv[1].get("usd", 0) or 0))[:3]
    top_s = " / ".join(f"{k} ${float(v.get('usd', 0)):.2f}" for k, v in top)
    billed_in = t["in"] + t["cw"] + t["cr"]
    return (f"[API일계] {day} 호출 {t['calls']:,}회 · 입력 {billed_in/1e6:.2f}M"
            f"(캐시읽기 {t['cr']/1e6:.2f}M) · 출력 {t['out']/1e6:.2f}M · 검색 {t['ws']:,}건"
            f" · ${t['usd']:.2f} · 상위 {top_s or '-'}")
