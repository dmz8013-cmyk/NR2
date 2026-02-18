import asyncio
from telegram import Bot
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import pytz
import re

BOT_TOKEN = "8591331989:AAEO0MuLnyFypcslPHMo8mWjW3LNy9BwejM"
CHAT_ID = "@gazzzza2025"
KST = pytz.timezone('Asia/Seoul')

sent_news = set()
last_article_ids = {}  # 언론사별 마지막 기사 번호 추적

keywords = ["삼성", "SK", "LG", "현대", "AI", "챗GPT", "테슬라", "엔비디아", 
            "환율", "금리", "HBM", "반도체", "머스크", "애플", "코스피",
            "이재명", "장동혁", "한동훈", "민주당", "국민의힘"]

async def send_news(bot, news_type, title, link, source):
    try:
        emoji_map = {
            "속보": "🔔",
            "단독": "🎯",
            "기획": "📋",
            "여론조사": "📊",
            "키워드": "📰"
        }
        emoji = emoji_map.get(news_type, "📰")
        
        message = f"{emoji} <b>{news_type}</b>\n\n{title}\n\n🔗 {link}"
        await bot.send_message(CHAT_ID, message, parse_mode="HTML")
        print(f"✅ [{news_type}] {title[:40]}...")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False

def extract_article_id(url):
    """URL에서 기사 번호 추출"""
    try:
        # https://n.news.naver.com/mnews/article/003/0013771010
        match = re.search(r'/article/(\d+)/(\d+)', url)
        if match:
            press_id = match.group(1)
            article_id = int(match.group(2))
            return press_id, article_id
    except:
        pass
    return None, 0

def is_recent_article(url):
    """기사가 최근 것인지 확인 (기사번호 기반)"""
    press_id, article_id = extract_article_id(url)
    
    if not press_id:
        return True  # URL 파싱 실패하면 일단 통과
    
    # 첫 실행이거나 해당 언론사 첫 기사면 기준값 설정
    if press_id not in last_article_ids:
        last_article_ids[press_id] = article_id
        return True
    
    # 이전 기사번호보다 크면 (= 최신이면) True
    if article_id > last_article_ids[press_id]:
        last_article_ids[press_id] = article_id
        return True
    
    # 기사번호 차이가 100 이내면 통과 (같은 시간대)
    if article_id >= last_article_ids[press_id] - 100:
        return True
    
    return False

def extract_keyword(title):
    """제목에서 키워드 추출"""
    for keyword in keywords:
        if keyword in title:
            return keyword
    return None

async def fetch_naver(bot):
    """네이버 섹션별 크롤링"""
    sections = [
        ("100", "정치"),
        ("101", "경제"),
        ("102", "사회"),
        ("104", "국제"),
        ("105", "IT과학")
    ]
    
    for sid, name in sections:
        try:
            r = requests.get(
                f"https://news.naver.com/section/{sid}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10
            )
            soup = BeautifulSoup(r.text, "html.parser")
            
            for a in soup.select("div.sa_text a.sa_text_title")[:15]:  # 15개로 증가
                title = a.get_text(strip=True)
                link = a.get("href", "")
                
                if not link or link in sent_news:
                    continue
                
                # ⭐ 핵심: 최근 기사만 필터링
                if not is_recent_article(link):
                    continue
                
                # [속보]
                if "[속보]" in title:
                    await send_news(bot, "속보", title, link, f"네이버{name}")
                    sent_news.add(link)
                    await asyncio.sleep(1)
                
                # [단독]
                elif "[단독]" in title or "(단독)" in title:
                    await send_news(bot, "단독", title, link, f"네이버{name}")
                    sent_news.add(link)
                    await asyncio.sleep(1)
                
                # [기획]
                elif "[기획]" in title or "(기획)" in title:
                    await send_news(bot, "기획", title, link, f"네이버{name}")
                    sent_news.add(link)
                    await asyncio.sleep(1)
                
                # 여론조사
                elif "여론조사" in title:
                    await send_news(bot, "여론조사", title, link, f"네이버{name}")
                    sent_news.add(link)
                    await asyncio.sleep(1)
                
                # 키워드
                elif extract_keyword(title):
                    await send_news(bot, "키워드", title, link, f"네이버{name}")
                    sent_news.add(link)
                    await asyncio.sleep(1)
        
        except Exception as e:
            print(f"❌ {name}: {e}")

async def main():
    print("🔥 누렁봇 스마트 버전!")
    print("📰 기사번호 기반 최신 필터링")
    print("🔔 [속보] + 🎯 [단독] + 📋 [기획] + 📊 여론조사 + 📰 키워드")
    print("📢 채널: @gazzzza2025")
    print("⏰ 30초마다 확인\n")
    
    bot = Bot(BOT_TOKEN)
    
    try:
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        await bot.send_message(
            CHAT_ID,
            f"🔥 <b>누렁봇 스마트 버전</b>\n\n"
            f"⏰ {now}\n"
            f"📰 기사번호 기반 최신 필터링\n"
            f"✅ 30초마다 실시간 체크",
            parse_mode="HTML"
        )
    except:
        pass
    
    while True:
        print(f"⏰ {datetime.now(KST).strftime('%H:%M:%S')} - 뉴스 확인 중...")
        await fetch_naver(bot)
        print("⏳ 30초 대기...\n")
        await asyncio.sleep(30)  # 30초마다!

asyncio.run(main())
