"""VIP 알림봇 - 머스크/트럼프 실시간 뉴스 모니터링 (네이버 API)"""
import os
import time
import requests
import json
import logging
import urllib.parse

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('SCHEDULE_BOT_TOKEN', '8734510853:AAHsqC3fQfC0K02-xrWEZgnh9ZDGUIi2P44')
CHAT_ID = '5132309076'
SENT_FILE = '/tmp/vip_sent.json'

TARGETS = [    {'name': '앤트로픽/AI', 'emoji': '🤖', 'queries': ['앤트로픽', 'Anthropic', 'AI 인공지능']},
    {'name': '일론 머스크', 'emoji': '🚀', 'queries': ['일론 머스크', '머스크']},
    {'name': '도널드 트럼프', 'emoji': '🇺🇸', 'queries': ['트럼프', '도널드 트럼프']},
    {'name': '섹스', 'emoji': '🔞', 'queries': ['섹스', '성관계 뉴스']},
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


def fetch_naver_news(query, limit=10):
    """네이버 뉴스 검색 API"""
    articles = []
    naver_id = os.environ.get('NAVER_CLIENT_ID', '')
    naver_secret = os.environ.get('NAVER_CLIENT_SECRET', '')
    if not naver_id:
        return articles
    try:
        params = urllib.parse.urlencode({'query': query, 'display': limit, 'sort': 'date'})
        url = f'https://openapi.naver.com/v1/search/news.json?{params}'
        r = requests.get(url, headers={
            'X-Naver-Client-Id': naver_id,
            'X-Naver-Client-Secret': naver_secret,
        }, timeout=10)
        data = r.json()
        for item in data.get('items', []):
            title = item.get('title', '')
            title = title.replace('<b>', '').replace('</b>', '')
            title = title.replace('&quot;', '"').replace('&amp;', '&')
            title = title.replace('&lt;', '<').replace('&gt;', '>')
            link = item.get('originallink', item.get('link', ''))
            articles.append({
                'title': title,
                'link': link,
            })
    except Exception as e:
        logger.error(f"네이버 검색 실패 [{query}]: {e}")
    return articles


def check_and_send():
    """새 뉴스 확인 후 전송"""
    sent = load_sent()
    first_run = len(sent) == 0
    new_count = 0

    for target in TARGETS:
        all_articles = []
        seen_titles = set()

        for query in target['queries']:
            articles = fetch_naver_news(query, limit=10)
            for art in articles:
                if art['title'] not in seen_titles:
                    seen_titles.add(art['title'])
                    all_articles.append(art)

        for art in all_articles:
            if art['link'] in sent:
                continue
            if target_count >= 3:
                break
            if first_run:
                sent.add(art['link'])
                continue
            sent.add(art['link'])
            message = (
                f"{target['emoji']} <b>{target['name']} 관련 뉴스</b>\n\n"
                f"📝 {art['title']}\n"
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
                    target_count += 1
                    time.sleep(3)
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