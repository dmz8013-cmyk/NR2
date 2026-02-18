import asyncio
from telegram import Bot

BOT_TOKEN = "8591331989:AAEO0MuLnyFypcslPHMo8mWjW3LNy9BwejM"

async def test():
    bot = Bot(BOT_TOKEN)
    try:
        me = await bot.get_me()
        print(f"✅ 봇 연결 성공!")
        print(f"   이름: @{me.username}")
        
        updates = await bot.get_updates()
        if updates:
            for u in updates:
                if u.message:
                    chat_id = u.message.chat.id
                    print(f"   Chat ID: {chat_id}")
                    await bot.send_message(chat_id, "🤖 봇 테스트!")
                    print(f"✅ 메시지 전송 성공!")
                    
    except Exception as e:
        print(f"❌ 오류: {e}")

asyncio.run(test())
