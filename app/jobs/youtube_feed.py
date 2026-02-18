"""
유튜브 RSS 피드를 주기적으로 확인하여
새 영상을 AESA 게시판에 자동 게시하는 잡 모듈
"""
import os
import logging
import feedparser

logger = logging.getLogger(__name__)

YOUTUBE_CHANNEL_ID = os.environ.get('YOUTUBE_CHANNEL_ID', 'UCy.rebuilding')
YOUTUBE_RSS_URL = f'https://www.youtube.com/feeds/videos.xml?channel_id={YOUTUBE_CHANNEL_ID}'


def check_and_post_new_videos(app):
    """유튜브 RSS 피드 확인 및 새 영상 자동 게시"""
    with app.app_context():
        from app import db
        from app.models import Post, User

        # 관리자 계정 (게시글 작성자로 사용)
        admin = User.query.filter_by(is_admin=True).first()
        if not admin:
            logger.error('[AESA] 관리자 계정이 없어 자동 게시를 건너뜁니다.')
            return

        # RSS 피드 파싱
        try:
            feed = feedparser.parse(YOUTUBE_RSS_URL)
        except Exception as e:
            logger.error(f'[AESA] RSS 피드 파싱 오류: {e}')
            return

        if not feed.entries:
            logger.info('[AESA] RSS 피드에 항목이 없습니다.')
            return

        new_count = 0
        for entry in feed.entries:
            video_id = entry.get('yt_videoid', '')
            if not video_id:
                continue

            video_url = f'https://www.youtube.com/watch?v={video_id}'

            # 중복 체크
            existing = Post.query.filter_by(
                board_type='aesa',
                youtube_url=video_url
            ).first()
            if existing:
                continue

            # 영상 설명 추출 (첫 200자)
            summary = entry.get('summary', '') or ''
            # feedparser HTML 태그 제거
            import re
            summary = re.sub(r'<[^>]+>', '', summary).strip()
            content = summary[:200] + ('...' if len(summary) > 200 else '') or '(설명 없음)'

            title = entry.get('title', '제목 없음')

            try:
                post = Post(
                    title=title,
                    content=content,
                    board_type='aesa',
                    youtube_url=video_url,
                    user_id=admin.id
                )
                db.session.add(post)
                db.session.commit()
                new_count += 1
                logger.info(f'[AESA] 새 영상 게시: {title}')
            except Exception as e:
                db.session.rollback()
                logger.error(f'[AESA] 게시 실패 ({video_url}): {e}')

        if new_count > 0:
            logger.info(f'[AESA] 총 {new_count}개 새 영상 게시 완료.')
        else:
            logger.info('[AESA] 새 영상 없음.')
