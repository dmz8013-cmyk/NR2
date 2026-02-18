import asyncio
from telegram import Bot
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = "7895248917:AAEoaBk8570354937:AAHzgqgVK88A7PYbfTEuP7jxPHhkUVAEXJs"
CHANNEL_ID = "@gazzzza2025"

async def test_bot():
    bot = Bot(BOT_TOKEN)
    
    # 1. 봇 테스트 메시지
    print("1️⃣ 텔레그램 연결 테스트 중...")
    try:
        await bot.send_message(CHANNEL_ID, "🤖 누렁봇 테스트 메시지입니다!")
        print("✅ 텔레그램 전송 성공!")
    except Exception as e:
        print(f"❌ 텔레그램 전송 실패: {e}")
        return
    
    # 2. 네이버 뉴스 크롤링 테스트
    print("\n2️⃣ 네이버 뉴스 크롤링 테스트 중...")
    for sid, name in [("100","정치"),("101","경제"),("102","사회")]:
        print(f"\n📰 {name} 섹션:")
        try:
            r = requests.get(f"https://news.naver.com/section/{sid}", 
                           headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            articles = soup.select("div.sa_text a.sa_text_title")[:5]
            
            for i, a in enumerate(articles, 1):
                title = a.get_text(strip=True)
                print(f"  {i}. {title}")
                
                # [속보] 있으면 전송
                if "[속보]" in title:
                    link = a.get("href","")
                    await bot.send_message(CHANNEL_ID, f"🔔 <b>속보</b>\n\n{title}\n\n🔗 {link}", parse_mode="HTML")
                    print(f"    ✅ 텔레그램 전송!")
                    
        except Exception as e:
            print(f"  ❌ 오류: {e}")

asyncio.run(test_bot())
