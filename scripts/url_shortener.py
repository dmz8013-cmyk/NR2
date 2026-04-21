"""nr2.kr 자체 URL 단축 라이브러리.

호출자는 Flask app context가 활성화된 상태여야 한다.
- Flask request handler에선 자동
- 봇에선 `with app.app_context():` 래핑 필요

공개 함수:
- shorten_url(original_url, ...) → str
- resolve_code(code, request_meta=None) → str | None
- get_user_shorteners(user_id, limit, offset) → list[URLShortener]
- get_click_stats(code, days=7) → dict | None
"""
import logging
import re
import secrets
import string
from datetime import datetime, timedelta

import requests

from app import db
from app.models.url_shortener import URLShortener, URLClickLog
from app.utils.press_map import resolve_press_name, extract_domain

logger = logging.getLogger(__name__)

BASE_URL = 'https://nr2.kr'
CODE_ALPHABET = string.ascii_letters + string.digits  # base62
CODE_LEN = 6
CODE_RETRY = 5
OG_TIMEOUT = 5
OG_UA = 'NR2-Shortener/1.0 (+https://nr2.kr)'
CLICK_ABUSE_WINDOW_HOURS = 24

_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r'<title[^>]*>([^<]+)</title>', re.IGNORECASE)


def _generate_code(length=CODE_LEN):
    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(length))


def _extract_og_title(url):
    """OG title 우선, 없으면 <title>. 실패해도 예외 없이 None 반환."""
    try:
        resp = requests.get(
            url,
            timeout=OG_TIMEOUT,
            headers={'User-Agent': OG_UA},
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        html = resp.text[:50000]
        m = _OG_TITLE_RE.search(html)
        title = m.group(1).strip() if m else None
        if not title:
            m = _TITLE_RE.search(html)
            title = m.group(1).strip() if m else None
        if title and len(title) > 300:
            title = title[:297] + '...'
        return title
    except Exception as e:
        logger.info(f'[단축] OG 추출 실패 ({url[:60]}): {type(e).__name__}')
        return None


def shorten_url(original_url, source_bot=None, user_id=None,
                custom_code=None, expires_at=None):
    """원본 URL을 단축. 실패 시 원본 URL 반환 (fallback).

    - 로그인 사용자(user_id 있음): (user_id, original_url) 조합 중복 체크 후 재사용
    - 비로그인(user_id=None): 매번 새 코드 생성 (중복 체크 skip)
    - OG 추출은 실패 허용 (5초 타임아웃)
    """
    if not original_url or not isinstance(original_url, str):
        return original_url
    if not original_url.startswith(('http://', 'https://')):
        return original_url

    try:
        if user_id is not None:
            existing = URLShortener.query.filter_by(
                user_id=user_id,
                original_url=original_url,
            ).first()
            if existing:
                return f'{BASE_URL}/s/{existing.code}'

        if custom_code:
            if URLShortener.query.filter_by(code=custom_code).first():
                logger.info(f'[단축] custom_code 충돌: {custom_code}')
                return original_url
            code = custom_code
            is_custom = True
        else:
            code = None
            for _ in range(CODE_RETRY):
                candidate = _generate_code()
                if not URLShortener.query.filter_by(code=candidate).first():
                    code = candidate
                    break
            if not code:
                logger.warning('[단축] 랜덤 코드 재시도 5회 실패')
                return original_url
            is_custom = False

        title = _extract_og_title(original_url)
        domain = extract_domain(original_url)
        press_name = resolve_press_name(original_url)

        row = URLShortener(
            code=code,
            original_url=original_url,
            title=title,
            domain=domain,
            press_name=press_name,
            source_bot=source_bot,
            user_id=user_id,
            custom_code=is_custom,
            expires_at=expires_at,
        )
        db.session.add(row)
        db.session.commit()
        return f'{BASE_URL}/s/{code}'
    except Exception as e:
        db.session.rollback()
        logger.warning(f'[단축] DB 실패: {type(e).__name__}: {e}')
        return original_url


def resolve_code(code, request_meta=None):
    """code → original_url. 만료/미존재 시 None.

    클릭 로그는 항상 기록. 어뷰즈 방지:
    동일 ip_hash + shortener_id가 24시간 내 중복이면 click_count 증가만 skip.
    """
    if not code:
        return None
    try:
        row = URLShortener.query.filter_by(code=code).first()
        if not row:
            return None
        now = datetime.now()
        if row.expires_at and row.expires_at < now:
            return None

        ip_hash = (request_meta or {}).get('ip_hash')
        count_this_click = True
        if ip_hash:
            window_start = now - timedelta(hours=CLICK_ABUSE_WINDOW_HOURS)
            recent = URLClickLog.query.filter(
                URLClickLog.shortener_id == row.id,
                URLClickLog.ip_hash == ip_hash,
                URLClickLog.clicked_at >= window_start,
            ).first()
            if recent:
                count_this_click = False

        if request_meta:
            log = URLClickLog(
                shortener_id=row.id,
                user_agent=(request_meta.get('user_agent') or None),
                ip_hash=ip_hash,
                referer=(request_meta.get('referer') or None),
                device_type=(request_meta.get('device_type') or None),
            )
            db.session.add(log)

        if count_this_click:
            row.click_count = (row.click_count or 0) + 1
            row.last_clicked_at = now
            # NP 적립은 Phase 2-B에서 별도 커밋
            # if row.user_id:
            #     from app.models.user import User
            #     from app.models.np_point import award_np
            #     user = User.query.get(row.user_id)
            #     if user:
            #         award_np(user, 'shortener_click', description=f'/s/{code}')

        db.session.commit()
        return row.original_url
    except Exception as e:
        db.session.rollback()
        logger.warning(f'[단축] resolve 실패 ({code}): {type(e).__name__}: {e}')
        return None


def get_user_shorteners(user_id, limit=50, offset=0):
    """사용자 소유 단축 URL 조회 (최신순)."""
    if user_id is None:
        return []
    return (
        URLShortener.query
        .filter_by(user_id=user_id)
        .order_by(URLShortener.created_at.desc())
        .offset(offset).limit(limit)
        .all()
    )


def get_click_stats(code, days=7):
    """단축 URL 클릭 통계 — 일별·시간별·디바이스별."""
    row = URLShortener.query.filter_by(code=code).first()
    if not row:
        return None
    since = datetime.now() - timedelta(days=days)
    logs = (
        URLClickLog.query
        .filter(
            URLClickLog.shortener_id == row.id,
            URLClickLog.clicked_at >= since,
        )
        .all()
    )

    daily = {}
    hourly = {h: 0 for h in range(24)}
    device = {'mobile': 0, 'desktop': 0, 'tablet': 0}
    for log in logs:
        d = log.clicked_at.strftime('%Y-%m-%d')
        daily[d] = daily.get(d, 0) + 1
        hourly[log.clicked_at.hour] = hourly.get(log.clicked_at.hour, 0) + 1
        dev = (log.device_type or 'desktop')
        if dev in device:
            device[dev] += 1

    return {
        'code': code,
        'original_url': row.original_url,
        'title': row.title,
        'press_name': row.press_name,
        'total_clicks': row.click_count,
        'daily': daily,
        'hourly': hourly,
        'device': device,
    }
