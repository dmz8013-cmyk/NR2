"""VIP 알림봇 - 머스크/트럼프 실시간 뉴스 모니터링"""
import os
import requests
import json
import logging
from bs4 import BeautifulSoup
from datetime import datetime

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('SCHEDULE_BOT_TOKEN', '8734510853:AAHsqC3fQfC0K02-xrWEZgnh9ZDGUIi2P44')
CHAT_ID = '5132309076'
SENT_FILE = '/tmp/vip_sent.json'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}

TARGETS = [
    {'name': '일론 머스크', 'emoji': '🚀', 'queries': ['일론 머스크', 'Elon Musk']},
    {'name': '도널드 트럼프', 'emoji': '🇺🇸', 'queries': ['트럼프', 'Donald Trump']},
]


def load_sent():
    try:
        with open(SENT_FILE, 'r') as f:
            return set(json.load(f))
    except:
        return set()


def save_sent(sent):
    try:
        with open(SENT_FILE, 'w') as f:
            json.dump(list(sent)[-300:], f)
    except:
        pass


def fetch_google_news(query, limit=10):
    """Google News RSS 한국어판 크롤링"""
    articles = []
    try:
        url = f'https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=ko&gl=KR&ceid=KR:ko'
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        for item in soup.select('item')[:limit]:
            title = item.select_one('title').text.strip()
            link = item.select_one('link').text.strip() if item.select_one('link') else ''
            source = title.split(' - ')[-1].strip() if ' - ' in title else ''
            clean_title = title.rsplit(' - ', 1)[0].strip() if ' - ' in title else title
            # 한글 기사만 필터링
            if not any("uac00" <= c <= "ud7a3" for c in clean_title):
                continue            
            pub_date = item.select_one('pubDate').text.strip() if item.select_one('pubDate') else ''
            articles.append({
                'title': clean_title,
                'source': source,
                'link': link,
                'pub_date': pub_date,
            })
    except Exception as e:
        logger.error(f"Google News 크롤링 실패 [{query}]: {e}")
    return articles


def check_and_send():
    """새 뉴스 확인 후 전송"""
    sent = load_sent()
    new_count = 0

    for target in TARGETS:
        all_articles = []
        seen_titles = set()

        for query in target['queries']:
            articles = fetch_google_news(query, limit=10)
            for art in articles:
                if art['title'] not in seen_titles:
                    seen_titles.add(art['title'])
                    all_articles.append(art)

        for art in all_articles:
            if art['link'] in sent:
                continue
            sent.add(art['link'])

            message = (
                f"{target['emoji']} <b>{target['name']} 관련 뉴스</b>\n\n"
                f"🏷️ 언론사: {art['source']}\n"
                f"📝 제목: {art['title']}\n"
                f"🔗 {art['link']}"
            )

            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                resp = requests.post(url, json={
                    'chat_id': CHAT_ID,
                    'text': message,
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': True,
                }, timeout=10)
                if resp.status_code == 200:
                    print(f"✅ {target['emoji']} {art['title'][:40]}")
                    new_count += 1
                else:
                    print(f"❌ 전송 실패: {resp.text}")
            except Exception as e:
                print(f"❌ 오류: {e}")

    save_sent(sent)
    print(f"[VIP알림봇] 완료 — {new_count}개 전송")


def run_vip_alert():
    check_and_send()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    check_and_send()
