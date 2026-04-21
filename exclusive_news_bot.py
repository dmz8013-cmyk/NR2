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

import pytz
import requests

logger = logging.getLogger(__name__)

KST = pytz.timezone('Asia/Seoul')

BOT_TOKEN_SCRAP = os.environ.get('SCRAP_BOT_TOKEN')
CHAT_ID_SCRAP = os.environ.get('SCRAP_CHAT_ID', '5132309076')
BOT_TOKEN_NR = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
CHAT_ID_NR = '@gazzzza2025'

NAVER_API_URL = 'https://openapi.naver.com/v1/search/news.json'
TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'
TELEGRAM_LIMIT = 4096

CATEGORY_KEYWORDS = {
    '💰 경제': ['주식', '증시', '기업', '투자', '금융', '코스피', '환율',
              '매출', '상장', '인수', '합병', '펀드', 'IPO', '채권'],
    '🏛️ 정치': ['국회', '정당', '의원', '대통령', '장관', '청와대',
              '민주당', '국민의힘', '선거', '공천', '내각'],
    '🌐 국제': ['미국', '중국', '일본', '러시아', '트럼프', '외교',
              '유엔', 'UN', '글로벌', '해외', '북한'],
    '💻 IT·과학': ['AI', '삼성', '애플', '구글', '메타', '반도체',
                 '스타트업', '플랫폼', '앱', '데이터'],
    '👥 사회': ['경찰', '검찰', '법원', '사건', '사고', '재판',
              '수사', '범죄', '복지', '의료'],
    '🎬 문화·연예': ['영화', '드라마', '음악', '연예', '배우',
                  '가수', '스포츠', '공연'],
}
CATEGORY_ORDER = ['💰 경제', '🏛️ 정치', '🌐 국제', '💻 IT·과학', '👥 사회', '🎬 문화·연예', '📌 기타']

_TAG_RE = re.compile(r'<[^>]+>')


def clean_html(text):
    """네이버 API 제목의 <b> 태그 + HTML 엔티티(&quot;, &amp; 등) 제거."""
    if not text:
        return ''
    stripped = _TAG_RE.sub('', text)
    return html.unescape(stripped).strip()


def get_time_range():
    """오전판 수집 구간: 전날 17:00 ~ 당일 07:30 (KST, tz-aware)."""
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


def classify_category(title):
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in title for kw in keywords):
            return cat
    return '📌 기타'


def fetch_exclusive_news():
    """네이버 뉴스 검색 API로 [단독] 기사 수집 → 시간 필터링."""
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

    # 중복 URL 제거 + 시간 필터 + 단독 재확인
    seen_urls = set()
    filtered = []
    for item in all_items:
        title = clean_html(item.get('title', ''))
        if '단독' not in title:
            continue
        link = item.get('originallink') or item.get('link') or ''
        if not link or link in seen_urls:
            continue
        pub_dt = parse_pub_date(item.get('pubDate', ''))
        if not pub_dt:
            continue
        if not (start_time <= pub_dt <= end_time):
            continue
        seen_urls.add(link)
        filtered.append({
            'pub_dt': pub_dt,
            'time': pub_dt.strftime('%H:%M'),
            'title': title,
            'link': link,
            'category': classify_category(title),
        })

    # 시간 역순(최신 먼저)
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
        return '\n'.join(lines)

    groups = defaultdict(list)
    for item in items:
        groups[item['category']].append(item)

    for cat in CATEGORY_ORDER:
        bucket = groups.get(cat)
        if not bucket:
            continue
        lines.append(f'<b>{html.escape(cat)}</b>')
        for item in bucket:
            # 제목은 절대 자르지 않고 전체 출력
            safe_title = html.escape(item['title'])
            safe_link = html.escape(item['link'], quote=True)
            lines.append(f'• [{item["time"]}] <a href="{safe_link}">{safe_title}</a>')
        lines.append('')

    lines.append(f'총 {len(items)}건 | NR2 단독 스크랩봇')
    lines.append('📖 오늘 브리핑 전문 + 심층 토론')
    lines.append('🔗 https://nr2.kr')

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
