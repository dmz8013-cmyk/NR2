import asyncio
from telegram import Bot
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import pytz
import json
import os
import feedparser
import hashlib
from collections import defaultdict

BOT_TOKEN = "8591331989:AAEO0MuLnyFypcslPHMo8mWjW3LNy9BwejM"
CHAT_ID = "@gazzzza2025"

# 저장 파일
SENT_NEWS_FILE = "sent_news.json"
KEYWORD_TRACKER_FILE = "keyword_tracker.json"

KST = pytz.timezone('Asia/Seoul')

# 🔥 주요 언론사 RSS 피드
RSS_FEEDS = {
    "연합뉴스": [
        ("https://www.yonhapnewstv.co.kr/category/news/politics/feed/", "정치"),
        ("https://www.yonhapnewstv.co.kr/category/news/economy/feed/", "경제"),
        ("https://www.yonhapnewstv.co.kr/category/news/society/feed/", "사회"),
    ],
    "뉴시스": "https://www.newsis.com/RSS/sokbo.xml",
    "한국경제": [
        ("https://www.hankyung.com/feed/politics", "정치"),
        ("https://www.hankyung.com/feed/economy", "경제"),
    ],
    "매일경제": "https://www.mk.co.kr/rss/30100041/",
    "서울경제": "https://www.sedaily.com/RSS/S11.xml",
    "한겨레": "https://www.hani.co.kr/rss/",
}

# 중복 추적
sent_news = set()
title_hashes = set()
keyword_last_sent = defaultdict(lambda: datetime.min)

def load_data():
    """저장된 데이터 로드"""
    global sent_news, title_hashes
    
    if os.path.exists(SENT_NEWS_FILE):
        with open(SENT_NEWS_FILE, 'r') as f:
            data = json.load(f)
            sent_news = set(data.get('urls', []))
            title_hashes = set(data.get('hashes', []))

def save_data():
    """데이터 영구 저장"""
    with open(SENT_NEWS_FILE, 'w') as f:
        json.dump({
            'urls': list(sent_news),
            'hashes': list(title_hashes)
        }, f)

def get_title_hash(title):
    """제목 해시값 생성"""
    clean_title = title.replace("[속보]", "").replace("[단독]", "").replace("(단독)", "").strip()
    return hashlib.md5(clean_title.encode()).hexdigest()

def is_recent(pub_date, minutes=10):
    """최근 N분 이내 기사인지 확인"""
    try:
        if not pub_date:
            return True
        
        now = datetime.now(KST)
        article_time = datetime(*pub_date[:6], tzinfo=KST)
        
        return (now - article_time).total_seconds() < (minutes * 60)
    except:
        return True

def extract_keywords(title):
    """제목에서 주요 키워드 추출"""
    keywords = ["AI", "챗GPT", "삼성", "SK", "LG", "현대", "테슬라", "머스크", "애플", 
                "구글", "아마존", "금리", "환율", "대선", "총선", "여론조사"]
    
    for keyword in keywords:
        if keyword in title:
            return keyword
    return None

def should_send_keyword_news(title):
    """키워드 중복 체크 (5분 이내 동일 키워드는 1개만)"""
    keyword = extract_keywords(title)
    if not keyword:
        return True
    
    now = datetime.now(KST)
    last_sent = keyword_last_sent[keyword]
    
    if (now - last_sent).total_seconds() > 300:  # 5분
        keyword_last_sent[keyword] = now
        return True
    
    return False

async def send_news(bot, news_type, title, link, source=""):
    """뉴스 전송"""
    try:
        emoji_map = {
            "속보": "🔔",
            "단독": "🎯",
            "기획": "📋",
            "여론조사": "📊"
        }
        emoji = emoji_map.get(news_type, "📰")
        
        source_text = f"📰 {source}\n" if source else ""
        message = f"{emoji} <b>{news_type}</b>\n\n{title}\n\n{source_text}🔗 {link}"
        
        await bot.send_message(CHAT_ID, message, parse_mode="HTML")
        print(f"✅ [{news_type}] {title[:40]}... ({source})")
        return True
    except Exception as e:
        print(f"❌ 전송 실패: {e}")
        return False

async def fetch_rss_feed(bot, feed_url, source_name, category=""):
    """RSS 피드 크롤링"""
    try:
        feed = feedparser.parse(feed_url)
        source = f"{source_name}{category}"
        
        for entry in feed.entries[:20]:
            title = entry.get('title', '')
            link = entry.get('link', '')
            pub_date = entry.get('published_parsed')
            
            if not title or not link:
                continue
            
            # 중복 체크
            title_hash = get_title_hash(title)
            if link in sent_news or title_hash in title_hashes:
                continue
            
            # 최근 기사만 (10분 이내)
            if not is_recent(pub_date, minutes=10):
                continue
            
            # [속보] 최우선
            if "[속보]" in title or "속보" in title:
                await send_news(bot, "속보", title, link, source)
                sent_news.add(link)
                title_hashes.add(title_hash)
                save_data()
                await asyncio.sleep(1)
            
            # [단독]
            elif "[단독]" in title or "(단독)" in title:
                await send_news(bot, "단독", title, link, source)
                sent_news.add(link)
                title_hashes.add(title_hash)
                save_data()
                await asyncio.sleep(1)
            
            # [기획]
            elif "[기획]" in title or "(기획)" in title:
                await send_news(bot, "기획", title, link, source)
                sent_news.add(link)
                title_hashes.add(title_hash)
                save_data()
                await asyncio.sleep(1)
            
            # 여론조사
            elif "여론조사" in title:
                await send_news(bot, "여론조사", title, link, source)
                sent_news.add(link)
                title_hashes.add(title_hash)
                save_data()
                await asyncio.sleep(1)
                
    except Exception as e:
        print(f"❌ RSS 오류 ({source_name}): {e}")

async def fetch_all_rss(bot):
    """모든 RSS 피드 병렬 처리"""
    tasks = []
    
    # 연합뉴스
    for feed_url, category in RSS_FEEDS["연합뉴스"]:
        tasks.append(fetch_rss_feed(bot, feed_url, "연합뉴스", category))
    
    # 뉴시스
    tasks.append(fetch_rss_feed(bot, RSS_FEEDS["뉴시스"], "뉴시스"))
    
    # 한국경제
    for feed_url, category in RSS_FEEDS["한국경제"]:
        tasks.append(fetch_rss_feed(bot, feed_url, "한국경제", category))
    
    # 매일경제
    tasks.append(fetch_rss_feed(bot, RSS_FEEDS["매일경제"], "매일경제"))
    
    # 서울경제
    tasks.append(fetch_rss_feed(bot, RSS_FEEDS["서울경제"], "서울경제"))
    
    # 한겨레
    tasks.append(fetch_rss_feed(bot, RSS_FEEDS["한겨레"], "한겨레"))
    
    # 병렬 실행
    await asyncio.gather(*tasks)

async def fetch_naver_breaking(bot):
    """네이버 속보 (보조)"""
    try:
        sections = [("100", "정치"), ("101", "경제"), ("105", "IT")]
        
        for sid, name in sections:
            url = f"https://news.naver.com/section/{sid}"
            r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            
            articles = soup.select("div.sa_text a.sa_text_title")[:5]
            
            for article in articles:
                title = article.get_text(strip=True)
                link = article.get("href", "")
                
                if not link:
                    continue
                
                title_hash = get_title_hash(title)
                if link in sent_news or title_hash in title_hashes:
                    continue
                
                # [속보]만
                if "[속보]" in title:
                    await send_news(bot, "속보", title, link, f"네이버{name}")
                    sent_news.add(link)
                    title_hashes.add(title_hash)
                    save_data()
                    await asyncio.sleep(1)
                    
    except Exception as e:
        print(f"❌ 네이버: {e}")

async def main():
    print("🔥 누렁봇 PRO 버전!")
    print("📰 다중 언론사 RSS 병렬 모니터링")
    print("🔔 [속보] + 🎯 [단독] + 📋 [기획] + 📊 여론조사")
    print("📢 채널: @gazzzza2025")
    print("⏰ 1분마다 확인 (10분 이내 기사)\n")
    
    load_data()
    print(f"📝 저장된 뉴스: {len(sent_news)}개")
    print(f"📝 저장된 해시: {len(title_hashes)}개\n")
    
    bot = Bot(BOT_TOKEN)
    
    try:
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        await bot.send_message(
            CHAT_ID,
            f"🔥 <b>누렁봇 PRO</b>\n\n"
            f"⏰ {now}\n"
            f"📰 7개 언론사 RSS 실시간 모니터링\n"
            f"✅ 10분 이내 최신 기사만 전송\n"
            f"✅ 제목 해시 중복 방지",
            parse_mode="HTML"
        )
    except:
        pass
    
    while True:
        print(f"⏰ {datetime.now(KST).strftime('%H:%M:%S')} - RSS 병렬 확인 중...")
        
        # RSS 병렬 크롤링
        await fetch_all_rss(bot)
        
        # 네이버 보조
        await fetch_naver_breaking(bot)
        
        print("⏳ 1분 대기...\n")
        await asyncio.sleep(60)

asyncio.run(main())
