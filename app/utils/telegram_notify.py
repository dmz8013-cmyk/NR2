"""텔레그램 알림 유틸리티"""
import os
import requests


def send_telegram_message(text, chat_id=None):
    """텔레그램 채널에 메시지 전송"""
    token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = chat_id or os.environ.get('TELEGRAM_CHAT_ID')

    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': False,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.ok
    except Exception as e:
        print(f"텔레그램 전송 실패: {str(e)}")
        return False


def send_to_channel(text):
    """공개 채널(@gazzzza2025)에 메시지 전송"""
    return send_telegram_message(text, chat_id='@gazzzza2025')


def notify_new_post(post):
    """새 게시글 알림 — 개인 + 채널 동시 발송"""
    board_names = {
        'free': '자유게시판',
        'left': 'LEFT',
        'right': 'RIGHT',
        'fakenews': '팩트체크',
        'morpheus': '모피어스뉴스',
        'aesa': '누렁이 AESA',
    }
    board_name = board_names.get(post.board_type, post.board_type)

    # 개인 알림 (기존)
    admin_text = (
        f"🐕 <b>NR2 새 글 알림</b>\n\n"
        f"📌 게시판: {board_name}\n"
        f"✏️ 제목: {post.title}\n"
        f"👤 작성자: {post.author.nickname}\n\n"
        f"🔗 https://nr2.kr/boards/{post.board_type}/{post.id}"
    )
    send_telegram_message(admin_text)

    # 채널 발송 (새 형식)
    channel_text = (
        f"🔥 <b>[{board_name}] 새 글</b>\n\n"
        f"📝 제목: {post.title}\n"
        f"👤 작성자: 익명 시민\n\n"
        f"💬 댓글 달고 NP 받기 👇\n"
        f"🔗 https://nr2.kr/boards/{post.board_type}/{post.id}"
    )
    return send_to_channel(channel_text)
