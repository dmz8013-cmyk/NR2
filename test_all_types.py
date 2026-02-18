import asyncio
from telegram import Bot
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = "8591331989:AAEO0MuLnyFypcslPHMo8mWjW3LNy9BwejM"
CHAT_ID = 5132309076

async def test():
    bot = Bot(BOT_TOKEN)
    
    print("📰 [속보] + [단독] + [기획] + 여론조사 검색 중...\n")
    
    for sid, name in [("100","정치"),("101","경제"),("102","사회"),("104","국제")]:
        print(f"\n📂 {name} 섹션:")
        try:
            r = requests.get(f"https://news.naver.com/section/{sid}", 
                           headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            articles = soup.select("div.sa_text a.sa_text_title")[:10]
            
            for i, a in enumerate(articles, 1):
                title = a.get_text(strip=True)
                link = a.get("href","")
                
                if "[속보]" in title:
                    print(f"  🔔 속보: {title}")
                    await bot.send_message(CHAT_ID, f"🔔 <b>속보</b>\n\n{title}\n\n🔗 {link}", parse_mode="HTML")
                    await asyncio.sleep(1)
                    
                elif "[단독]" in title or "(단독)" in title:
                    print(f"  🎯 단독: {title}")
                    await bot.send_message(CHAT_ID, f"🎯 <b>단독</b>\n\n{title}\n\n🔗 {link}", parse_mode="HTML")
                    await asyncio.sleep(1)
                
                elif "[기획]" in title or "(기획)" in title:
                    print(f"  📋 기획: {title}")
                    await bot.send_message(CHAT_ID, f"📋 <b>기획</b>\n\n{title}\n\n🔗 {link}", parse_mode="HTML")
                    await asyncio.sleep(1)
                
                elif "여론조사" in title:
                    print(f"  📊 여론조사: {title}")
                    await bot.send_message(CHAT_ID, f"📊 <b>여론조사</b>\n\n{title}\n\n🔗 {link}", parse_mode="HTML")
                    await asyncio.sleep(1)
                    
                else:
                    print(f"  {i}. {title[:50]}...")
                    
        except Exception as e:
            print(f"  ❌ 오류: {e}")
    
    print("\n✅ 테스트 완료!")

asyncio.run(test())
