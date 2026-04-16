"""누렁이 사설봇 - 매일 아침 15개 신문 사설 (네이버 검색 API)"""
import os
import requests
import logging
import urllib.parse
from datetime import datetime

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('SCRAP_BOT_TOKEN')
CHAT_ID = os.environ.get('SCRAP_CHAT_ID', '5132309076')
NAVER_CLIENT_ID = os.environ.get('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')

PAPERS = {
    '종합지': ['경향신문', '국민일보', '동아일보', '서울신문', '세계일보', '조선일보', '중앙일보', '한겨레', '한국일보'],
    '경제지': ['디지털타임스', '매일경제', '머니투데이', '서울경제', '이데일리', '파이낸셜뉴스', '한국경제'],
}

# 네이버 검색에서 '[사설]' 태그가 잘 잡히지 않는 언론사 — 쿼리/필터 보완 대상
SPECIAL_PAPERS = ('머니투데이', '이데일리')


def escape_md(text):
    """텔레그램 MarkdownV2 특수문자 escape"""
    special = r'\_*[]()~`>#+-=|{}.!'
    for ch in special:
        text = text.replace(ch, f'\\{ch}')
    return text


def search_naver_editorial(paper_name, limit=4):
    """네이버 뉴스 검색 API로 사설 찾기"""
    try:
        # 네이버 사설 태그 부재 언론사는 쿼리를 완화
        if paper_name in SPECIAL_PAPERS:
            query = f'{paper_name} 사설 오늘'
        else:
            query = f'"{paper_name}" 사설'
        params = urllib.parse.urlencode({
            'query': query,
            'display': 20,
            'sort': 'date'
        })
        url = f'https://openapi.naver.com/v1/search/news.json?{params}'

        headers = {
            'X-Naver-Client-Id': NAVER_CLIENT_ID,
            'X-Naver-Client-Secret': NAVER_CLIENT_SECRET,
        }
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()

        titles = []
        for item in data.get('items', []):
            title = item.get('title', '')
            # HTML 태그 제거
            title = title.replace('<b>', '').replace('</b>', '')
            title = title.replace('&quot;', '"').replace('&amp;', '&')
            title = title.replace('&lt;', '<').replace('&gt;', '>')

            # 사설 태그가 포함된 기사 필터링
            # 1) '[사설]' 포함
            # 2) '사설]' 포함 (변형 대괄호 대응)
            # 3) '사설'로 시작하는 경우
            # 4) '사설' + 언론사명이 동시에 포함 (태그 부재 언론사 대응)
            is_editorial = (
                '[사설]' in title
                or '사설]' in title
                or title.lstrip().startswith('사설')
                or ('사설' in title and paper_name in title)
            )

            if is_editorial:
                clean = title
                # 다양한 사설 태그 패턴 제거
                for pattern in ('[사설]', '사설]', '【사설】', '<사설>'):
                    clean = clean.replace(pattern, '')
                clean = clean.strip()
                if clean and len(clean) > 5:
                    titles.append(clean)

        return titles[:limit]
    except Exception as e:
        logger.error(f"{paper_name} 사설 검색 실패: {e}")
        return []


def format_message(editorials):
    """텔레그램 메시지 포맷 (MarkdownV2)"""
    today = datetime.now().strftime('%Y.%m.%d')
    lines = [f'🗞️주요 신문 사설\\({escape_md(today)}\\)🗞️\n']

    for category, papers in editorials.items():
        lines.append(f'\n*{escape_md(category)}*')
        for name, titles in papers.items():
            lines.append(f'◇{escape_md(name)}')
            if titles:
                for t in titles:
                    lines.append(f'\\-{escape_md(t)}')
            else:
                lines.append('\\-사설을 찾지 못했습니다')

    lines.append(f'\n출처: {escape_md("https://t.me/gazzzza2025")}')
    lines.append(escape_md('(실시간 텔레그램 정보방)'))
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━━')
    lines.append('📖 오늘 브리핑 전문 \\+ 심층 토론')
    lines.append(f'👉 {escape_md("https://nr2.kr")}')
    lines.append('━━━━━━━━━━━━━━━━')
    return '\n'.join(lines)


def send_editorial():
    """사설 수집 후 텔레그램 전송"""
    logger.info("=== 사설봇 시작 ===")
    print("사설봇 시작...")

    if not NAVER_CLIENT_ID:
        logger.error("NAVER_CLIENT_ID 환경변수 없음")
        print("NAVER_CLIENT_ID 없음 — 환경변수 확인 필요")
        return

    editorials = {}
    for category, papers in PAPERS.items():
        editorials[category] = {}
        for name in papers:
            titles = search_naver_editorial(name)
            editorials[category][name] = titles
            print(f"  {name}: {len(titles)}개")

    message = format_message(editorials)

    # 4096자 분할
    if len(message) > 4000:
        parts = []
        current = ""
        for line in message.split('\n'):
            if len(current) + len(line) + 1 > 4000:
                parts.append(current)
                current = line
            else:
                current += '\n' + line if current else line
        if current:
            parts.append(current)
    else:
        parts = [message]

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        for part in parts:
            resp = requests.post(url, json={
                'chat_id': CHAT_ID,
                'text': part,
                'parse_mode': 'MarkdownV2',
                'disable_web_page_preview': True,
            }, timeout=10)
            if resp.status_code == 200:
                print(f"전송 완료 ({len(part)}자)")
            else:
                print(f"전송 실패: {resp.text}")

        logger.info("=== 사설봇 완료 ===")
        print("사설봇 완료 ✅")
    except Exception as e:
        logger.error(f"사설봇 오류: {e}")
        print(f"오류: {e}")



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    send_editorial()