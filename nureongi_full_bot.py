import asyncio
from telegram import Bot
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import pytz

BOT_TOKEN = "8591331989:AAEO0MuLnyFypcslPHMo8mWjW3LNy9BwejM"
CHAT_ID = "@gazzzza2025"
sent_news = set()

KST = pytz.timezone('Asia/Seoul')

async def send_news(bot, news_type, title, link, pub_time):
    try:
        emoji_map = {
            "속보": "🔔",
            "단독": "🎯",
            "기획": "📋",
            "여론조사": "📊"
        }
        emoji = emoji_map.get(news_type, "📰")
        
        message = f"{emoji} <b>{news_type}</b>\n\n{title}\n\n🕐 {pub_time}\n🔗 {link}"
        await bot.send_message(CHAT_ID, message, parse_mode="HTML")
        print(f"✅ [{news_type}] {title[:40]}... ({pub_time})")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False

def is_within_1_minute(time_text):
    """1분 이내 기사인지 확인"""
    try:
        # "N분 전" 형식만 허용
        if "분 전" in time_text:
            minutes = int(time_text.replace("분 전", "").strip())
            return minutes <= 1  # 1분 이내만!
        
        # "방금" 또는 "1분 이내" 같은 표현
        if "방금" in time_text or "지금" in time_text:
            return True
        
        # 그 외는 모두 제외
        return False
        
    except:
        return False

async def fetch_news():
    bot = Bot(BOT_TOKEN)
    
    sections = [
        ("100", "정치"),
        ("101", "경제"),
        ("102", "사회"),
        ("104", "국제")
    ]
    
    for sid, name in sections:
        try:
            r = requests.get(
                f"https://news.naver.com/section/{sid}", 
                headers={"User-Agent":"Mozilla/5.0"}, 
                timeout=10
            )
            soup = BeautifulSoup(r.text, "html.parser")
            
            articles = soup.select("div.sa_text")[:10]
            
            for article in articles:
                title_elem = article.select_one("a.sa_text_title")
                if not title_elem:
                    continue
                
                title = title_elem.get_text(strip=True)
                link = title_elem.get("href", "")
                
                # 시간 정보
                time_elem = article.select_one("div.sa_text_time")
                time_text = time_elem.get_text(strip=True) if time_elem else ""
                
                # 중복 체크
                if link in sent_news:
                    continue
                
                # 1분 이내 기사만!
                if not is_within_1_minute(time_text):
                    continue
                
                # 키워드 체크
                if "[속보]" in title:
                    await send_news(bot, "속보", title, link, time_text)
                    sent_news.add(link)
                    await asyncio.sleep(2)
                
                elif "[단독]" in title or "(단독)" in title:
                    await send_news(bot, "단독", title, link, time_text)
                    sent_news.add(link)
                    await asyncio.sleep(2)
                
                elif "[기획]" in title or "(기획)" in title:
                    await send_news(bot, "기획", title, link, time_text)
                    sent_news.add(link)
                    await asyncio.sleep(2)
                
                elif "여론조사" in title:
                    await send_news(bot, "여론조사", title, link, time_text)
                    sent_news.add(link)
                    await asyncio.sleep(2)
                    
        except Exception as e:
            print(f"❌ {name}: {e}")

async def main():
    print("🤖 누렁봇 시작!")
    print("🔔 [속보] + 🎯 [단독] + 📋 [기획] + 📊 여론조사")
    print("📢 채널: @gazzzza2025")
    print("⏰ 1분마다 확인 (1분 이내 기사만!)\n")
    
    # 시작 알림
    bot = Bot(BOT_TOKEN)
    try:
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        await bot.send_message(
            CHAT_ID, 
            f"🤖 <b>누렁봇 재시작</b>\n\n"
            f"⏰ {now}\n"
            f"✅ 1분 이내 기사만 전송합니다.",
            parse_mode="HTML"
        )
    except:
        pass
    
    while True:
        print(f"⏰ {datetime.now(KST).strftime('%H:%M:%S')} - 뉴스 확인 중...")
        await fetch_news()
        print("⏳ 1분 대기...\n")
        await asyncio.sleep(60)  # 1분마다!

asyncio.run(main())
