"""단독 뉴스 오전판 봇 — 전날 17:00 ~ 당일 07:30 KST 구간의 [단독] 기사 수집·발송.

매일 07:31 KST에 SOB Scrap(@sob_scrap_bot) + 누렁이 정보방(@gazzzza2025)에 동시 발송.
"""
import os
import html
import re
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import pytz
import requests

logger = logging.getLogger(__name__)

KST = pytz.timezone('Asia/Seoul')

BOT_TOKEN_SCRAP = os.environ.get('SCRAP_BOT_TOKEN')
CHAT_ID_SCRAP = os.environ.get('SCRAP_CHAT_ID', '5132309076')
BOT_TOKEN_NR = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
CHAT_ID_NR = '@gazzzza2025'

NAVER_API_URL = 'https://openapi.naver.com/v1/search/news.json'
BULY_SHORTEN_URL = 'https://buly.kr/api/shorten'
TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'
TELEGRAM_LIMIT = 4096

# 순서 고정 — CATEGORIES 리스트 인덱스 순으로 메시지에 출력.
CATEGORIES = [
    {
        'label': '🏛️ 국민주권정부 (대통령실)',
        'keywords': ['대통령실', '국빈', '순방', '대통령 주재', '한덕수',
                     '국무회의', '수석', '비서관', '청와대', '용산'],
    },
    {
        'label': '🔔 오늘의 현안',
        'keywords': ['지방선거', '특검', '공천', '종교계', '로비', '의혹',
                     '이란', '미국', '전쟁', '호르무즈', '트럼프', '관세',
                     '탄핵', '헌재', '계엄'],
    },
    {
        'label': '🏛️ 이재명 정부',
        'keywords': ['이재명', '민주당', '국정', '장관', '정책', '법안',
                     '예산', '정부안', '입법', '국회 통과', '여당'],
    },
    {
        'label': '⚡ 정치',
        'keywords': ['국회', '의원', '국민의힘', '야당', '원내', '당대표',
                     '공천', '선거', '정치', '보궐', '재선거', '경선'],
    },
    {
        'label': '📢 사회 (사건·사고)',
        'keywords': ['사망', '살인', '폭행', '성범죄', '수사', '체포',
                     '검거', '구속', '재판', '판결', '경찰', '검찰',
                     '사고', '화재', '폭발', '추락'],
    },
    {
        'label': '💥 사회 (일반)',
        'keywords': ['복지', '의료', '교육', '노동', '환경', '청년',
                     '출산', '인구', '학교', '병원', '노조', '파업'],
    },
    {
        'label': '📊 경제 (일반·부동산·금융·블록체인)',
        'keywords': ['주식', '코스피', '증시', '부동산', '아파트', '금리',
                     '환율', '금융', '은행', '코인', '비트코인', '블록체인',
                     '펀드', '투자', '채권', '보험'],
    },
    {
        'label': '🏭 경제 (산업)',
        'keywords': ['삼성', 'LG', '현대', 'SK', '포스코', '반도체',
                     '배터리', '자동차', '조선', '철강', '에너지',
                     '공장', '수출', '수입', '무역', '기업', 'AI', '스타트업'],
    },
]
CATEGORY_ORDER = [c['label'] for c in CATEGORIES] + ['📌 기타']

PRESS_MAP = {
    'chosun': '조선일보',
    'joongang': '중앙일보',
    'donga': '동아일보',
    'hani': '한겨레',
    'khan': '경향신문',
    'ohmynews': '오마이뉴스',
    'yna': '연합뉴스',
    'yonhapnewstv': '연합뉴스TV',
    'mbc': 'MBC',
    'kbs': 'KBS',
    'sbs': 'SBS',
    'jtbc': 'JTBC',
    'tvchosun': 'TV조선',
    'mbn': 'MBN',
    'hankyung': '한국경제',
    'mk': '매일경제',
    'edaily': '이데일리',
    'newsis': '뉴시스',
    'news1': '뉴스1',
    'nocut': '노컷뉴스',
    'seoul': '서울신문',
    'munhwa': '문화일보',
    'kmib': '국민일보',
    'segye': '세계일보',
    'dt': '디지털타임스',
    'etnews': '전자신문',
}

_TAG_RE = re.compile(r'<[^>]+>')

# buly.kr 공개 API가 없어 연속 실패 시 이번 사이클은 단축을 포기 (원본 링크 사용).
_shortener_disabled = False


def clean_html(text):
    """네이버 API 문자열의 <b> 태그 + HTML 엔티티 제거."""
    if not text:
        return ''
    stripped = _TAG_RE.sub('', text)
    return html.unescape(stripped).strip()


def get_time_range():
    """오전판 수집 구간: 전날 17:00 ~ 당일 07:30 (KST)."""
    now = datetime.now(KST)
    end = now.replace(hour=7, minute=30, second=0, microsecond=0)
    start = (now - timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)
    return start, end


def parse_pub_date(pub_date_str):
    """RFC 822 pubDate → KST tz-aware datetime."""
    try:
        dt = parsedate_to_datetime(pub_date_str)
        if dt.tzinfo is None:
            dt = KST.localize(dt)
        return dt.astimezone(KST)
    except Exception as e:
        logger.warning(f'pubDate 파싱 실패 ({pub_date_str}): {e}')
        return None


def extract_press(link, originallink=''):
    """언론사명 추출. 발행처 도메인 정보가 있는 originallink를 우선 참조.

    네이버 미러 링크(n.news.naver.com)는 도메인에 언론사 정보가 없으므로
    originallink(실제 발행처 URL)로 PRESS_MAP 매칭 → 실패 시 도메인 그대로.
    """
    probe = originallink or link or ''
    low = probe.lower()
    for domain, name in PRESS_MAP.items():
        if domain in low:
            return name
    try:
        netloc = urlparse(probe).netloc.replace('www.', '').replace('m.', '')
        return netloc or '언론사 미상'
    except Exception:
        return '언론사 미상'


def classify_category(title, description=''):
    text = f'{title} {description}'
    for cat in CATEGORIES:
        if any(kw in text for kw in cat['keywords']):
            return cat['label']
    return '📌 기타'


def shorten_url(long_url):
    """buly.kr로 단축 시도. 실패 시 원본 URL 반환.

    buly.kr는 현재 공개 JSON API가 없어 대체로 실패할 것임을 가정.
    최초 호출이 실패하면 이번 사이클 동안 단축기 비활성화(성능 보호).
    """
    global _shortener_disabled
    if _shortener_disabled or not long_url:
        return long_url
    try:
        resp = requests.get(BULY_SHORTEN_URL, params={'url': long_url}, timeout=3)
        if resp.status_code == 200:
            ct = resp.headers.get('content-type', '')
            if 'json' in ct.lower():
                data = resp.json()
                short = data.get('shortUrl') or data.get('short_url')
                if short and short.startswith('http'):
                    return short
        # JSON이 아니거나 비정상 응답 — 단축기 비활성화
        _shortener_disabled = True
        logger.info('buly.kr 단축 API 비활성화 — 원본 URL 사용')
    except Exception as e:
        _shortener_disabled = True
        logger.info(f'buly.kr 단축 실패, 원본 URL 사용: {e}')
    return long_url


def fetch_exclusive_news():
    """네이버 뉴스 검색 API로 [단독] 기사 수집 → 시간 필터링."""
    global _shortener_disabled
    _shortener_disabled = False  # 매 실행 초기화

    client_id = os.environ.get('NAVER_CLIENT_ID')
    client_secret = os.environ.get('NAVER_CLIENT_SECRET')
    if not client_id or not client_secret:
        logger.error('NAVER_CLIENT_ID/SECRET 환경변수 없음')
        return []

    headers = {
        'X-Naver-Client-Id': client_id,
        'X-Naver-Client-Secret': client_secret,
    }

    start_time, end_time = get_time_range()
    all_items = []

    # 100건씩 최대 10페이지 (1000건) — 전날 17:00~당일 07:30 구간 안정 커버
    for start in (1, 101, 201, 301, 401, 501, 601, 701, 801, 901):
        params = {
            'query': '[단독]',
            'display': 100,
            'start': start,
            'sort': 'date',
        }
        try:
            resp = requests.get(NAVER_API_URL, headers=headers, params=params, timeout=10)
            items = resp.json().get('items', [])
        except Exception as e:
            logger.error(f'네이버 API 호출 실패 (start={start}): {e}')
            break
        if not items:
            break
        all_items.extend(items)

    seen_urls = set()
    filtered = []
    for item in all_items:
        title = clean_html(item.get('title', ''))
        if '단독' not in title:
            continue
        # 표시용 URL은 반드시 네이버뉴스 링크(item['link'])
        naver_link = item.get('link') or ''
        originallink = item.get('originallink') or ''
        if not naver_link or naver_link in seen_urls:
            continue
        pub_dt = parse_pub_date(item.get('pubDate', ''))
        if not pub_dt:
            continue
        if not (start_time <= pub_dt <= end_time):
            continue

        description = clean_html(item.get('description', ''))
        seen_urls.add(naver_link)
        filtered.append({
            'pub_dt': pub_dt,
            'datetime_str': pub_dt.strftime('%Y-%m-%d %H:%M'),
            'title': title,
            'link': naver_link,
            'short_link': shorten_url(naver_link),
            'press': extract_press(naver_link, originallink),
            'category': classify_category(title, description),
        })

    filtered.sort(key=lambda x: x['pub_dt'], reverse=True)
    return filtered


def format_exclusive_message(items):
    now = datetime.now(KST)
    yesterday = (now - timedelta(days=1)).strftime('%m/%d')
    today = now.strftime('%m/%d')

    lines = [
        '🚨 단독 뉴스 오전판 🚨',
        f'수집 기준: {yesterday} 17:00 ~ {today} 07:30 KST',
        '',
    ]

    if not items:
        lines.append('수집된 단독 기사 없음')
        lines.append('')
        lines.append(f'총 0건 | NR2 단독 스크랩봇')
        lines.append('')
        lines.append('출처: https://t.me/gazzzza2025')
        lines.append('(실시간 텔레그램 정보방)')
        return '\n'.join(lines)

    groups = defaultdict(list)
    for item in items:
        groups[item['category']].append(item)

    for cat in CATEGORY_ORDER:
        bucket = groups.get(cat)
        if not bucket:
            continue
        lines.append(f'<b>{html.escape(cat)}</b>')
        lines.append('')
        for item in bucket:
            # 제목은 절대 자르지 않고 전체 출력
            safe_press = html.escape(item['press'])
            safe_title = html.escape(item['title'])
            # URL은 escape 하지 않고 그대로 — 텔레그램이 http(s)만 들어와도 안전하게 취급
            lines.append(f'🏷️ 언론사: {safe_press}')
            lines.append(f'📝 제목: {safe_title}')
            lines.append(f'🕐 발생 시각: {item["datetime_str"]}')
            lines.append(f'🔗 {item["short_link"]}')
            lines.append('')  # 기사 사이 빈 줄

    lines.append(f'총 {len(items)}건 | NR2 단독 스크랩봇')
    lines.append('')
    lines.append('출처: https://t.me/gazzzza2025')
    lines.append('(실시간 텔레그램 정보방)')

    return '\n'.join(lines)


def _split_for_telegram(text, limit=TELEGRAM_LIMIT):
    """4096자 초과 시 줄바꿈 경계로 분할."""
    if len(text) <= limit:
        return [text]
    parts = []
    current = ''
    for line in text.split('\n'):
        if len(current) + len(line) + 1 > limit:
            if current:
                parts.append(current)
            current = line
        else:
            current = f'{current}\n{line}' if current else line
    if current:
        parts.append(current)
    return parts


def _send_telegram(token, chat_id, text, channel_label):
    if not token:
        logger.warning(f'[{channel_label}] 봇 토큰 미설정 — 발송 스킵')
        return False
    url = TELEGRAM_API.format(token=token)
    parts = _split_for_telegram(text)
    ok = True
    for idx, chunk in enumerate(parts, 1):
        try:
            resp = requests.post(
                url,
                json={
                    'chat_id': chat_id,
                    'text': chunk,
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': True,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info(f'[{channel_label}] 발송 완료 ({idx}/{len(parts)}, {len(chunk)}자)')
            else:
                ok = False
                logger.error(f'[{channel_label}] 발송 실패 HTTP {resp.status_code}: {resp.text[:200]}')
        except Exception as e:
            ok = False
            logger.error(f'[{channel_label}] 발송 예외: {e}')
    return ok


def send_exclusive_news():
    """단독 뉴스 오전판 — SOB Scrap + 누렁이 정보방 동시 발송."""
    logger.info('=== 단독 뉴스 오전판 시작 ===')
    items = fetch_exclusive_news()
    logger.info(f'수집 결과: {len(items)}건')

    message = format_exclusive_message(items)

    _send_telegram(BOT_TOKEN_SCRAP, CHAT_ID_SCRAP, message, 'SOB Scrap')
    _send_telegram(BOT_TOKEN_NR, CHAT_ID_NR, message, '누렁이 정보방')

    logger.info('=== 단독 뉴스 오전판 종료 ===')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    send_exclusive_news()
