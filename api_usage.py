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

# $/MTok (input, output). 캐시 쓰기 1.25x·읽기 0.1x 는 입력가 기준.
PRICES = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10


def _fields(usage) -> dict:
    g = (lambda n: int(getattr(usage, n, 0) or 0))
    return {"in": g("input_tokens"), "out": g("output_tokens"),
            "cw": g("cache_creation_input_tokens"), "cr": g("cache_read_input_tokens")}


def cost_usd(model: str, f: dict) -> float:
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return ((f["in"] + f["cw"] * CACHE_WRITE_MULT + f["cr"] * CACHE_READ_MULT) * pin
            + f["out"] * pout) / 1e6


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
        for k in ("in", "out", "cw", "cr"):
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
