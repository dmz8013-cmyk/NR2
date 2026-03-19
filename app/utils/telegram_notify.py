"""텔레그램 알림 유틸리티 — 게시판별 맞춤 포맷"""
import os
import re
import requests


def send_telegram_message(text, chat_id=None):
    """텔레그램 메시지 전송 (chat_id 명시 필수)"""
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


def send_to_admin(text):
    """관리자 개인 DM 전송 (채널과 분리)"""
    admin_chat_id = os.environ.get('TELEGRAM_ADMIN_CHAT_ID', '5132309076')
    return send_telegram_message(text, chat_id=admin_chat_id)


# ── 게시판명 매핑 ──
BOARD_DISPLAY = {
    'free': '자유게시판',
    'left': 'LEFT',
    'right': 'RIGHT',
    'fakenews': '팩트체크',
    'morpheus': '모피어스뉴스',
    'aesa': '누렁이 AESA',
    'pick': '누렁이 픽',
    'lounge_media': '언론인 라운지',
    'lounge_congress': '국회 라운지',
    'lounge_govt': '정부 라운지',
    'lounge_corp': '기업 라운지',
    'lounge_public': '행인 광장',
    'lounge_bamboo': '대나무숲',
}

LOUNGE_BADGES = {
    'lounge_media': '익명·언론인',
    'lounge_congress': '익명·국회',
    'lounge_govt': '익명·정부',
    'lounge_corp': '익명·기업',
    'lounge_public': '익명·행인',
    'lounge_bamboo': '익명',
}


def _strip_html(html):
    """HTML 태그 제거, 100자 자르기"""
    text = re.sub(r'<[^>]+>', '', html or '').strip()
    return text[:100] + '...' if len(text) > 100 else text


def _format_lounge(post, board_name):
    """라운지 익명글 포맷"""
    badge = LOUNGE_BADGES.get(post.board_type, '익명')
    return (
        f"💬 <b>[{board_name}] 새 글</b>\n\n"
        f"[{badge}]: {post.title}\n\n"
        f"댓글 달러 가기 → https://nr2.kr/boards/{post.board_type}/{post.id}"
    )


def _format_pick(post, board_name):
    """누렁이 픽 포맷"""
    snippet = _strip_html(post.content)
    ext_url = post.external_url or f'https://nr2.kr/boards/pick/{post.id}'
    lines = [
        f"🎬 <b>[누렁이 픽] {post.title}</b>\n",
    ]
    if snippet:
        lines.append(f"누렁이 한마디: {snippet}\n")
    lines.append(f"바로 보기 → {ext_url}")
    lines.append(f"nr2.kr 토론 → https://nr2.kr/boards/pick/{post.id}")
    return "\n".join(lines)


def _format_morpheus(post, board_name):
    """모피어스 뉴스 포맷"""
    snippet = _strip_html(post.content)
    return (
        f"📰 <b>[모피어스뉴스] {post.title}</b>\n\n"
        f"{snippet}\n\n"
        f"nr2.kr에서 전체 보기 → https://nr2.kr/boards/morpheus/{post.id}"
    )


def _format_default(post, board_name):
    """기본 게시글 포맷"""
    return (
        f"🔥 <b>[{board_name}] 새 글</b>\n\n"
        f"📝 {post.title}\n"
        f"👤 익명 시민\n\n"
        f"💬 댓글 달고 NP 받기 👇\n"
        f"🔗 https://nr2.kr/boards/{post.board_type}/{post.id}"
    )


def notify_new_post(post):
    """새 게시글 알림 — 관리자 DM + 채널 동시 발송 (게시판별 포맷)"""
    board_name = BOARD_DISPLAY.get(post.board_type, post.board_type)
    is_lounge = post.board_type.startswith('lounge_')

    # ── 관리자 개인 DM (채널과 분리, 모든 게시판 상세 정보) ──
    admin_text = (
        f"🐕 <b>NR2 새 글 알림</b>\n\n"
        f"📌 게시판: {board_name}\n"
        f"✏️ 제목: {post.title}\n"
        f"👤 작성자: {post.author.nickname}\n\n"
        f"🔗 https://nr2.kr/boards/{post.board_type}/{post.id}"
    )
    send_to_admin(admin_text)

    # ── 라운지 익명글: 관리자에게 별도 알림 ──
    if is_lounge:
        lounge_admin = (
            f"🔔 <b>[라운지 익명글]</b>\n"
            f"게시판: {board_name}\n"
            f"제목: {post.title}\n"
            f"작성자(내부): {post.author.nickname}\n"
            f"🔗 https://nr2.kr/boards/{post.board_type}/{post.id}"
        )
        send_to_admin(lounge_admin)

    # ── 채널 발송 (게시판별 포맷) ──
    if is_lounge:
        channel_text = _format_lounge(post, board_name)
    elif post.board_type == 'pick':
        channel_text = _format_pick(post, board_name)
    elif post.board_type == 'morpheus':
        channel_text = _format_morpheus(post, board_name)
    else:
        channel_text = _format_default(post, board_name)

    return send_to_channel(channel_text)


def notify_new_briefing(briefing):
    """새 AI 브리핑 알림 — 채널 발송"""
    type_names = {
        'ai_morning': '🌅 아침 AI 브리핑',
        'ai_evening': '🌆 저녁 AI 브리핑',
        'political_afternoon': '🏛️ 오후 정치 브리핑',
        'political_evening': '🏛️ 저녁 정치 브리핑',
    }
    type_name = type_names.get(briefing.briefing_type, '📰 AI 브리핑')
    snippet = (briefing.content or '')[:150].strip()
    if len(briefing.content or '') > 150:
        snippet += '...'

    text = (
        f"{type_name}\n\n"
        f"<b>{briefing.title}</b>\n\n"
        f"{snippet}\n\n"
        f"전체 보기 → https://nr2.kr/briefings/{briefing.id}"
    )
    return send_to_channel(text)
