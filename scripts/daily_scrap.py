"""
scripts/daily_scrap.py
─────────────────────
네이버 뉴스 검색 API로 [단독]/(단독) 기사를 수집해 텔레그램으로 전송한다.

실행 방식:
  python scripts/daily_scrap.py          # 직접 실행 (판 자동 감지)
  python scripts/daily_scrap.py morning  # 오전판 강제
  python scripts/daily_scrap.py afternoon # 오후판 강제

필요 환경 변수:
  NAVER_CLIENT_ID      – 네이버 검색 API client_id
  NAVER_CLIENT_SECRET  – 네이버 검색 API client_secret
  SCRAP_BOT_TOKEN      – 텔레그램 봇 토큰
  SCRAP_CHAT_ID        – 수신 chat_id (개인 봇)
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import urllib.error
import difflib
import logging
from datetime import datetime, timedelta, timezone

# ── 로거 ─────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger('daily_scrap')

# ── 상수 ─────────────────────────────────────────────────────────────────────
KST = timezone(timedelta(hours=9))
NAVER_SEARCH_URL = 'https://openapi.naver.com/v1/search/news.json'
TINYURL_API      = 'https://tinyurl.com/api-create.php?url='
TELEGRAM_API     = 'https://api.telegram.org/bot{token}/sendMessage'

# 오전판 기준: 현재 시각이 12시 이전이면 오전판
MORNING_CUTOFF_HOUR = 12
# 오전판 수집 범위: 전날 오후 16:00 이후 ~ 오늘 07:30
# 오후판 수집 범위: 오늘 07:00 이후 ~ 오늘 16:30
MORNING_LOOKBACK_HOURS = 16   # 07:30 기준 약 16h 전(전날 15:30)부터 수집
AFTERNOON_LOOKBACK_HOURS = 10  # 16:30 기준 약 10h 전(06:30)부터 수집

MAX_RESULTS_PER_QUERY = 30    # 네이버 API 1회 최대 100, 중복 감안해 30
DEDUP_THRESHOLD       = 0.70  # 제목 유사도 70% 이상이면 중복
MAX_PER_SECTION       = 5     # 섹션당 최대 기사 수

# ── 섹션 분류 키워드 (우선순위 순) ────────────────────────────────────────────
SECTIONS = {
    '🏛️ 정치':    ['대통령', '국회', '여당', '야당', '정부', '총리', '장관', '의원', '선거',
                    '국정', '민주당', '국민의힘', '정당', '청와대', '탄핵', '국무회의'],
    '💰 경제':    ['경제', '주식', '환율', '금리', '부동산', '증시', '코스피', '코스닥',
                    '기업', '재벌', '물가', '수출', '무역', '한국은행', '금융', '투자',
                    '예산', '세금', '취업', '고용'],
    '🌐 국제':    ['미국', '중국', '일본', '러시아', '북한', '유럽', '외교', '트럼프',
                    '바이든', '시진핑', '푸틴', '나토', '유엔', 'UN', '정상회담', '제재'],
    '📱 IT·과학': ['AI', '인공지능', '삼성', 'LG', 'SK', '현대', '카카오', '네이버',
                    '스타트업', '반도체', '우주', '과학', '기술', '앱', '플랫폼', '데이터'],
    '🎭 사회':    ['사건', '사고', '범죄', '법원', '검찰', '경찰', '재판', '의료', '교육',
                    '복지', '환경', '인권', '노동', '파업', '시위', '화재', '사망'],
    '🎬 문화·연예': ['문화', '영화', '드라마', '연예', '배우', '가수', '아이돌', 'K-팝',
                      '방탄소년단', '음악', '공연', '전시', '스포츠', '야구', '축구', '올림픽'],
    '🗂️ 기타':    [],  # 위 섹션에 해당 없는 기사
}


# ────────────────────────────────────────────────────────────────────────────
# 헬퍼 함수
# ────────────────────────────────────────────────────────────────────────────

def _get_env(key: str) -> str:
    val = os.environ.get(key, '').strip()
    if not val:
        raise EnvironmentError(f'필수 환경변수 누락: {key}')
    return val


def _strip_html(text: str) -> str:
    """네이버 API 응답의 <b>, &quot; 등 제거."""
    import re
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&apos;', "'")
    return text.strip()


def _shorten_url(url: str) -> str:
    """TinyURL API로 URL 단축. 실패 시 원본 반환."""
    try:
        encoded = urllib.parse.quote(url, safe='')
        req = urllib.request.Request(
            TINYURL_API + encoded,
            headers={'User-Agent': 'Mozilla/5.0'},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            short = resp.read().decode('utf-8').strip()
        if short.startswith('http'):
            return short
    except Exception as e:
        logger.warning(f'TinyURL 실패({url[:40]}…): {e}')
    return url


def _send_telegram(token: str, chat_id: str, text: str) -> bool:
    """텔레그램 메시지 전송. 4096자 초과 시 자동 분할."""
    def _post(chunk: str) -> bool:
        payload = json.dumps({
            'chat_id': chat_id,
            'text': chunk,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }).encode('utf-8')
        url = TELEGRAM_API.format(token=token)
        req = urllib.request.Request(
            url,
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                return result.get('ok', False)
        except Exception as e:
            logger.error(f'텔레그램 전송 오류: {e}')
            return False

    LIMIT = 4096
    if len(text) <= LIMIT:
        return _post(text)

    # 4096자 단위로 분할 (줄바꿈 경계 우선)
    parts = []
    while text:
        if len(text) <= LIMIT:
            parts.append(text)
            break
        split_at = text.rfind('\n', 0, LIMIT)
        if split_at == -1:
            split_at = LIMIT
        parts.append(text[:split_at])
        text = text[split_at:].lstrip('\n')

    ok = True
    for part in parts:
        if not _post(part):
            ok = False
    return ok


# ────────────────────────────────────────────────────────────────────────────
# 네이버 검색
# ────────────────────────────────────────────────────────────────────────────

def _naver_search(query: str, client_id: str, client_secret: str,
                  display: int = MAX_RESULTS_PER_QUERY) -> list[dict]:
    """네이버 뉴스 검색 API 호출. 결과 목록 반환."""
    params = urllib.parse.urlencode({
        'query': query,
        'display': display,
        'sort': 'date',
    })
    url = f'{NAVER_SEARCH_URL}?{params}'
    req = urllib.request.Request(
        url,
        headers={
            'X-Naver-Client-Id': client_id,
            'X-Naver-Client-Secret': client_secret,
            'User-Agent': 'Mozilla/5.0',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data.get('items', [])
    except Exception as e:
        logger.error(f'네이버 검색 오류({query}): {e}')
        return []


def _parse_pub_date(pub_date_str: str) -> datetime | None:
    """'Mon, 13 Mar 2026 07:30:00 +0900' → KST aware datetime."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_date_str)
        return dt.astimezone(KST)
    except Exception:
        return None


# ────────────────────────────────────────────────────────────────────────────
# 판 결정 & 시간 필터링
# ────────────────────────────────────────────────────────────────────────────

def _detect_edition(now: datetime) -> str:
    """현재 시각 기준으로 오전판/오후판 자동 결정."""
    return 'morning' if now.hour < MORNING_CUTOFF_HOUR else 'afternoon'


def _time_window(edition: str, now: datetime) -> tuple[datetime, datetime]:
    """수집 대상 시간 범위 (start, end) 반환."""
    if edition == 'morning':
        start = now - timedelta(hours=MORNING_LOOKBACK_HOURS)
    else:
        start = now - timedelta(hours=AFTERNOON_LOOKBACK_HOURS)
    return start, now


def _filter_by_time(articles: list[dict], start: datetime, end: datetime) -> list[dict]:
    """발행 시각이 [start, end] 범위에 있는 기사만 반환."""
    filtered = []
    for art in articles:
        pub = _parse_pub_date(art.get('pubDate', ''))
        if pub and start <= pub <= end:
            filtered.append({**art, '_pub': pub})
    return filtered


# ────────────────────────────────────────────────────────────────────────────
# 중복 제거 & 섹션 분류
# ────────────────────────────────────────────────────────────────────────────

def _deduplicate(articles: list[dict], threshold: float = DEDUP_THRESHOLD) -> list[dict]:
    """제목 유사도 기반 중복 제거."""
    selected = []
    for art in articles:
        title = art.get('_clean_title', art.get('title', ''))
        is_dup = any(
            difflib.SequenceMatcher(None, title, s.get('_clean_title', '')).ratio() >= threshold
            for s in selected
        )
        if not is_dup:
            selected.append(art)
    return selected


def _classify_section(title: str) -> str:
    """제목 키워드 매칭으로 섹션 분류."""
    for section, keywords in SECTIONS.items():
        if not keywords:
            continue
        if any(kw in title for kw in keywords):
            return section
    return '🗂️ 기타'


# ────────────────────────────────────────────────────────────────────────────
# 메시지 포매팅
# ────────────────────────────────────────────────────────────────────────────

def _format_message(edition: str, now: datetime,
                    sections: dict[str, list[dict]]) -> str:
    """섹션별로 묶어 최종 텔레그램 메시지 생성."""
    edition_label = '🌅 오전판' if edition == 'morning' else '🌆 오후판'
    date_str = now.strftime('%Y년 %m월 %d일 %H:%M')

    lines = [
        f'<b>📰 단독 뉴스 {edition_label}</b>',
        f'<i>수집 기준: {date_str} KST</i>',
        '',
    ]

    total = 0
    for section_name in SECTIONS:  # 고정 순서 유지
        arts = sections.get(section_name, [])
        if not arts:
            continue
        lines.append(f'<b>{section_name}</b>')
        for art in arts[:MAX_PER_SECTION]:
            title = art.get('_clean_title', '제목 없음')
            url   = art.get('_short_url', art.get('originallink', art.get('link', '#')))
            pub   = art['_pub'].strftime('%H:%M') if '_pub' in art else ''
            lines.append(f'  • [{pub}] <a href="{url}">{title}</a>')
            total += 1
        lines.append('')

    lines.append(f'<i>총 {total}건 | NR2 단독 스크랩봇</i>')
    return '\n'.join(lines)


# ────────────────────────────────────────────────────────────────────────────
# 메인 실행
# ────────────────────────────────────────────────────────────────────────────

def run(edition: str | None = None) -> None:
    # ── 환경변수 로드 ──────────────────────────────────────────────────────
    try:
        client_id     = _get_env('NAVER_CLIENT_ID')
        client_secret = _get_env('NAVER_CLIENT_SECRET')
        bot_token     = _get_env('SCRAP_BOT_TOKEN')
        chat_id       = _get_env('SCRAP_CHAT_ID')
    except EnvironmentError as e:
        logger.error(str(e))
        return

    now = datetime.now(KST)
    if edition is None:
        edition = _detect_edition(now)
    logger.info(f'[DailyScrap] 실행 — {edition} 판, {now.strftime("%Y-%m-%d %H:%M")} KST')

    # ── 수집 시간 범위 결정 ────────────────────────────────────────────────
    start_dt, end_dt = _time_window(edition, now)
    logger.info(f'[DailyScrap] 수집 범위: {start_dt.strftime("%m/%d %H:%M")} ~ {end_dt.strftime("%m/%d %H:%M")}')

    # ── 네이버 검색 (두 패턴 모두 조회) ───────────────────────────────────
    raw: list[dict] = []
    for query in ('[단독]', '(단독)'):
        items = _naver_search(query, client_id, client_secret)
        raw.extend(items)
        logger.info(f'  검색 "{query}": {len(items)}건')

    if not raw:
        logger.warning('[DailyScrap] 수집된 기사 없음')
        return

    # ── 시간 필터 ─────────────────────────────────────────────────────────
    time_filtered = _filter_by_time(raw, start_dt, end_dt)
    logger.info(f'[DailyScrap] 시간 필터 후: {len(time_filtered)}건')

    # ── 제목 정제 + 중복 제거 ─────────────────────────────────────────────
    for art in time_filtered:
        art['_clean_title'] = _strip_html(art.get('title', ''))

    deduped = _deduplicate(time_filtered)
    logger.info(f'[DailyScrap] 중복 제거 후: {len(deduped)}건')

    if not deduped:
        logger.info('[DailyScrap] 발송할 기사 없음')
        return

    # ── URL 단축 ──────────────────────────────────────────────────────────
    for art in deduped:
        original = art.get('originallink') or art.get('link', '')
        art['_short_url'] = _shorten_url(original) if original else '#'

    # ── 섹션 분류 ─────────────────────────────────────────────────────────
    sections: dict[str, list[dict]] = {s: [] for s in SECTIONS}
    for art in deduped:
        section = _classify_section(art['_clean_title'])
        sections[section].append(art)

    for sec, arts in sections.items():
        if arts:
            logger.info(f'  {sec}: {len(arts)}건')

    # ── 메시지 포매팅 & 전송 ──────────────────────────────────────────────
    message = _format_message(edition, now, sections)
    success = _send_telegram(bot_token, chat_id, message)

    if success:
        logger.info('[DailyScrap] 텔레그램 전송 완료')
    else:
        logger.error('[DailyScrap] 텔레그램 전송 실패')


# ────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    forced_edition = sys.argv[1] if len(sys.argv) > 1 else None
    if forced_edition not in (None, 'morning', 'afternoon'):
        print('사용법: python scripts/daily_scrap.py [morning|afternoon]')
        sys.exit(1)
    run(forced_edition)
