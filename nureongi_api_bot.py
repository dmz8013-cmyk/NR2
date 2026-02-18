import asyncio
from telegram import Bot
from datetime import datetime, timedelta
import requests
import pytz

BOT_TOKEN = "8591331989:AAEO0MuLnyFypcslPHMo8mWjW3LNy9BwejM"
CHAT_ID = "@gazzzza2025"
KST = pytz.timezone('Asia/Seoul')

# 네이버 API 키 (무료)
NAVER_CLIENT_ID = "YOUR_CLIENT_ID"  # 발급 필요
NAVER_CLIENT_SECRET = "YOUR_CLIENT_SECRET"  # 발급 필요

sent_news = set()

keywords = ["삼성전자", "SK하이닉스", "LG", "현대차", "AI", "챗GPT", "테슬라", 
            "엔비디아", "환율", "금리", "HBM", "반도체", "머스크", "애플",
            "이재명", "장동혁", "한동훈", "여론조사"]

async def send_news(bot, news_type, title, link, source):
    try:
        emoji_map = {
            "속보": "🔔",
            "단독": "🎯",
            "키워드": "📰",
        }
        emoji = emoji_map.get(news_type, "📰")
        
        message = f"{emoji} <b>{news_type}</b>\n\n{title}\n\n📰 {source}\n🔗 {link}"
        await bot.send_message(CHAT_ID, message, parse_mode="HTML")
        print(f"✅ [{news_type}] {title[:40]}...")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False

async def search_naver_news(query, bot):
    """네이버 뉴스 검색 API"""
    try:
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
        }
        params = {
            "query": query,
            "display": 10,  # 10개씩
            "sort": "date"  # 최신순
        }
        
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        
        if "items" not in data:
            return
        
        now = datetime.now(KST)
        one_hour_ago = now - timedelta(hours=1)
        
        for item in data["items"]:
            title = item["title"].replace("<b>", "").replace("</b>", "")
            link = item["link"]
            
            # 중복 체크
            if link in sent_news:
                continue
            
            # 발행 시간 파싱 (YYYYMMDD 형식)
            pub_date_str = item.get("pubDate", "")  # 예: "Mon, 17 Feb 2026 10:30:00 +0900"
            
            try:
                # pubDate를 datetime으로 변환
                from email.utils import parsedate_to_datetime
                pub_date = parsedate_to_datetime(pub_date_str)
                
                # 1시간 이내 기사만
                if pub_date < one_hour_ago:
                    continue
                    
            except:
                # 시간 파싱 실패하면 무시하고 계속
                pass
            
            # 속보/단독 체크
            if "[속보]" in title:
                await send_news(bot, "속보", title, link, "네이버뉴스")
                sent_news.add(link)
                await asyncio.sleep(1)
            elif "[단독]" in title or "(단독)" in title:
                await send_news(bot, "단독", title, link, "네이버뉴스")
                sent_news.add(link)
                await asyncio.sleep(1)
            else:
                await send_news(bot, "키워드", title, link, "네이버뉴스")
                sent_news.add(link)
                await asyncio.sleep(1)
                
    except Exception as e:
        print(f"❌ 검색 오류 [{query}]: {e}")

async def main():
    print("🔥 누렁봇 API 버전!")
    print("📰 네이버 검색 API 사용 (1시간 이내)")
    print("🔔 [속보] + 🎯 [단독] + 📰 키워드")
    print("📢 채널: @gazzzza2025")
    print("⏰ 1분마다 확인\n")
    
    bot = Bot(BOT_TOKEN)
    
    try:
        now = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
        await bot.send_message(
            CHAT_ID,
            f"🔥 <b>누렁봇 API 버전</b>\n\n"
            f"⏰ {now}\n"
            f"📰 1시간 이내 최신 뉴스만 전송",
            parse_mode="HTML"
        )
    except:
        pass
    
    while True:
        print(f"⏰ {datetime.now(KST).strftime('%H:%M:%S')} - 뉴스 검색 중...")
        
        # 주요 키워드로 검색
        for keyword in keywords[:10]:  # 상위 10개 키워드만
            await search_naver_news(keyword, bot)
            await asyncio.sleep(2)  # API 호출 간격
        
        print("⏳ 1분 대기...\n")
        await asyncio.sleep(60)

asyncio.run(main())
