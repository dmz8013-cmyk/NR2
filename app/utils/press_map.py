"""언론사 도메인 → 한글명 매핑 공용 유틸.

기존 exclusive_news_bot.py에 하드코딩돼 있던 PRESS_MAP을 분리.
단축 URL·뉴스 봇·편향 리포트 등에서 공유.
"""
import re
from urllib.parse import urlparse


# 네이버 뉴스 미러 URL의 언론사 ID (3자리) → 한글명.
# n.news.naver.com/article/{press_id}/{article_no} 포맷 지원.
NAVER_PRESS_ID = {
    '001': '연합뉴스',
    '003': '뉴시스',
    '005': '국민일보',
    '008': '머니투데이',
    '009': '매일경제',
    '011': '서울경제',
    '014': '파이낸셜뉴스',
    '015': '한국경제',
    '016': '헤럴드경제',
    '018': '이데일리',
    '020': '동아일보',
    '021': '문화일보',
    '022': '세계일보',
    '023': '조선일보',
    '025': '중앙일보',
    '028': '한겨레',
    '029': '디지털타임스',
    '032': '경향신문',
    '044': '오마이뉴스',
    '055': 'SBS',
    '056': 'KBS',
    '057': 'MBN',
    '081': '서울신문',
    '119': '데일리안',
    '138': '디지털데일리',
    '214': 'MBC',
    '277': '아시아경제',
    '366': '조선비즈',
    '374': 'SBS Biz',
    '421': '뉴스1',
    '422': '연합뉴스TV',
    '437': 'JTBC',
    '449': '채널A',
    '469': '한국일보',
    '648': '비즈워치',
    '654': '강원일보',
    '855': 'CJB청주방송',
}

_NAVER_ARTICLE_RE = re.compile(
    r'n\.news\.naver\.com/(?:mnews/)?article/(\d{3})/',
    re.IGNORECASE,
)

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


def extract_press(url):
    """도메인 기반 언론사명 추출. 매칭 실패 시 None."""
    if not url:
        return None
    low = url.lower()
    for domain, name in PRESS_MAP.items():
        if domain in low:
            return name
    return None


def resolve_press_name(url):
    """네이버 뉴스 미러 URL 우선, 실패 시 도메인 기반 PRESS_MAP fallback.

    - https://n.news.naver.com/mnews/article/421/0008901473 → 뉴스1
    - https://www.chosun.com/... → 조선일보
    - 매칭 불가 → None
    """
    if not url:
        return None
    m = _NAVER_ARTICLE_RE.search(url)
    if m:
        press = NAVER_PRESS_ID.get(m.group(1))
        if press:
            return press
    return extract_press(url)


def extract_domain(url):
    """URL에서 정규화된 도메인 추출 (www./m. 제거)."""
    if not url:
        return None
    try:
        netloc = urlparse(url).netloc.replace('www.', '').replace('m.', '')
        return netloc[:100] or None
    except Exception:
        return None
