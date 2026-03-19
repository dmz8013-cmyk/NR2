"""
timeline_filter.py — 브리핑 기사 타임라인 필터

브리핑에 포함될 기사가 커버리지 윈도우 내에 있는지 엄격하게 검증.
발행일 없는 기사, 오래된 기사를 걸러내서 구식 뉴스 혼입을 방지.

사용:
  from timeline_filter import filter_articles, is_within_window
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger("timeline_filter")

KST = ZoneInfo("Asia/Seoul")

# ── 브리핑별 커버리지 윈도우 ──
# max_age_hours: 기사가 아무리 늦어도 이 시간 이내여야 포함
COVERAGE_WINDOWS = {
    "ai_morning": {
        "description": "아침 AI 브리핑 (06:00)",
        "max_age_hours": 14,        # 전날 18:00 ~ 당일 06:00 = 12h + 여유 2h
    },
    "ai_evening": {
        "description": "저녁 AI 브리핑 (18:00)",
        "max_age_hours": 14,        # 당일 06:00 ~ 18:00 = 12h + 여유 2h
    },
    "political_afternoon": {
        "description": "정치 오후 브리핑 (13:00)",
        "max_age_hours": 6,         # 당일 09:00 ~ 13:00 = 4h + 여유 2h
    },
    "political_evening": {
        "description": "정치 저녁 브리핑 (22:00)",
        "max_age_hours": 11,        # 당일 13:00 ~ 22:00 = 9h + 여유 2h
    },
}

# 절대 상한: 어떤 브리핑이든 이보다 오래된 기사는 무조건 제외
MAX_STALENESS_HOURS = 48


def is_within_window(
    pub_date: datetime | None,
    window_start: datetime,
    window_end: datetime,
    max_staleness_hours: int = MAX_STALENESS_HOURS,
) -> tuple[bool, str]:
    """
    기사 발행일이 윈도우 내에 있는지 검증.

    Returns:
        (통과 여부, 사유 문자열)
    """
    now = datetime.now(KST)

    # 1) 발행일 없는 기사 → 거부
    if pub_date is None:
        return False, "발행일 없음 (pub_date=None)"

    # 2) 절대 상한 초과 → 거부
    age = now - pub_date
    if age > timedelta(hours=max_staleness_hours):
        hours_old = age.total_seconds() / 3600
        return False, f"절대 상한 초과 ({hours_old:.0f}시간 경과, 상한={max_staleness_hours}h)"

    # 3) 커버리지 윈도우 체크 (여유분 2시간)
    margin = timedelta(hours=2)
    if pub_date < (window_start - margin):
        return False, f"윈도우 이전 ({pub_date.strftime('%m/%d %H:%M')} < {window_start.strftime('%m/%d %H:%M')})"

    if pub_date > (window_end + margin):
        return False, f"윈도우 이후 ({pub_date.strftime('%m/%d %H:%M')} > {window_end.strftime('%m/%d %H:%M')})"

    return True, "OK"


def filter_articles(
    articles: list[dict],
    window_start: datetime,
    window_end: datetime,
    briefing_type: str = "ai_morning",
) -> list[dict]:
    """
    기사 목록에서 타임라인 윈도우를 벗어난 기사를 제거.

    Args:
        articles: [{"title": str, "published": str|None, "link": str, ...}, ...]
        window_start: 커버리지 시작 시각 (KST)
        window_end: 커버리지 종료 시각 (KST)
        briefing_type: COVERAGE_WINDOWS 키

    Returns:
        필터링된 기사 목록
    """
    config = COVERAGE_WINDOWS.get(briefing_type, {})
    max_age = config.get("max_age_hours", MAX_STALENESS_HOURS)

    passed = []
    rejected = 0

    for article in articles:
        # published 필드 → datetime 변환
        pub_date = _parse_iso_date(article.get("published"))

        ok, reason = is_within_window(pub_date, window_start, window_end, max_age)

        if ok:
            passed.append(article)
        else:
            rejected += 1
            title = article.get("title", "")[:40]
            logger.info(f"[타임라인 필터] 제외: '{title}...' — {reason}")

    if rejected > 0:
        logger.warning(
            f"[타임라인 필터] {len(articles)}건 중 {rejected}건 제외, {len(passed)}건 통과"
        )

    return passed


def filter_naver_articles(
    articles: list[dict],
    window_start: datetime,
    window_end: datetime,
    briefing_type: str = "political_afternoon",
) -> list[dict]:
    """
    네이버 API 기사 목록 필터 (political_briefing.py용).
    article["pub_date"]가 datetime 객체인 경우.
    """
    config = COVERAGE_WINDOWS.get(briefing_type, {})
    max_age = config.get("max_age_hours", MAX_STALENESS_HOURS)

    passed = []
    rejected = 0

    for article in articles:
        pub_date = article.get("pub_date")

        ok, reason = is_within_window(pub_date, window_start, window_end, max_age)

        if ok:
            passed.append(article)
        else:
            rejected += 1
            title = article.get("title", "")[:40]
            logger.info(f"[타임라인 필터] 제외: '{title}...' — {reason}")

    if rejected > 0:
        logger.warning(
            f"[타임라인 필터] {len(articles)}건 중 {rejected}건 제외, {len(passed)}건 통과"
        )

    return passed


def _parse_iso_date(value) -> datetime | None:
    """ISO 8601 문자열 또는 datetime을 KST datetime으로 변환."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=KST)
        return value.astimezone(KST)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt.astimezone(KST)
        except (ValueError, TypeError):
            return None
    return None
