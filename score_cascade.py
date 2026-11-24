"""score_cascade.py — 채점 2단 캐스케이드 (2026-11-24).

1차 Haiku 5.5 로 채점하고, 점수가 경계 구간(기본 5~8점)이거나 JSON 을 못 읽으면
같은 프롬프트로 Sonnet 5.5 가 다시 채점한다. 경계 밖(0~4, 9~10)은 Haiku 결과를 쓴다.

근거(10/21 측정, project memory): Haiku 5.5 단독은 AESA 7점 컷 교차 17.8%로 부적합,
[5~8] 구간 재채점 시 잔여 누락 0.5%·월 약 $36 절감.

환경변수
  SCORE_CASCADE_ENABLED  (기본 true)  false 면 Sonnet 단독(기존 동작)
  SCORE_CASCADE_BAND     (기본 "5-8") Sonnet 재채점 구간(양끝 포함)
  SCORE_FAST_MODEL       (기본 claude-haiku-5-5)
"""
import logging
import os

logger = logging.getLogger("score_cascade")

FAST_MODEL = os.environ.get("SCORE_FAST_MODEL", "claude-haiku-5-5")
STRONG_MODEL = "claude-sonnet-5-5"


def enabled() -> bool:
    return os.environ.get("SCORE_CASCADE_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def band() -> tuple[int, int]:
    try:
        lo, hi = os.environ.get("SCORE_CASCADE_BAND", "5-8").split("-")
        return int(lo), int(hi)
    except Exception:
        return 5, 8


def _thinking_off(model: str) -> dict:
    # Sonnet 5.5: "disabled" 는 400 → between_tools. Haiku 5.5: disabled 허용(effort high 이하, 기본 medium).
    return {"type": "between_tools"} if model.startswith("claude-sonnet-5") else {"type": "disabled"}


def score(client, *, content: list, parse, max_tokens: int, system: str | None = None,
          stats: dict | None = None):
    """→ (response, model, parsed). parse(response) 는 점수(int) 를 담은 결과 또는 None.

    parsed 는 parse() 반환값 그대로. 점수는 parse 결과의 ["score"] 로 읽는다.
    """
    def call(model):
        kw = {"system": system} if system else {}
        return client.messages.create(model=model, max_tokens=max_tokens,
                                      thinking=_thinking_off(model),
                                      messages=[{"role": "user", "content": content}], **kw)

    if enabled():
        try:
            r1 = call(FAST_MODEL)
        except Exception as e:
            # Haiku 호출 자체가 실패(모델·파라미터 400, 일시 장애)해도 점수는 잃지 않는다 → Sonnet.
            logger.warning(f"[캐스케이드] {FAST_MODEL} 호출 실패 → {STRONG_MODEL} 로 채점: {str(e)[:160]}")
            if stats is not None:
                stats["fast_error"] = stats.get("fast_error", 0) + 1
            r1 = None
        p1 = None
        try:
            p1 = parse(r1) if r1 is not None else None
        except Exception:
            p1 = None
        s1 = None
        try:
            s1 = int(p1["score"]) if p1 is not None else None
        except Exception:
            s1 = None
        lo, hi = band()
        if s1 is not None and not (lo <= s1 <= hi) and r1.stop_reason != "max_tokens":
            if stats is not None:
                stats["fast_only"] = stats.get("fast_only", 0) + 1
            return r1, FAST_MODEL, p1
        if stats is not None:
            stats["escalated"] = stats.get("escalated", 0) + 1
        logger.debug(f"[캐스케이드] Haiku 점수 {s1} → Sonnet 재채점")
    r2 = call(STRONG_MODEL)
    try:
        p2 = parse(r2)
    except Exception:
        p2 = None
    return r2, STRONG_MODEL, p2
