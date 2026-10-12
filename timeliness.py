"""timeliness.py — 수집 단계 시의성 필터 (전 브리핑 파이프라인 공통).

규칙: 기사 발행시각을 KST 로 변환해 날짜가 {오늘, 전일} 집합에 없으면 제외 (실행 시각 무관).
발행시각 소스 우선순위:
  1) RSS / 네이버 API pubDate (article['pub_date'|'published'|'pubDate'])
  2) 없으면 기사 HTML 의 article:published_time / og:published_time / og:updated_time /
     JSON-LD datePublished 메타 (타임아웃 3초, 회당 최대 30건 보조 조회)
  3) 그래도 없으면 제외 (허용 아님)
어떤 실패도 수집을 멈추지 않는다 — 해석 불가 기사는 '제외' 로 분류될 뿐이다.
"""
import os
import re
import json
import logging
from datetime import datetime, date, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

logger = logging.getLogger("timeliness")
KST = ZoneInfo("Asia/Seoul")

HTML_TIMEOUT = 3.0
HTML_BUDGET = 30
MAX_AGE_HOURS = int(os.environ.get("TIMELINESS_MAX_AGE_HOURS", "24"))   # 발행 24h 초과는 날짜와 무관하게 제외
_META_RES = [
    re.compile(r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']', re.I),
    re.compile(r'<meta[^>]+property=["\']og:published_time["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"', re.I),
    re.compile(r'<meta[^>]+property=["\']og:updated_time["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:updated_time["\']', re.I),
]


def allowed_dates(now: datetime | None = None) -> set[date]:
    now = now.astimezone(KST) if now else datetime.now(KST)
    return {now.date(), (now - timedelta(days=1)).date()}


def to_kst(value) -> datetime | None:
    """datetime / ISO8601 / RFC2822 문자열 → tz-aware KST datetime. 실패 시 None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        dt = None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            try:
                dt = parsedate_to_datetime(s)
            except Exception:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)        # naive 는 KST 로 간주
    return dt.astimezone(KST)


def article_pub_date(article: dict) -> datetime | None:
    for key in ("pub_date", "published", "pubDate", "pub_date_resolved"):
        dt = to_kst(article.get(key))
        if dt:
            return dt
    return None


def source_of(article: dict) -> str:
    src = (article.get("source") or article.get("press") or "").strip()
    if src:
        return src
    title = article.get("title") or ""
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()[:20]
    link = article.get("link") or article.get("url") or ""
    try:
        host = urlparse(link).netloc
        return host.replace("www.", "")[:30] if host else "미상"
    except Exception:
        return "미상"


def fetch_html_pub_date(url: str, timeout: float = HTML_TIMEOUT) -> datetime | None:
    """기사 HTML 앞부분(≤200KB)에서 발행시각 메타 추출. 실패 시 None."""
    if not url or not url.startswith("http"):
        return None
    try:
        import requests
        r = requests.get(url, timeout=timeout, stream=True,
                         headers={"User-Agent": "Mozilla/5.0 (NR2 timeliness)"})
        chunks, size = [], 0
        for ch in r.iter_content(8192):
            chunks.append(ch); size += len(ch)
            if size > 200_000:
                break
        r.close()
        html = b"".join(chunks).decode(r.encoding or "utf-8", errors="ignore")
    except Exception as e:
        logger.info(f"[시의성] HTML 조회 실패 {url[:60]}: {e}")
        return None
    for rx in _META_RES:
        m = rx.search(html)
        if m:
            dt = to_kst(m.group(1))
            if dt:
                return dt
    return None


def filter_timely(articles: list[dict], now: datetime | None = None,
                  html_budget: int = HTML_BUDGET, allow_html: bool = True,
                  fetcher=fetch_html_pub_date, cross_check: bool = False) -> tuple[list[dict], list[dict]]:
    """→ (통과 목록, 제외 목록). 통과 기사에는 pub_date_kst(ISO)·pub_label 이 채워진다.

    cross_check=True: pubDate 가 있어도 같은 보조 조회 예산 안에서 HTML 메타를 대조해, 메타 발행일이
    전일 이전이면 메타를 신뢰해 제외한다(네이버 API 재색인 pubDate 가 '오늘' 로 찍히는 경우 대응).
    제외 항목: {title, source, pub_date(ISO|None), reason}"""
    allowed = allowed_dates(now)
    now_kst = now.astimezone(KST) if now else datetime.now(KST)
    max_age_hours = MAX_AGE_HOURS
    passed, excluded = [], []
    lenient: list[dict] = []
    budget = html_budget if allow_html else 0
    for a in articles:
        dt = article_pub_date(a)
        link = a.get("link") or a.get("url")
        if dt is None and budget > 0 and link:
            budget -= 1
            dt = fetcher(link)
            if dt:
                a["pub_date_resolved"] = dt.isoformat()
                if not a.get("published") and not a.get("pub_date"):
                    a["published"] = dt.isoformat()
        elif dt is not None and cross_check and budget > 0 and link:
            budget -= 1
            meta = fetcher(link)
            if meta and meta.date() not in allowed and (dt - meta) > timedelta(days=1):
                excluded.append({"title": a.get("title", ""), "source": source_of(a),
                                 "pub_date": meta.isoformat(), "reason": f"HTML 메타 발행일 {meta:%m/%d} (API pubDate {dt:%m/%d} 재색인 의심)"})
                continue
        if dt is None:
            if not strict_mode():
                # TIMELINESS_STRICT=0: 제외 대신 통과 + 표기 (롤백 없이 완화하는 스위치)
                a["timeliness_lenient"] = True
                a["pub_label"] = "발행시각 없음"
                lenient.append({"title": a.get("title", ""), "source": source_of(a), "pub_date": None,
                                "reason": "발행시각 없음 — TIMELINESS_STRICT=0 통과"})
                passed.append(a)
                continue
            excluded.append({"title": a.get("title", ""), "source": source_of(a),
                             "pub_date": None, "reason": "발행시각 없음"})
            continue
        if dt.date() not in allowed:
            excluded.append({"title": a.get("title", ""), "source": source_of(a),
                             "pub_date": dt.isoformat(), "reason": f"발행일 {dt:%m/%d} — 전일 이전"})
            continue
        if (now_kst - dt).total_seconds() > max_age_hours * 3600:
            excluded.append({"title": a.get("title", ""), "source": source_of(a),
                             "pub_date": dt.isoformat(), "reason": f"발행 {int((now_kst - dt).total_seconds() // 3600)}시간 경과 — {max_age_hours}h 초과"})
            continue
        a["pub_date_kst"] = dt.isoformat()
        a["pub_label"] = dt.strftime("%m/%d %H:%M")
        passed.append(a)
    logger.info(f"[시의성] 입력 {len(articles)}건 → 통과 {len(passed)} · 제외 {len(excluded)} · 완화 {len(lenient)} "
                f"(허용 {sorted(d.isoformat() for d in allowed)}, 보조 조회 잔여 {budget})")
    if excluded:
        logger.warning(f"[시의성] {len(articles)}건 중 {len(excluded)}건 제외 (허용 {sorted(allowed)})")
    if lenient:
        logger.warning(f"[시의성] 발행시각 없음 {len(lenient)}건 통과 (TIMELINESS_STRICT=0)")
    global LAST_LENIENT
    LAST_LENIENT = lenient
    return passed, excluded


LAST_LENIENT: list[dict] = []     # 직전 filter_timely 에서 완화 통과한 항목 (회차 DM 표기용)


def strict_mode() -> bool:
    """TIMELINESS_STRICT (기본 1). 0/false/no 면 완화 모드."""
    return str(os.environ.get("TIMELINESS_STRICT", "1")).strip().lower() not in ("0", "false", "no", "off")


def format_lenient(lenient: list[dict], max_examples: int = 3) -> str:
    if not lenient:
        return ""
    ex = " / ".join(f"{e.get('source', '')} · {(e.get('title') or '')[:28]}" for e in lenient[:max_examples])
    return f"⚠️ 발행시각 없음 통과 {len(lenient)}건 (TIMELINESS_STRICT=0): {ex}"


def format_exclusions(excluded: list[dict], max_examples: int = 3) -> str:
    """관리자 DM 한 줄: '시의성 제외 N건: 매체 · 제목 · 발행일; …'"""
    if not excluded:
        return "시의성 제외 0건"
    ex = []
    for e in excluded[:max_examples]:
        d = e.get("pub_date")
        d = to_kst(d).strftime("%m/%d") if d else "발행일 없음"
        ex.append(f"{e.get('source', '')} · {(e.get('title') or '')[:28]} · {d}")
    return f"시의성 제외 {len(excluded)}건: " + " / ".join(ex)
