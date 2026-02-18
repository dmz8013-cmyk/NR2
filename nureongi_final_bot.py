import asyncio
from telegram import Bot
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import pytz
import json
import os

BOT_TOKEN = "8591331989:AAEO0MuLnyFypcslPHMo8mWjW3LNy9BwejM"
CHAT_ID = "@gazzzza2025"

# 중복 방지용 파일 저장
SENT_NEWS_FILE = "sent_news.json"

KST = pytz.timezone('Asia/Seoul')

# 전송한 뉴스 영구 저장
def load_sent_news():
    if os.path.exists(SENT_NEWS_FILE):
        with open(SENT_NEWS_FILE, 'r') as f:
            return set(json.load(f))
    return set()

def save_sent_news(sent_news):
    with open(SENT_NEWS_FILE, 'w') as f:
        json.dump(list(sent_news), f)

sent_news = load_sent_news()

async def send_news(bot, news_type, title, link, source=""):
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
        print(f"❌ {e}")
        return False

async def fetch_naver_sections(bot):
    """네이버 섹션별 - 속보/단독/기획/여론조사만"""
    sections = [
        ("100", "정치"),
        ("101", "경제"),
        ("102", "사회"),
        ("104", "국제"),
        ("105", "IT과학"),
    ]
    
    for sid, name in sections:
        try:
            url = f"https://news.naver.com/section/{sid}"
            r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            
            articles = soup.select("div.sa_text a.sa_text_title")[:10]
            
            for article in articles:
                title = article.get_text(strip=True)
                link = article.get("href", "")
                
                if not link or link in sent_news:
                    continue
                
                # [속보] 우선
                if "[속보]" in title:
                    await send_news(bot, "속보", title, link, f"네이버{name}")
                    sent_news.add(link)
                    save_sent_news(sent_news)
                    await asyncio.sleep(1)
                
                # [단독] / (단독)
                elif "[단독]" in title or "(단독)" in title:
                    await send_news(bot, "단독", title, link, f"네이버{name}")
                    sent_news.add(link)
                    save_sent_news(sent_news)
                    await asyncio.sleep(1)
                
                # [기획] / (기획)
                elif "[기획]" in title or "(기획)" in title:
                    await send_news(bot, "기획", title, link, f"네이버{name}")
                    sent_news.add(link)
                    save_sent_news(sent_news)
                    await asyncio.sleep(1)
                
                # 여론조사
                elif "여론조사" in title:
                    await send_news(bot, "여론조사", title, link, f"네이버{name}")
                    sent_news.add(link)
                    save_sent_news(sent_news)
                    await asyncio.sleep(1)
                    
        except Exception as e:
            print(f"❌ {name}: {e}")

async def fetch_naver_main(bot):
    """네이버 메인 헤드라인 - 속보만"""
    try:
        url = "https://news.naver.com/"
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        
        headlines = soup.select("a.cjs_news_tw, a.cjs_t")[:20]
        
        for headline in headlines:
            title = headline.get_text(strip=True)
            link = headline.get("href", "")
            
            if not link or link in sent_news:
                continue
            
            if not link.startswith("http"):
                link = "https://news.naver.com" + link
            
            # [속보]만
            if "[속보]" in title:
                await send_news(bot, "속보", title, link, "네이버메인")
                sent_news.add(link)
                save_sent_news(sent_news)
                await asyncio.sleep(1)
                
    except Exception as e:
        print(f"❌ 네이버메인: {e}")

async def main():
    print("🤖 누렁봇 최종판!")
    print("📰 네이버 실시간 모니터링")
    print("🔔 [속보] + 🎯 [단독] + 📋 [기획] + 📊 여론조사")
    print("📢 채널: @gazzzza2025")
    print("⏰ 1분마다 확인\n")
    print(f"📝 저장된 뉴스: {len(sent_news)}개\n")
    
    bot = Bot(BOT_TOKEN)
    
    try:
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        await bot.send_message(
            CHAT_ID, 
            f"🤖 <b>누렁봇 최종판</b>\n\n"
            f"⏰ {now}\n"
            f"📰 네이버 실시간 [속보] [단독] [기획] 여론조사\n"
            f"✅ 중복 방지 시스템 활성화",
            parse_mode="HTML"
        )
    except:
        pass
    
    while True:
        print(f"⏰ {datetime.now(KST).strftime('%H:%M:%S')} - 뉴스 확인 중...")
        
        # 네이버 메인 (속보만)
        await fetch_naver_main(bot)
        
        # 네이버 섹션별 (속보/단독/기획/여론조사)
        await fetch_naver_sections(bot)
        
        print("⏳ 1분 대기...\n")
        await asyncio.sleep(60)

asyncio.run(main())
