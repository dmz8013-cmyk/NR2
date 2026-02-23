"""누렁이 사설봇 - 매일 아침 15개 신문 사설 (Google News RSS)"""
import os
import requests
import logging
from bs4 import BeautifulSoup
from datetime import datetime

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('SCHEDULE_BOT_TOKEN', '8734510853:AAHsqC3fQfC0K02-xrWEZgnh9ZDGUIi2P44')
CHAT_ID = '5132309076'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

PAPERS = {
    '종합지': ['경향신문', '국민일보', '동아일보', '서울신문', '세계일보', '조선일보', '중앙일보', '한겨레', '한국일보'],
    '경제지': ['디지털타임스', '매일경제', '서울경제', '이데일리', '파이낸셜뉴스', '한국경제'],
}


def get_editorials_google(paper_name, limit=3):
    """Google News RSS로 사설 검색"""
    try:
        query = f'{paper_name} 사설'
        url = f'https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=ko&gl=KR&ceid=KR:ko'
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'xml')

        today = datetime.now().strftime('%Y')
        titles = []
        for item in soup.select('item')[:10]:
            title = item.select_one('title').text.strip()
            # [사설] 태그 있는 것만 + 언론사명 제거
            if True:  # 모든 결과 수집 (Google 검색이 이미 필터링)
                clean = title.split(' - ')[0].strip()
                clean = clean.replace('[사설]', '').replace('[사설] ', '').strip()
                if clean and len(clean) > 5:
                    titles.append(clean)
        return titles[:limit]
    except Exception as e:
        logger.error(f"{paper_name} 사설 검색 실패: {e}")
        return []


def format_message(editorials):
    """텔레그램 메시지 포맷"""
    lines = ['🗞️ <b>주요 신문 사설</b> 🗞️\n']

    for category, papers in editorials.items():
        lines.append(f'\n<b>*{category}*</b>')
        for name, titles in papers.items():
            lines.append(f'◇{name}')
            if titles:
                for t in titles:
                    lines.append(f'-{t}')
            else:
                lines.append('-사설을 찾지 못했습니다')

    lines.append(f'\n출처: https://t.me/gazzzza2025')
    lines.append('(실시간 텔레그램 정보방)')
    return '\n'.join(lines)


def send_editorial():
    """사설 수집 후 텔레그램 전송"""
    logger.info("=== 사설봇 시작 ===")
    print("사설봇 시작...")

    editorials = {}
    for category, papers in PAPERS.items():
        editorials[category] = {}
        for name in papers:
            titles = get_editorials_google(name)
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
                'parse_mode': 'HTML',
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
