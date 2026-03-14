"""
YouTube Data API v3를 사용하여 @NR2AESA 채널의 새 영상을
AESA 게시판에 자동 게시하는 잡 모듈

[영구 비활성화] AESA 게시판 이준석 관련 중복 글 문제로 영구 비활성화.
scheduler_worker.py에서도 비활성화됨. 절대 재활성화 금지.
환경변수:
  YOUTUBE_API_KEY      — YouTube Data API v3 키 (Railway Variables에서 설정)
  YOUTUBE_CHANNEL_ID   — 대상 채널 ID
"""
import os
import logging
from datetime import datetime, timedelta

import requests

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY', '')
YOUTUBE_CHANNEL_ID = os.environ.get('YOUTUBE_CHANNEL_ID', '')
SEARCH_URL = 'https://www.googleapis.com/youtube/v3/search'
VIDEO_URL = 'https://www.googleapis.com/youtube/v3/videos'


def fetch_recent_videos(published_after=None):
    """채널의 최근 영상 목록을 가져온다 (최대 10개)."""
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_ID:
        logger.warning('[YT-API] YOUTUBE_API_KEY 또는 YOUTUBE_CHANNEL_ID가 설정되지 않았습니다.')
        return []

    if published_after is None:
        published_after = (datetime.utcnow() - timedelta(hours=2)).isoformat() + 'Z'

    params = {
        'key': YOUTUBE_API_KEY,
        'channelId': YOUTUBE_CHANNEL_ID,
        'part': 'snippet',
        'order': 'date',
        'type': 'video',
        'maxResults': 10,
        'publishedAfter': published_after,
    }

    try:
        resp = requests.get(SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f'[YT-API] 검색 API 호출 실패: {e}')
        return []

    videos = []
    for item in data.get('items', []):
        snippet = item.get('snippet', {})
        video_id = item.get('id', {}).get('videoId')
        if not video_id:
            continue
        videos.append({
            'video_id': video_id,
            'title': snippet.get('title', '제목 없음'),
            'description': snippet.get('description', ''),
            'url': f'https://www.youtube.com/watch?v={video_id}',
        })

    return videos


def check_and_post_new_videos_api(app):
    """YouTube Data API v3로 새 영상을 확인하고 AESA 게시판에 게시한다."""
    with app.app_context():
        from app import db
        from app.models import Post, User

        admin = User.query.filter_by(is_admin=True).first()
        if not admin:
            logger.error('[YT-API] 관리자 계정이 없어 자동 게시를 건너뜁니다.')
            return

        videos = fetch_recent_videos()
        if not videos:
            logger.info('[YT-API] 새 영상 없음.')
            return

        new_count = 0
        for v in videos:
            # youtube_video_id로 중복 체크
            existing = Post.query.filter_by(youtube_video_id=v['video_id']).first()
            if existing:
                continue

            description = v['description'][:300] + ('...' if len(v['description']) > 300 else '') if v['description'] else '(설명 없음)'

            content = f"""<p>{description}</p>
<p><br></p>
<p><a href="{v['url']}" target="_blank">▶ YouTube에서 보기</a></p>"""

            try:
                post = Post(
                    title=v['title'],
                    content=content,
                    board_type='aesa',
                    youtube_url=v['url'],
                    youtube_video_id=v['video_id'],
                    user_id=admin.id,
                )
                db.session.add(post)
                db.session.commit()
                new_count += 1
                logger.info(f'[YT-API] 새 영상 게시: {v["title"]}')
            except Exception as e:
                db.session.rollback()
                logger.error(f'[YT-API] 게시 실패 ({v["video_id"]}): {e}')

        logger.info(f'[YT-API] 완료 — 신규 {new_count}건 게시.')
