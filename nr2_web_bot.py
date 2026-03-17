"""
nr2.kr 웹 연동 텔레그램 봇
- /web 명령어: 오늘의 인기글 TOP 3
- YouCheck 매일 오전 8시 자동 발송
"""
import os
import logging
import requests
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = '@gazzzza2025'


def tg_send(chat_id, text):
    """텔레그램 메시지 전송"""
    if not BOT_TOKEN:
        logger.warning('[WebBot] TELEGRAM_BOT_TOKEN 미설정')
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML',
        'disable_web_page_preview': False,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if not resp.ok:
            logger.error(f'[WebBot] 전송 실패: {resp.text}')
        return resp.ok
    except Exception as e:
        logger.error(f'[WebBot] 전송 오류: {e}')
        return False


# ──────────────────────────────────────────────
# 기능 2: /web 명령어 — 오늘의 인기글 TOP 3
# ──────────────────────────────────────────────

def get_top3_posts(app):
    """DB에서 오늘 인기글 TOP 3 조회 (Heat Score 알고리즘)"""
    with app.app_context():
        from app.models.post import Post
        cutoff = datetime.now() - timedelta(hours=48)
        posts = Post.query.filter(
            Post.created_at >= cutoff,
            Post.board_type != 'notice'
        ).all()

        now = datetime.now()
        scored = []
        for post in posts:
            hours = (now - post.created_at).total_seconds() / 3600
            likes = post.likes_count
            comments = post.comments_count
            views = post.views or 0
            score = (likes * 5 + comments * 3 + views * 0.1) / ((hours + 2) ** 1.2)
            if score > 0:
                scored.append((post, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:3]


def format_top3_message(top3):
    """TOP 3 메시지 포맷팅"""
    if not top3:
        return "📰 <b>오늘의 nr2.kr TOP 3</b>\n\n아직 인기글이 없습니다. 첫 글을 작성해보세요!\n🔗 https://nr2.kr"

    board_names = {
        'free': '자유게시판', 'left': 'LEFT', 'right': 'RIGHT',
        'fakenews': '팩트체크', 'morpheus': '모피어스', 'aesa': 'AESA',
    }
    medals = ['🥇', '🥈', '🥉']
    lines = ["📰 <b>오늘의 nr2.kr TOP 3</b>\n"]
    for i, (post, score) in enumerate(top3):
        board = board_names.get(post.board_type, post.board_type)
        link = f"https://nr2.kr/boards/{post.board_type}/{post.id}"
        lines.append(f"{medals[i]} [{board}] {post.title}\n    → {link}")
    lines.append("\n💬 댓글 달고 NP 받기!\n🔗 https://nr2.kr")
    return "\n".join(lines)


def handle_web_command(chat_id, app):
    """'/web' 명령어 처리"""
    top3 = get_top3_posts(app)
    msg = format_top3_message(top3)
    tg_send(chat_id, msg)


def poll_commands(app):
    """텔레그램 getUpdates 폴링으로 /web 명령어 처리 (1회 실행)"""
    if not BOT_TOKEN:
        return
    import json

    offset_file = '/tmp/nr2_web_bot_offset.json'
    offset = 0
    try:
        with open(offset_file, 'r') as f:
            offset = json.load(f).get('offset', 0)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {'offset': offset, 'timeout': 5, 'allowed_updates': ['message']}
    try:
        resp = requests.get(url, params=params, timeout=15)
        if not resp.ok:
            logger.error(f'[WebBot] getUpdates 실패: {resp.text}')
            return
        data = resp.json()
    except Exception as e:
        logger.error(f'[WebBot] getUpdates 오류: {e}')
        return

    new_offset = offset
    for update in data.get('result', []):
        new_offset = update['update_id'] + 1
        msg = update.get('message', {})
        text = msg.get('text', '')
        chat_id = msg.get('chat', {}).get('id')

        if text.strip().lower() in ('/web', '/web@nr2_bot'):
            logger.info(f'[WebBot] /web 명령어 수신: chat_id={chat_id}')
            handle_web_command(chat_id, app)

    # offset 저장
    if new_offset > offset:
        try:
            with open(offset_file, 'w') as f:
                json.dump({'offset': new_offset}, f)
        except Exception:
            pass


# ──────────────────────────────────────────────
# 기능 3: YouCheck 매일 오전 8시 자동 발송
# ──────────────────────────────────────────────

def send_youcheck_daily(app):
    """오늘의 YouCheck 기사 채널 발송"""
    with app.app_context():
        from app.models.bias import NewsArticle
        from sqlalchemy import or_

        # 최근 24시간 내 가장 투표 많은 기사, 없으면 최신 기사
        cutoff = datetime.now() - timedelta(hours=48)
        article = NewsArticle.query.filter(
            NewsArticle.created_at >= cutoff,
            NewsArticle.is_visible == True,
        ).order_by(
            NewsArticle.vote_total.desc(),
            NewsArticle.created_at.desc()
        ).first()

        if not article:
            # 투표 없으면 그냥 최신 기사
            article = NewsArticle.query.filter(
                NewsArticle.is_visible == True,
            ).order_by(NewsArticle.created_at.desc()).first()

        if not article:
            logger.info('[WebBot] YouCheck 발송할 기사 없음')
            return False

        text = (
            f"☑️ <b>오늘의 YouCheck</b>\n\n"
            f"📰 \"{article.title}\"\n\n"
            f"이 기사, 어느 쪽에 가깝다고 생각하시나요?\n"
            f"편향 분석에 참여하고 <b>NP +5</b> 받기 👇\n\n"
            f"🔗 https://nr2.kr/bias"
        )
        result = tg_send(CHANNEL_ID, text)
        if result:
            logger.info(f'[WebBot] YouCheck 발송 완료: {article.title}')
        return result


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    print("=== 테스트: TOP 3 ===")
    top3 = get_top3_posts(app)
    print(format_top3_message(top3))
    print("\n=== 테스트: YouCheck ===")
    send_youcheck_daily(app)
