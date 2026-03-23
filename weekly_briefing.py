"""주간 TOP5 브리핑 — 매주 일요일 20:00 KST 텔레그램 자동 발송"""
import os
import logging
from datetime import datetime, timedelta

import requests

from app import db
from app.models.post import Post
from app.models import Comment, Like

logger = logging.getLogger(__name__)

MEDALS = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']


def _fetch_top_posts(app, limit=5):
    """지난 7일간 (likes*3 + comments*2 + views*1) 상위 게시글 반환"""
    with app.app_context():
        since = datetime.now() - timedelta(days=7)

        posts = (
            Post.query
            .filter(Post.created_at >= since)
            .filter(Post.board_type != 'notice')
            .all()
        )

        scored = []
        for p in posts:
            like_cnt = p.likes.count()
            comment_cnt = p.comments.count()
            view_cnt = p.views or 0
            score = like_cnt * 3 + comment_cnt * 2 + view_cnt
            scored.append({
                'post': p,
                'score': score,
                'likes': like_cnt,
                'comments': comment_cnt,
                'views': view_cnt,
            })

        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:limit]


def _build_message(ranked):
    """텔레그램 발송용 텍스트 생성"""
    lines = [
        '🐕 이번 주 누렁이 TOP 5',
        '━━━━━━━━━━━━━━━━━━',
        '',
    ]

    for i, item in enumerate(ranked):
        p = item['post']
        medal = MEDALS[i] if i < len(MEDALS) else f'{i+1}.'
        title = p.title[:50] + ('…' if len(p.title) > 50 else '')
        lines.append(f'{medal} {title}')
        lines.append(
            f'💬 댓글 {item["comments"]}개 · '
            f'👍 {item["likes"]} · '
            f'👁 {item["views"]}'
        )
        lines.append(f'→ nr2.kr/boards/{p.board_type}/{p.id}')
        lines.append('')

    lines.append('━━━━━━━━━━━━━━━━')
    lines.append('📖 오늘 브리핑 전문 + 심층 토론')
    lines.append('👉 https://nr2.kr')
    lines.append('━━━━━━━━━━━━━━━━')

    return '\n'.join(lines)


def send_weekly_briefing(app):
    """주간 TOP5 브리핑 생성 → 텔레그램 발송"""
    logger.info('[Weekly] 주간 TOP5 브리핑 시작')

    ranked = _fetch_top_posts(app, limit=5)

    if not ranked:
        logger.info('[Weekly] 지난 7일간 게시글 0건 — 발송 스킵')
        return False

    text = _build_message(ranked)

    token = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    if not token or not chat_id:
        logger.error('[Weekly] NUREONGI_NEWS_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 미설정')
        return False

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': None,
        'disable_web_page_preview': True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.ok:
            logger.info(f'[Weekly] 채널 발송 완료 (TOP {len(ranked)}개)')
            return True
        else:
            logger.error(f'[Weekly] 발송 실패: {resp.text}')
            return False
    except Exception as e:
        logger.error(f'[Weekly] 발송 예외: {e}')
        return False
