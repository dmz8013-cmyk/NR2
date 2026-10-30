"""briefing_dedup.py — 섹션 간·섹션 내 중복 병합 (2026-10-30 E).

1차: 결속 URL 이 같고 어간 겹침이 임계 이상 → 같은 사건
2차: 같은 섹션 안에서 rapidfuzz token_set_ratio >= 임계 → 같은 사건
병합된 항목은 src 를 2개 유지한다(같은 사건이므로 1:1 규칙의 예외).
상대 당 반박 항목은 예외로 남긴다.

어떤 실패도 발행을 막지 않는다 — 판정 불가면 원문 유지.
"""
import os
import json
import logging

logger = logging.getLogger("briefing_dedup")
_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_HERE, "config", "briefing_dedup.json")
_CFG = None
STANCE = ("비판", "반박", "규탄", "반발", "지적", "겨냥", "촉구", "질타")


def config() -> dict:
    global _CFG
    if _CFG is None:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                _CFG = json.load(f)
        except Exception as e:
            logger.warning(f"[병합] 설정 로드 실패 — 기본값: {e}")
            _CFG = {"url_match_min_overlap": 4, "token_set_ratio": 85, "rebuttal_exempt": True}
    return _CFG


def ratio(a: str, b: str) -> float:
    """token_set_ratio. rapidfuzz 없으면 difflib 로 근사 (scrap_dedup 과 같은 폴백 방침)."""
    try:
        from rapidfuzz import fuzz
        return float(fuzz.token_set_ratio(a, b))
    except ImportError:
        import difflib
        return difflib.SequenceMatcher(None, a, b).ratio() * 100


def _toks(t: str) -> set:
    try:
        from source_bind import tokens
        return tokens(t)
    except Exception:
        return set((t or "").split())


def _is_rebuttal(a: str, b: str) -> bool:
    """서로 다른 주체의 반박 쌍이면 병합하지 않는다."""
    if not config().get("rebuttal_exempt", True):
        return False
    return any(w in a for w in STANCE) and any(w in b for w in STANCE)


def dedup(briefing: str, bound: list[dict]) -> tuple[str, list[str]]:
    """→ (텍스트, 메모). bound 는 source_bind.bind 의 결속 메타."""
    cfg = config()
    by_body = {b["body"]: b for b in (bound or [])}
    lines = briefing.split("\n")
    try:
        from briefing_layout import SECTION_HEADER_RE
    except Exception:
        import re
        SECTION_HEADER_RE = re.compile(r'^(🏛️|💰|🤖|🎯|📌|🇰🇷|🟦|🟥|🎸|🌐)')

    items, cur = [], None          # (줄번호, 본문, 섹션, url)
    for i, ln in enumerate(lines):
        s = (ln or "").strip()
        if SECTION_HEADER_RE.match(s):
            cur = s
            continue
        if not s.startswith("▪") or "보도 없음" in s or "이슈 없음" in s:
            continue
        body = s.lstrip("▪").strip()
        items.append((i, body, cur, (by_body.get(body) or {}).get("url")))

    notes, dropped = [], set()
    for x in range(len(items)):
        if x in dropped:
            continue
        ix, bx, sx, ux = items[x]
        for y in range(x + 1, len(items)):
            if y in dropped:
                continue
            iy, by, sy, uy = items[y]
            if _is_rebuttal(bx, by):
                continue
            same = False
            if ux and uy and ux == uy:
                if len(_toks(bx) & _toks(by)) >= cfg["url_match_min_overlap"]:
                    same, why = True, "URL 일치"
            if not same and sx == sy and ratio(bx, by) >= cfg["token_set_ratio"]:
                same, why = True, f"유사도 {ratio(bx, by):.0f}%"
            if same:
                dropped.add(y)
                notes.append(f"{why}: '{by[:38]}' → '{bx[:38]}' 로 병합")
    for y in sorted(dropped, reverse=True):
        lines[items[y][0]] = None
    if notes:
        logger.warning(f"[병합] {len(notes)}건: {notes[:3]}")
    return "\n".join(l for l in lines if l is not None), notes
