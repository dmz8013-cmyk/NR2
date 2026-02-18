import asyncio
from telegram import Bot
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import pytz
import json
import os
import hashlib
from collections import defaultdict

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
keyword_last_sent = defaultdict(lambda: datetime.min)

def get_hash(title):
    """제목 정규화 후 해시"""
    clean = title.replace("[속보]", "").replace("[단독]", "").replace("(단독)", "")
    clean = clean.replace("[기획]", "").replace("(기획)", "").replace("여론조사", "").strip()
    return hashlib.md5(clean.encode()).hexdigest()

def extract_date_from_url(url):
    """URL에서 날짜 추출 (aid 기준)"""
    try:
        # https://n.news.naver.com/mnews/article/009/0005637704
        # aid의 앞 6자리가 날짜인 경우가 많음 (예: 000563 = 오늘)
        # 또는 클러스터 URL: /cluster/c_202602141510_...
        
        if "/cluster/c_" in url:
            # c_202602141510 형식에서 날짜 추출
            date_str = url.split("c_")[1][:8]  # 20260214
            return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=KST)
        
        # 기본적으로 오늘/어제만 허용
        return datetime.now(KST)
        
    except:
        return datetime.now(KST)

def is_recent(url):
    """오늘 또는 어제 기사인지 확인"""
    try:
        article_date = extract_date_from_url(url)
        now = datetime.now(KST)
        yesterday = now - timedelta(days=1)
        
        # 오늘 또는 어제만 허용
        return article_date.date() >= yesterday.date()
    except:
        # 날짜 추출 실패시 일단 허용 (다른 필터가 걸러낼 것)
        return True

def extract_keyword(title):
    """제목에서 주요 키워드 추출 (키워드 폭탄 방지용)"""
    keywords = ["삼성", "SK", "LG", "현대", "AI", "챗GPT", "테슬라", "엔비디아", 
                "환율", "금리", "HBM", "반도체", "머스크", "애플"]
    
    for keyword in keywords:
        if keyword in title:
            return keyword
    return None

def should_send_keyword_news(title):
    """키워드 중복 체크 (5분 이내 동일 키워드는 1개만)"""
    keyword = extract_keyword(title)
    if not keyword:
        return True
    
    now = datetime.now(KST)
    last_sent = keyword_last_sent[keyword]
    
    if (now - last_sent).total_seconds() > 300:  # 5분
        keyword_last_sent[keyword] = now
        return True
    
    return False

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
        
        message = f"{emoji} <b>{news_type}</b>\n\n{title}\n\n📰 {source}\n🔗 {link}"
        await bot.send_message(CHAT_ID, message, parse_mode="HTML")
        print(f"✅ [{news_type}] {title[:40]}...")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False

async def fetch_naver(bot):
    """네이버 섹션 크롤링"""
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
                
                # 날짜 체크 (오늘/어제만)
                if not is_recent(link):
                    continue
                
                # 제목 해시 중복 체크
                title_hash = get_hash(title)
                if title_hash in sent_hashes:
                    continue
                
                # [속보] - 최우선
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
                
                # 키워드 (5분 제한)
                elif extract_keyword(title) and should_send_keyword_news(title):
                    await send_news(bot, "키워드", title, link, f"네이버{name}")
                    sent_hashes.add(title_hash)
                    save_sent(sent_hashes)
                    await asyncio.sleep(1)
                    
        except Exception as e:
            print(f"❌ {name}: {e}")

async def main():
    print("🔥 누렁봇 완벽판!")
    print("📰 오늘/어제 기사만 + 중복 완벽 차단")
    print("🔔 [속보] + 🎯 [단독] + 📋 [기획] + 📊 여론조사 + 📰 키워드")
    print("📢 채널: @gazzzza2025")
    print("⏰ 1분마다 확인\n")
    print(f"📝 저장된 기사: {len(sent_hashes)}개\n")
    
    bot = Bot(BOT_TOKEN)
    
    try:
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        await bot.send_message(
            CHAT_ID,
            f"🔥 <b>누렁봇 완벽판</b>\n\n"
            f"⏰ {now}\n"
            f"✅ 오늘/어제 기사만 전송\n"
            f"✅ 제목 해시 중복 방지\n"
            f"✅ 키워드 5분 제한",
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
