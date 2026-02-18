import asyncio
from telegram import Bot
from datetime import datetime
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = "7895248917:AAEoaBk8570354937:AAHzgqgVK88A7PYbfTEuP7jxPHhkUVAEXJs"
CHANNEL_ID = "@gazzzza2025"
sent_news = set()

async def send_news(bot, title, link):
    try:
        await bot.send_message(CHANNEL_ID, f"🔔 <b>속보</b>\n\n{title}\n\n🔗 {link}", parse_mode="HTML")
        print(f"✅ {title[:50]}")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False

async def fetch_news():
    bot = Bot(BOT_TOKEN)
    for sid, name in [("100","정치"),("101","경제"),("102","사회"),("104","국제")]:
        try:
            r = requests.get(f"https://news.naver.com/section/{sid}", headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("div.sa_text a.sa_text_title")[:10]:
                title, link = a.get_text(strip=True), a.get("href","")
                if "[속보]" in title and link not in sent_news:
                    await send_news(bot, title, link)
                    sent_news.add(link)
                    await asyncio.sleep(2)
        except Exception as e:
            print(f"❌ {name}: {e}")

async def main():
    print("🤖 누렁봇 시작!")
    print("⏰ 10분마다 확인\n")
    while True:
        await fetch_news()
        print("⏳ 10분 대기...\n")
        await asyncio.sleep(600)

asyncio.run(main())
