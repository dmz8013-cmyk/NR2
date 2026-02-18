import asyncio
from telegram import Bot
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import pytz
import json
import os
import hashlib

BOT_TOKEN = "8591331989:AAEO0MuLnyFypcslPHMo8mWjW3LNy9BwejM"
CHAT_ID = "@gazzzza2025"

SENT_FILE = "sent_news.json"
KST = pytz.timezone('Asia/Seoul')

# 영구 저장
def load_sent():
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, 'r') as f:
            data = json.load(f)
            return set(data.get('hashes', []))
    return set()

def save_sent(hashes):
    with open(SENT_FILE, 'w') as f:
        json.dump({'hashes': list(hashes)}, f)

sent_hashes = load_sent()

def get_hash(title):
    """제목 정규화 후 해시"""
    clean = title.replace("[속보]", "").replace("[단독]", "").replace("(단독)", "")
    clean = clean.replace("[기획]", "").replace("(기획)", "").strip()
    return hashlib.md5(clean.encode()).hexdigest()

def is_today(title, link):
    """오늘 기사인지 확인 (URL 날짜 체크)"""
    now = datetime.now(KST)
    today = now.strftime('%Y%m%d')
    
    # URL에서 날짜 추출 시도
    if today in link:
        return True
    
    # 제목에 "오늘", "오후", "오전" 등 있으면 OK
    time_keywords = ["오늘", "오후", "오전", "방금", "금일"]
    if any(kw in title for kw in time_keywords):
        return True
    
    return False

async def send_news(bot, news_type, title, link, source):
    try:
        emoji_map = {
            "속보": "🔔",
            "단독": "🎯", 
            "기획": "📋",
            "여론조사": "📊"
        }
        emoji = emoji_map.get(news_type, "📰")
        
        message = f"{emoji} <b>{news_type}</b>\n\n{title}\n\n📰 {source}\n🔗 {link}"
        await bot.send_message(CHAT_ID, message, parse_mode="HTML")
        print(f"✅ [{news_type}] {title[:40]}...")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False

async def fetch_naver(bot):
    """네이버 섹션 - 속보/단독/기획/여론조사만"""
    sections = [
        ("100", "정치"),
        ("101", "경제"),
        ("102", "사회"),
        ("104", "국제"),
        ("105", "IT"),
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
                
                if not link:
                    continue
                
                # 제목 해시 중복 체크
                title_hash = get_hash(title)
                if title_hash in sent_hashes:
                    continue
                
                # 오늘 기사인지 확인
                if not is_today(title, link):
                    continue
                
                # [속보]
                if "[속보]" in title:
                    await send_news(bot, "속보", title, link, f"네이버{name}")
                    sent_hashes.add(title_hash)
                    save_sent(sent_hashes)
                    await asyncio.sleep(1)
                
                # [단독]
                elif "[단독]" in title or "(단독)" in title:
                    await send_news(bot, "단독", title, link, f"네이버{name}")
                    sent_hashes.add(title_hash)
                    save_sent(sent_hashes)
                    await asyncio.sleep(1)
                
                # [기획]
                elif "[기획]" in title or "(기획)" in title:
                    await send_news(bot, "기획", title, link, f"네이버{name}")
                    sent_hashes.add(title_hash)
                    save_sent(sent_hashes)
                    await asyncio.sleep(1)
                
                # 여론조사
                elif "여론조사" in title:
                    await send_news(bot, "여론조사", title, link, f"네이버{name}")
                    sent_hashes.add(title_hash)
                    save_sent(sent_hashes)
                    await asyncio.sleep(1)
                    
        except Exception as e:
            print(f"❌ {name}: {e}")

async def main():
    print("🔥 누렁봇 진짜 실시간!")
    print("📰 오늘 기사만 + 중복 완벽 차단")
    print("🔔 [속보] + 🎯 [단독] + 📋 [기획] + 📊 여론조사")
    print("📢 채널: @gazzzza2025")
    print("⏰ 1분마다 확인\n")
    print(f"📝 저장된 기사: {len(sent_hashes)}개\n")
    
    bot = Bot(BOT_TOKEN)
    
    try:
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        await bot.send_message(
            CHAT_ID,
            f"🔥 <b>누렁봇 실시간 재시작</b>\n\n"
            f"⏰ {now}\n"
            f"✅ 오늘 기사만 전송\n"
            f"✅ 제목 해시 중복 방지\n"
            f"✅ URL 날짜 필터링",
            parse_mode="HTML"
        )
    except:
        pass
    
    while True:
        print(f"⏰ {datetime.now(KST).strftime('%H:%M:%S')} - 뉴스 확인 중...")
        await fetch_naver(bot)
        print("⏳ 1분 대기...\n")
        await asyncio.sleep(60)

asyncio.run(main())
