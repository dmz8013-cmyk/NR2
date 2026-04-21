"""언론사 도메인 → 한글명 매핑 공용 유틸.

기존 exclusive_news_bot.py에 하드코딩돼 있던 PRESS_MAP을 분리.
단축 URL·뉴스 봇·편향 리포트 등에서 공유.
"""
from urllib.parse import urlparse

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
    """URL에서 언론사명 추출. 매칭 실패 시 None."""
    if not url:
        return None
    low = url.lower()
    for domain, name in PRESS_MAP.items():
        if domain in low:
            return name
    return None


def extract_domain(url):
    """URL에서 정규화된 도메인 추출 (www./m. 제거)."""
    if not url:
        return None
    try:
        netloc = urlparse(url).netloc.replace('www.', '').replace('m.', '')
        return netloc[:100] or None
    except Exception:
        return None
