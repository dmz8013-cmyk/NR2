"""src_age_guard.py — 결속 기사 시각·항목 내 사건 날짜 검사 (2026-11-02).

B-1 (지시대로) 결속 기사 게시시각이 브리핑 시각 기준 MAX_SRC_AGE_H(36h)를 넘으면
    항목 제외. 단 그 기사가 **후속 보도**면(제목에 후속/추가/파장/반박 등) 예외.

B-2 (실효) 11/2 적발 사례 — '김준혁 10/7 국감 자료'는 B-1 으로 잡히지 않는다.
    결속 기사 자체는 11/1~2 발행이고, 낡은 것은 **항목이 말하는 사건의 날짜**다.
    그래서 항목 본문의 날짜 표기(10월 7일 / 10.7 / 10/7)를 읽어 MAX_EVENT_AGE_DAYS
    (7일)보다 오래된 과거 사건이면 제외한다. 미래 날짜·후속 보도는 예외.

    한계: 항목에 날짜가 없으면(‘국감에서 받은 자료’) 이 가드로는 못 잡는다.
    그 유형은 수집 단계의 사건나이 메타가 있어야 한다(미구현).

어떤 실패도 발행을 막지 않는다 — 판정 불가면 None(통과).
"""
import os
import re
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger("src_age_guard")
KST = ZoneInfo("Asia/Seoul")

MAX_SRC_AGE_H = int(os.environ.get("SRC_MAX_AGE_H", "36"))
MAX_EVENT_AGE_DAYS = int(os.environ.get("EVENT_MAX_AGE_DAYS", "7"))

FOLLOWUP_RE = re.compile(r"(후속|추가\s*보도|파장|반박|해명|재반박|속보|단독|후폭풍|"
                         r"잇따라|재확인|다시|번복|철회)")
# 날짜 **직후**에 붙는 미래 단서만. '추진·전망'처럼 날짜와 무관한 말을 넣으면
# 뒤쪽 단어 하나로 낡은 날짜가 전부 면제된다(11/2 검증에서 확인).
FUTURE_RE = re.compile(r"(예정|개막|열린다|열릴|개최|앞두고|부터\s*시행|로\s*예고)")
_DATE_RES = (re.compile(r"(?<![\d.])(\d{1,2})월\s*(\d{1,2})일"),
             re.compile(r"(?<![\d./])(\d{1,2})/(\d{1,2})(?![\d/])"),
             re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})(?![\d.])"))


def src_age_hours(art: dict, now: datetime | None = None) -> float | None:
    """결속 기사 게시 후 경과 시간. 판정 불가면 None."""
    try:
        from source_bind import _pub
        dt = _pub(art or {})
    except Exception:
        return None
    if dt is None:
        return None
    return ((now or datetime.now(KST)) - dt).total_seconds() / 3600


def event_dates(body: str, now: datetime | None = None) -> list[tuple[datetime, int]]:
    """항목 본문에서 읽어낸 사건 날짜 → (날짜, 본문 위치). 연도는 과거 기준으로 보정."""
    now = now or datetime.now(KST)
    out = []
    for rx in _DATE_RES:
        for m in rx.finditer(body or ""):
            mo, d = int(m.group(1)), int(m.group(2))
            if not (1 <= mo <= 12 and 1 <= d <= 31):
                continue
            # 연도 보정은 **오늘에서 가장 가까운 쪽**으로 한다. '작년으로 돌린다'
            # 식의 단순 규칙은 11/2 검증에서 '12월 2일 법정 시한'(한 달 뒤)을
            # 작년 12월로 읽어 335일 경과로 지웠다.
            cands = []
            for year in (now.year - 1, now.year, now.year + 1):
                try:
                    cands.append(datetime(year, mo, d, tzinfo=KST))
                except ValueError:
                    continue
            if cands:
                out.append((min(cands, key=lambda x: abs((x - now).total_seconds())), m.start()))
    return out


def check(body: str, art: dict, now: datetime | None = None) -> str | None:
    """→ 제외 사유 또는 None(통과)."""
    now = now or datetime.now(KST)
    title = (art or {}).get("title") or ""
    followup = bool(FOLLOWUP_RE.search(title) or FOLLOWUP_RE.search(body or ""))

    age = src_age_hours(art, now)
    if age is not None and age > MAX_SRC_AGE_H and not followup:
        return f"B 결속 기사 {age:.0f}h 경과(상한 {MAX_SRC_AGE_H}h)"

    if followup:
        return None
    for dt, at in event_dates(body, now):
        days = (now - dt).days
        if days <= MAX_EVENT_AGE_DAYS:
            continue                       # 미래 날짜는 days 가 음수라 여기서 걸러진다
        # ‘11월 20일 개막 예정’처럼 미래 일정을 과거로 오인한 경우 제외.
        # 미래 단서는 날짜 주변에서만 본다 — 본문 전체로 보면 뒤쪽의 '추진' 하나에
        # 낡은 날짜가 전부 면제된다.
        if FUTURE_RE.search((body or "")[at:at + 22]):
            continue
        return f"B 사건 날짜 {dt.strftime('%m/%d')} — {days}일 경과(상한 {MAX_EVENT_AGE_DAYS}일)"
    return None
