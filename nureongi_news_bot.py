"""누렁이 뉴스봇 - 한글 네이버 뉴스 크롤링"""
import os
import asyncio
import requests
import json
from bs4 import BeautifulSoup
from telegram import Bot
from datetime import datetime, timezone, timedelta
import pytz

BOT_TOKEN = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
CHAT_ID = "@gazzzza2025"
KST = pytz.timezone('Asia/Seoul')

# 중복 방지 - 파일로 영구 저장
SENT_FILE = '/tmp/sent_news.json'

def load_sent_news():
    try:
        with open(SENT_FILE, 'r') as f:
            return set(json.load(f))
    except:
        return set()

def save_sent_news(sent):
    try:
        with open(SENT_FILE, 'w') as f:
            json.dump(list(sent), f)
    except:
        pass

KEYWORDS = [
    "삼성", "SK", "LG", "현대", "AI", "챗GPT", "테슬라", "엔비디아",
    "환율", "금리", "HBM", "반도체", "머스크", "애플", "코스피",
    "팔란티어", "안두릴", "UAM", "AAM", "드론", "클로드", "젠슨황",
    "피터틸", "아모데이",
    "이재명", "장동혁", "한동훈", "민주당", "국민의힘",
    "정청래", "조국", "김어준", "윤석열", "김건희",
    "이준석", "선거", "지방선거",
    "트럼프", "푸틴", "시진핑", "다카이치", "네타냐후", "에르도안",
]

SPECIAL_TAGS = ['[단독]', '[속보]', '[여론조사]', '[기획]', '[인터뷰]', '(단독)']

SOURCES = [
    ("경제", "https://news.naver.com/section/101"),
    ("정치", "https://news.naver.com/section/100"),
    ("IT/과학", "https://news.naver.com/section/105"),
    ("세계", "https://news.naver.com/section/104"),
]

def get_article_time(link):
    """기사 페이지에서 작성 시간 추출"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(link, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        # 네이버 뉴스 날짜 태그
        time_tag = soup.select_one('.media_end_head_info_datestamp_time, ._ARTICLE_DATE_TIME')
        if time_tag:
            dt_str = time_tag.get('data-date-time') or time_tag.get_text(strip=True)
            if dt_str:
                dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                return dt
    except:
        pass
    return None

def get_news():
    """네이버 뉴스 크롤링 - 1시간 이내 기사만"""
    articles = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    for section_name, url in SOURCES:
        try:
            res = requests.get(url, headers=headers, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            items = soup.select('a.sa_text_title')

            for item in items[:20]:
                title = item.get_text(strip=True)
                link = item.get('href', '')
                if not link.startswith('http'):
                    continue

                # 키워드 또는 특수태그 필터
                matched = (
                    any(tag in title for tag in SPECIAL_TAGS) or
                    any(kw in title for kw in KEYWORDS)
                )
                if not matched:
                    continue

                # 1시간 이내 기사만
                article_time = get_article_time(link)
                if article_time and article_time < one_hour_ago:
                    continue

                articles.append((title, link, section_name))

        except Exception as e:
            print(f"크롤링 오류 [{section_name}]: {e}")

    return articles

async def send_news():
    """새 뉴스 텔레그램 전송"""
    if not BOT_TOKEN:
        print("NUREONGI_NEWS_BOT_TOKEN 환경변수 없음")
        return

    sent_news = load_sent_news()
    bot = Bot(BOT_TOKEN)
    articles = get_news()
    new_count = 0

    for title, link, section in articles:
        if link in sent_news:
            continue

        sent_news.add(link)
        tags = [f"#{kw}" for kw in KEYWORDS if kw in title]
        tag_str = " ".join(tags[:3])

        section_emoji = {
            "경제": "💰", "정치": "🏛️", "IT/과학": "💻", "세계": "🌍"
        }.get(section, "📰")

        message = (
            f"{section_emoji} <b>[{section}] 뉴스 알림</b>\n\n"
            f"{title}\n\n"
            f"{tag_str}\n"
            f"🔗 {link}"
        )

        try:
            await bot.send_message(
                CHAT_ID,
                message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            print(f"✅ [{section}] {title[:30]}")
            new_count += 1
            await asyncio.sleep(2)
        except Exception as e:
            print(f"❌ 전송 실패: {e}")

    save_sent_news(sent_news)
    print(f"[뉴스봇] 완료 — {new_count}개 전송")

def run_news_bot():
    asyncio.run(send_news())
