"""누렁이 뉴스봇 v2 - 언론사 표시 + 속보/단독 강화"""
import os
import asyncio
import requests
import json
from bs4 import BeautifulSoup
from telegram import Bot

BOT_TOKEN = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
CHAT_ID = "@gazzzza2025"
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
            json.dump(list(sent)[-500:], f)
    except:
        pass

KEYWORDS = [
    "삼성", "SK", "LG", "현대", "AI", "챗GPT", "테슬라", "엔비디아",
    "환율", "금리", "HBM", "반도체", "머스크", "애플", "코스피",
    "팔란티어", "안두릴", "UAM", "AAM", "드론", "클로드", "젠슨황",
    "피터틸", "아모데이",
    "손흥민", "오타니",
    "이재명", "장동혁", "한동훈", "민주당", "국민의힘",
    "정청래", "조국", "김어준", "윤석열", "김건희",
    "이준석", "선거", "지방선거",
    "트럼프", "푸틴", "시진핑", "다카이치", "네타냐후", "에르도안",
]

SPECIAL_TAGS = ['[단독]', '[속보]', '[여론조사]', '[기획]', '[인터뷰]', '(단독)', '[긴급]', '[breaking]']

# 섹션 + 속보 페이지
SOURCES = [
    ("정치", "https://news.naver.com/section/100"),
    ("경제", "https://news.naver.com/section/101"),
    ("세계", "https://news.naver.com/section/104"),
    ("IT/과학", "https://news.naver.com/section/105"),
]

# 속보 전용 페이지 (최신순 정렬)
BREAKING_SOURCES = [
    ("정치", "https://news.naver.com/breakingnews/section/100"),
    ("경제", "https://news.naver.com/breakingnews/section/101"),
    ("세계", "https://news.naver.com/breakingnews/section/104"),
    ("IT/과학", "https://news.naver.com/breakingnews/section/105"),
]

# 속보 전문 언론사 (이 언론사의 [속보][단독]은 우선 전송)
WIRE_SERVICES = ['연합뉴스', '뉴시스', '뉴스1']

SECTION_EMOJI = {
    "경제": "💰", "정치": "🏛️", "IT/과학": "💻", "세계": "🌍"
}


def parse_articles(url, section_name, limit=30):
    """네이버 뉴스 섹션 파싱 - 언론사 포함"""
    articles = []
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        items = soup.select('.sa_item')[:limit]
        for item in items:
            title_el = item.select_one('a.sa_text_title')
            press_el = item.select_one('.sa_text_press')
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = title_el.get('href', '')
            press = press_el.get_text(strip=True) if press_el else '미상'
            if not link.startswith('http'):
                continue
            articles.append({
                'title': title,
                'link': link,
                'press': press,
                'section': section_name,
            })
    except Exception as e:
        print(f"크롤링 오류 [{section_name}]: {e}")
    return articles


def get_news():
    """키워드/태그 매칭 기사 수집"""
    all_articles = []
    seen_links = set()

    # 1) 속보 페이지 먼저 (최신순)
    for section_name, url in BREAKING_SOURCES:
        for art in parse_articles(url, section_name, limit=60):
            if art['link'] not in seen_links:
                seen_links.add(art['link'])
                all_articles.append(art)

    # 2) 일반 섹션
    for section_name, url in SOURCES:
        for art in parse_articles(url, section_name, limit=30):
            if art['link'] not in seen_links:
                seen_links.add(art['link'])
                all_articles.append(art)

    # 3) 필터: 키워드 또는 특수태그 매칭
    matched = []
    for art in all_articles:
        title = art['title']
        has_tag = any(tag.lower() in title.lower() for tag in SPECIAL_TAGS)
        has_keyword = any(kw in title for kw in KEYWORDS)
        is_wire_breaking = (art['press'] in WIRE_SERVICES and has_tag)

        if has_tag or has_keyword or is_wire_breaking:
            art['is_breaking'] = has_tag
            art['is_wire'] = art['press'] in WIRE_SERVICES
            matched.append(art)

    # 속보/단독 우선 정렬
    matched.sort(key=lambda x: (x['is_breaking'] and x['is_wire'], x['is_breaking']), reverse=True)
    return matched


def format_message(art):
    """새 포맷: 언론사 + 제목 + URL"""
    emoji = SECTION_EMOJI.get(art['section'], '📰')

    # 속보/단독 강조
    prefix = ""
    if any(tag in art['title'] for tag in ['[속보]', '[긴급]']):
        prefix = "🚨 "
    elif any(tag in art['title'] for tag in ['[단독]', '(단독)']):
        prefix = "⚡ "

    return (
        f"{prefix}{emoji} <b>[{art['section']}]</b>\n"
        f"🏷️ 언론사: {art['press']}\n"
        f"📝 제목: {art['title']}\n"
        f"🔗 {art['link']}"
    )


async def send_news():
    if not BOT_TOKEN:
        print("NUREONGI_NEWS_BOT_TOKEN 환경변수 없음")
        return
    sent_news = load_sent_news()
    first_run = len(sent_news) == 0
    bot = Bot(BOT_TOKEN)
    articles = get_news()
    new_count = 0
    for art in articles:
        if art['link'] in sent_news:
            continue
        if first_run:
            sent_news.add(art['link'])
            continue
        sent_news.add(art['link'])
        if new_count >= 15:
            break
        message = format_message(art)
        try:
            await bot.send_message(
                CHAT_ID, message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            tag = "🚨속보" if art['is_breaking'] else "📰"
            print(f"✅ {tag} [{art['press']}] {art['title'][:30]}")
            new_count += 1
            await asyncio.sleep(2)
        except Exception as e:
            print(f"❌ 전송 실패: {e}")
    save_sent_news(sent_news)
    print(f"[뉴스봇v2] 완료 — {new_count}개 전송")


def run_news_bot():
    asyncio.run(send_news())