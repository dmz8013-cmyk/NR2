"""텔레그램 알림 유틸리티"""
import os
import requests

def send_telegram_message(text):
    """텔레그램 채널에 메시지 전송"""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        return False
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.ok
    except Exception as e:
        print(f"텔레그램 전송 실패: {str(e)}")
        return False

def notify_new_post(post):
    """새 게시글 알림"""
    board_names = {
        'free': '자유게시판',
        'left': 'LEFT',
        'right': 'RIGHT',
        'fakenews': '팩트체크',
        'morpheus': '모피어스뉴스',
        'aesa': '누렁이 AESA',
    }
    board_name = board_names.get(post.board_type, post.board_type)
    
    text = (
        f"🐕 <b>NR2 새 글 알림</b>\n\n"
        f"📌 게시판: {board_name}\n"
        f"✏️ 제목: {post.title}\n"
        f"👤 작성자: {post.author.nickname}\n\n"
        f"🔗 https://nr2.kr/boards/{post.board_type}/{post.id}"
    )
    return send_telegram_message(text)
