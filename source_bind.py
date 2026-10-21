"""source_bind.py — 항목 ↔ 원문 결속 (2026-10-21 결함1·2).

브리핑의 ▪ 항목마다 수집 풀에서 근거 기사를 찾아 **원문 URL·게시시각을 내부 메타로
보존**하고, 근거를 못 찾거나 근거가 24h 밖이면 출력에서 제외한다.

왜 필요한가 — 기존 `section_fill.source_match_guard` 는 파이프라인에서 LLM 생성
단계(enforce_breaking / fill_empty_sections / enforce_rebuttal)보다 **앞에서** 한 번만
돌았다. 그 뒤에 생성된 항목은 출처 매칭도, 원문 대조도, 시의성 검사도 받지 않고
그대로 발행됐다(10/21 13:00판 16건 중 6건 출처 불명, 8월 기사 1건).

이 모듈은 생성 단계가 **전부 끝난 뒤** 마지막 관문으로 호출한다.
어떤 실패도 발행을 막지 않는다 — 판정 불가면 보수적으로 원문을 유지하되,
근거를 찾지 못한 항목은 제외한다(루머 유통 방지가 우선).
"""
import re
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("source_bind")
KST = ZoneInfo("Asia/Seoul")

MIN_OVERLAP = 2          # 항목 ↔ 기사 제목+본문 핵심어 겹침 최소 개수
MAX_AGE_HOURS = 24       # 근거 기사 발행 후 경과 상한
NO_NEWS = "금일 주요 보도 없음"

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_STOP = {"있음", "없음", "했음", "밝힘", "대한", "관련", "이번", "지난", "오늘", "전날",
         "대해", "위해", "통해", "따라", "등을", "등이", "것으로", "가운데"}


# 조사·어미 — 한국어는 '장외집회'와 '장외집회를'이 다른 토큰이 돼 겹침이 0으로 나온다.
# 토큰과 어간을 함께 넣어 비교한다(어간만 쓰면 2자 명사가 과도하게 뭉친다).
_PARTICLES = ("에서는", "에게서", "으로써", "이라고", "에서", "으로", "에게", "라고", "보다",
              "처럼", "까지", "부터", "마다", "조차", "라며", "이나", "하고", "에는", "과의",
              "와의", "들이", "들을", "은", "는", "이", "가", "을", "를", "의", "에", "도",
              "만", "와", "과", "로", "서", "께")
_ENDINGS = ("했다고", "한다고", "했음", "했다", "한다", "됐다", "됐음", "이다", "있다", "였다",
            "하며", "하고", "함", "됨", "임")


def _stem(w: str) -> str:
    for suf in _PARTICLES + _ENDINGS:
        if len(w) > len(suf) + 1 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokens(t: str) -> set[str]:
    """토큰 + 어간 집합. 한국어 조사·어미 때문에 표면형만으로는 겹침이 0이 된다.
    grounding 등 다른 가드도 이 구현 하나를 쓴다(2026-10-21)."""
    out = set()
    for w in _TOKEN_RE.findall(t or ""):
        if w in _STOP:
            continue
        out.add(w)
        st = _stem(w)
        if len(st) >= 2:
            out.add(st)
    return out


_toks = tokens          # 내부 호출 호환


def _article_text(a: dict) -> str:
    return f"{a.get('title', '')} {a.get('description') or ''}"


def _pub(a: dict):
    from timeliness import to_kst
    return to_kst(a.get("pub_date_kst") or a.get("pub_date_resolved")
                  or a.get("pub_date") or a.get("published"))


def best_match(body: str, articles: list[dict]) -> tuple[dict | None, int]:
    """항목과 핵심어가 가장 많이 겹치는 기사. → (기사, 겹침 수)."""
    bt = _toks(body)
    best, score = None, 0
    for a in articles or []:
        n = len(bt & _toks(_article_text(a)))
        if n > score:
            best, score = a, n
    return best, score


def bind(briefing: str, articles: list[dict], now: datetime | None = None
         ) -> tuple[str, list[dict], list[str]]:
    """→ (텍스트, 결속 메타 목록, 제외 사유 목록).

    메타 1건 = {body, url, source, pub, age_h, overlap} — 회차 DM·감사 추적용.
    """
    now = now or datetime.now(KST)
    lines = briefing.split("\n")
    bound: list[dict] = []
    dropped: list[str] = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("▪") or NO_NEWS in s:
            continue
        body = s.lstrip("▪").strip()
        art, ov = best_match(body, articles)
        if art is None or ov < MIN_OVERLAP:
            lines[i] = None
            dropped.append(f"근거 없음(겹침 {ov}): {body[:60]}")
            continue
        url = art.get("link") or art.get("url") or ""
        if not url:
            lines[i] = None
            dropped.append(f"원문 URL 없음: {body[:60]}")
            continue
        dt = _pub(art)
        if dt is None:
            lines[i] = None
            dropped.append(f"게시시각 불명: {body[:60]}")
            continue
        age = (now - dt).total_seconds() / 3600
        if age > MAX_AGE_HOURS:
            lines[i] = None
            dropped.append(f"근거 {age:.0f}h 경과(상한 {MAX_AGE_HOURS}h): {body[:60]}")
            continue
        bound.append({"body": body, "url": url, "source": art.get("query") or art.get("source") or "",
                      "pub": dt.strftime("%m/%d %H:%M"), "age_h": round(age, 1), "overlap": ov})
    if dropped:
        logger.warning(f"[출처결속] 제외 {len(dropped)}건: {dropped[:5]}")
    logger.info(f"[출처결속] 결속 {len(bound)}건 · 제외 {len(dropped)}건")
    return "\n".join(l for l in lines if l is not None), bound, dropped


def format_bound(bound: list[dict], limit: int = 20) -> list[str]:
    """회차 DM 용 — 항목별 원문 URL·게시시각 한 줄씩."""
    return [f"{b['body'][:44]} ← {b['pub']}({b['age_h']}h) {b['url'][:70]}"
            for b in bound[:limit]]
