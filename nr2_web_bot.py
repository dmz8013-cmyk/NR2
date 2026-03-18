"""
nr2.kr 웹 연동 텔레그램 봇
- /web, /home  : 오늘의 YouCheck TOP 3 + nr2.kr 링크
- /lounge      : 직군별 라운지 6개 바로가기 링크
- /bias {번호} : 해당 기사 편향 투표 페이지 링크
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
# /home, /web — 오늘의 YouCheck TOP 3 + 인기글
# ──────────────────────────────────────────────

def get_top3_youcheck(app):
    """DB에서 YouCheck 투표 많은 기사 TOP 3"""
    with app.app_context():
        from app.models.bias import NewsArticle
        cutoff = datetime.now() - timedelta(hours=72)
        articles = NewsArticle.query.filter(
            NewsArticle.created_at >= cutoff,
            NewsArticle.is_visible == True,
        ).order_by(
            NewsArticle.vote_total.desc(),
            NewsArticle.created_at.desc()
        ).limit(3).all()
        return articles


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


def handle_home_command(chat_id, app):
    """/home 명령어 — YouCheck TOP 3 + 인기글 TOP 3"""
    # YouCheck TOP 3
    yc_articles = get_top3_youcheck(app)
    lines = ["🏠 <b>nr2.kr 오늘의 하이라이트</b>\n"]

    if yc_articles:
        lines.append("━━ ☑️ <b>YouCheck TOP 3</b> ━━")
        medals = ['🥇', '🥈', '🥉']
        for i, art in enumerate(yc_articles):
            votes = f"({art.vote_total}표)" if art.vote_total else "(집계중)"
            lines.append(f"{medals[i]} {art.title} {votes}\n    → https://nr2.kr/bias/{art.id}")
        lines.append("")

    # 인기글 TOP 3
    board_names = {
        'free': '자유게시판', 'left': 'LEFT', 'right': 'RIGHT',
        'fakenews': '팩트체크', 'morpheus': '모피어스', 'aesa': 'AESA',
    }
    top3 = get_top3_posts(app)
    if top3:
        lines.append("━━ 🔥 <b>인기글 TOP 3</b> ━━")
        medals = ['🥇', '🥈', '🥉']
        for i, (post, score) in enumerate(top3):
            board = board_names.get(post.board_type, post.board_type)
            lines.append(f"{medals[i]} [{board}] {post.title}\n    → https://nr2.kr/boards/{post.board_type}/{post.id}")
        lines.append("")

    if not yc_articles and not top3:
        lines.append("아직 오늘의 콘텐츠가 없습니다.\n첫 글을 작성해보세요!")

    lines.append("💬 댓글 달고 NP 받기!\n🔗 https://nr2.kr")
    tg_send(chat_id, "\n".join(lines))


# ──────────────────────────────────────────────
# /lounge — 직군별 라운지 6개 바로가기
# ──────────────────────────────────────────────

def handle_lounge_command(chat_id, app):
    """/lounge 명령어 — 직군별 라운지 링크"""
    text = (
        "🏛️ <b>nr2.kr 직군별 라운지</b>\n\n"
        "같은 업계 사람들과 익명으로 솔직하게!\n\n"
        "📰 <b>언론인 라운지</b> — 기자·PD·언론사\n"
        "    → https://nr2.kr/boards/lounge_media\n\n"
        "🏛️ <b>국회 라운지</b> — 보좌진·당직자\n"
        "    → https://nr2.kr/boards/lounge_congress\n\n"
        "🏢 <b>정부 라운지</b> — 공무원·공공기관\n"
        "    → https://nr2.kr/boards/lounge_govt\n\n"
        "💼 <b>기업 라운지</b> — 홍보·대관·임원\n"
        "    → https://nr2.kr/boards/lounge_corp\n\n"
        "🚶 <b>행인 광장</b> — 모든 회원 자유 소통\n"
        "    → https://nr2.kr/boards/lounge_public\n\n"
        "🎋 <b>누렁이 대나무숲</b> — 완전 익명 제보\n"
        "    → https://nr2.kr/boards/lounge_bamboo\n\n"
        "🔗 라운지 허브: https://nr2.kr/boards/lounge"
    )
    tg_send(chat_id, text)


# ──────────────────────────────────────────────
# /bias {번호} — 기사 편향 투표 페이지 바로가기
# ──────────────────────────────────────────────

def handle_bias_command(chat_id, args, app):
    """/bias {id} 명령어 — 기사 편향 투표 링크"""
    if not args:
        # 인자 없으면 YouCheck 메인 + 최근 기사 3개
        with app.app_context():
            from app.models.bias import NewsArticle
            recent = NewsArticle.query.filter(
                NewsArticle.is_visible == True
            ).order_by(NewsArticle.created_at.desc()).limit(3).all()

        lines = [
            "☑️ <b>YouCheck 편향 분석</b>\n",
            "사용법: <code>/bias 123</code> — 기사 번호로 바로 이동\n",
        ]
        if recent:
            lines.append("📰 <b>최근 기사:</b>")
            for art in recent:
                votes = f"({art.vote_total}표)" if art.vote_total else ""
                lines.append(f"  • #{art.id} {art.title} {votes}")
            lines.append("")
        lines.append("🔗 전체 목록: https://nr2.kr/bias")
        tg_send(chat_id, "\n".join(lines))
        return

    # 숫자 파싱
    try:
        article_id = int(args.strip())
    except ValueError:
        tg_send(chat_id, "⚠️ 기사 번호는 숫자로 입력해주세요.\n예: <code>/bias 42</code>")
        return

    # DB에서 기사 조회
    with app.app_context():
        from app.models.bias import NewsArticle
        article = NewsArticle.query.get(article_id)

    if not article:
        tg_send(chat_id, f"⚠️ #{article_id} 기사를 찾을 수 없습니다.\n\n🔗 전체 목록: https://nr2.kr/bias")
        return

    # 투표 현황
    status = ""
    if article.vote_total and article.vote_total >= 3:
        status = f"\n\n📊 현재 결과: 진보 {article.left_pct}% | 중도 {article.center_pct}% | 보수 {article.right_pct}% ({article.vote_total}표)"
    elif article.vote_total:
        status = f"\n\n📊 현재 {article.vote_total}표 (집계 진행 중)"
    else:
        status = "\n\n📊 아직 투표가 없습니다. 첫 투표의 주인공이 되어보세요!"

    text = (
        f"☑️ <b>YouCheck #{article.id}</b>\n\n"
        f"📰 {article.title}\n"
        f"🏷️ {article.source or '출처 미상'}"
        f"{status}\n\n"
        f"이 기사, 진보? 중도? 보수?\n"
        f"투표하고 <b>NP +5</b> 받기 👇\n\n"
        f"🔗 https://nr2.kr/bias/{article.id}"
    )
    tg_send(chat_id, text)


# ──────────────────────────────────────────────
# 폴링 — 모든 명령어 통합 처리
# ──────────────────────────────────────────────

def poll_commands(app):
    """텔레그램 getUpdates 폴링으로 명령어 처리 (1회 실행)"""
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
        text = (msg.get('text') or '').strip()
        chat_id = msg.get('chat', {}).get('id')
        if not chat_id or not text:
            continue

        cmd = text.lower().split()[0]
        args = text[len(cmd):].strip() if len(text) > len(cmd) else ''

        try:
            if cmd in ('/home', '/web', '/home@nr2_bot', '/web@nr2_bot'):
                logger.info(f'[WebBot] /home 수신: chat_id={chat_id}')
                handle_home_command(chat_id, app)

            elif cmd in ('/lounge', '/lounge@nr2_bot'):
                logger.info(f'[WebBot] /lounge 수신: chat_id={chat_id}')
                handle_lounge_command(chat_id, app)

            elif cmd in ('/bias', '/bias@nr2_bot'):
                logger.info(f'[WebBot] /bias 수신: chat_id={chat_id}, args={args}')
                handle_bias_command(chat_id, args, app)

        except Exception as e:
            logger.error(f'[WebBot] 명령어 처리 오류: {cmd} → {e}')

    # offset 저장
    if new_offset > offset:
        try:
            with open(offset_file, 'w') as f:
                json.dump({'offset': new_offset}, f)
        except Exception:
            pass


# ──────────────────────────────────────────────
# YouCheck 매일 오전 8시 자동 발송
# ──────────────────────────────────────────────

def send_youcheck_daily(app):
    """오늘의 YouCheck 기사 채널 발송"""
    with app.app_context():
        from app.models.bias import NewsArticle

        cutoff = datetime.now() - timedelta(hours=48)
        article = NewsArticle.query.filter(
            NewsArticle.created_at >= cutoff,
            NewsArticle.is_visible == True,
        ).order_by(
            NewsArticle.vote_total.desc(),
            NewsArticle.created_at.desc()
        ).first()

        if not article:
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
            f"🔗 https://nr2.kr/bias/{article.id}"
        )
        result = tg_send(CHANNEL_ID, text)
        if result:
            logger.info(f'[WebBot] YouCheck 발송 완료: {article.title}')
        return result


if __name__ == '__main__':
    from app import create_app
    app = create_app()
    print("=== 테스트: /home ===")
    handle_home_command('test', app)
    print("\n=== 테스트: /bias (목록) ===")
    handle_bias_command('test', '', app)
    print("\n=== 테스트: /lounge ===")
    handle_lounge_command('test', app)
