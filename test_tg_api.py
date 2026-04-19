import os, requests
BOT_TOKEN = "test:123" 
url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMessages"
r = requests.post(url, json={"chat_id": "@nr2aesa", "message_ids": [1]})
print(r.json())
