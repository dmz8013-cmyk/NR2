import asyncio
from telegram import Bot
from datetime import datetime, timedelta
import feedparser
import pytz

BOT_TOKEN = "8591331989:AAEO0MuLnyFypcslPHMo8mWjW3LNy9BwejM"
CHAT_ID = "@gazzzza2025"
sent_news = set()

KST = pytz.timezone('Asia/Seoul')

# 연합뉴스 RSS 피드
FEEDS = {
    "속보": "https://www.yonhapnewstv.co.kr/browse/feed/",
    "정치": "https://www.yna.co.kr/rss/politics.xml",
    "경제": "https://www.yna.co.kr/rss/economy.xml",
    "사회": "https://www.yna.co.kr/rss/society.xml",
    "국제": "https://www.yna.co.kr/rss/international.xml",
}

async def send_news(bot, news_type, title, link, pub_date):
    try:
        emoji_map = {
            "속보": "🔔",
            "단독": "🎯",
            "기획": "📋",
            "여론조사": "📊"
        }
        emoji = emoji_map.get(news_type, "📰")
        
        message = f"{emoji} <b>{news_type}</b>\n\n{title}\n\n🕐 {pub_date}\n🔗 {link}"
        await bot.send_message(CHAT_ID, message, parse_mode="HTML")
        print(f"✅ [{news_type}] {title[:40]}...")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False

def is_recent(published_parsed, minutes=5):
    """최근 N분 이내 기사인지 확인"""
    try:
        from time import mktime
        pub_time = datetime.fromtimestamp(mktime(published_parsed), tz=KST)
        now = datetime.now(KST)
        diff = (now - pub_time).total_seconds() / 60
        return diff <= minutes
    except:
        return False

async def fetch_news():
    bot = Bot(BOT_TOKEN)
    
    for feed_name, feed_url in FEEDS.items():
        try:
            print(f"📰 {feed_name} 피드 확인 중...")
            feed = feedparser.parse(feed_url)
            
            for entry in feed.entries[:10]:
                title = entry.title
                link = entry.link
                
                # 중복 체크
                if link in sent_news:
                    continue
                
                # 시간 체크 (최근 5분 이내)
                if hasattr(entry, 'published_parsed'):
                    if not is_recent(entry.published_parsed, minutes=5):
                        continue
                
                # 발행 시간
                pub_date = ""
                if hasattr(entry, 'published'):
                    pub_date = entry.published
                
                # 키워드 체크
                if "[속보]" in title or "속보" in title:
                    await send_news(bot, "속보", title, link, pub_date)
                    sent_news.add(link)
                    await asyncio.sleep(2)
                
                elif "[단독]" in title or "(단독)" in title:
                    await send_news(bot, "단독", title, link, pub_date)
                    sent_news.add(link)
                    await asyncio.sleep(2)
                
                elif "[기획]" in title or "(기획)" in title:
                    await send_news(bot, "기획", title, link, pub_date)
                    sent_news.add(link)
                    await asyncio.sleep(2)
                
                elif "여론조사" in title:
                    await send_news(bot, "여론조사", title, link, pub_date)
                    sent_news.add(link)
                    await asyncio.sleep(2)
                    
        except Exception as e:
            print(f"❌ {feed_name}: {e}")

async def main():
    print("🤖 누렁봇 실시간 속보 시작!")
    print("📰 연합뉴스 RSS 피드 모니터링")
    print("🔔 [속보] + 🎯 [단독] + 📋 [기획] + 📊 여론조사")
    print("📢 채널: @gazzzza2025")
    print("⏰ 1분마다 확인 (5분 이내 기사만!)\n")
    
    # 시작 알림
    bot = Bot(BOT_TOKEN)
    try:
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        await bot.send_message(
            CHAT_ID, 
            f"🤖 <b>누렁봇 재시작</b>\n\n"
            f"⏰ {now}\n"
            f"📰 연합뉴스 RSS 실시간 모니터링\n"
            f"✅ 5분 이내 기사만 전송합니다.",
            parse_mode="HTML"
        )
    except:
        pass
    
    while True:
        print(f"⏰ {datetime.now(KST).strftime('%H:%M:%S')} - 피드 확인 중...")
        await fetch_news()
        print("⏳ 1분 대기...\n")
        await asyncio.sleep(60)

asyncio.run(main())
