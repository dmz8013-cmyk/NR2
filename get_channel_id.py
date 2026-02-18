import asyncio
from telegram import Bot

BOT_TOKEN = "7895248917:AAEoaBk8570354937:AAHzgqgVK88A7PYbfTEuP7jxPHhkUVAEXJs"

async def get_updates():
    bot = Bot(BOT_TOKEN)
    try:
        # 봇 정보 확인
        me = await bot.get_me()
        print(f"✅ 봇 이름: {me.username}")
        print(f"✅ 봇 ID: {me.id}")
        
        # 업데이트 가져오기
        updates = await bot.get_updates()
        print(f"\n📬 최근 메시지: {len(updates)}개")
        
        for update in updates:
            if update.channel_post:
                chat = update.channel_post.chat
                print(f"\n📢 채널 발견!")
                print(f"   이름: {chat.title}")
                print(f"   ID: {chat.id}")
                print(f"   Username: @{chat.username if chat.username else 'N/A'}")
                
    except Exception as e:
        print(f"❌ 오류: {e}")

asyncio.run(get_updates())
