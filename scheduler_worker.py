"""
APScheduler 스케줄러 워커 - Railway worker 서비스 전용
"""
import os
import logging
from apscheduler.schedulers.blocking import BlockingScheduler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

from app import create_app
app = create_app()

from app.jobs.youtube_feed import check_and_post_new_videos
from nureongi_news_bot import run_news_bot

scheduler = BlockingScheduler(timezone='Asia/Seoul')
INTERVAL_MINUTES = int(os.environ.get('YOUTUBE_CHECK_INTERVAL', 10))

@scheduler.scheduled_job('interval', minutes=INTERVAL_MINUTES, id='youtube_feed_check',
                          coalesce=True, max_instances=1)
def job():
    logger.info('[Scheduler] 유튜브 RSS 피드 확인 중...')
    check_and_post_new_videos(app)

@scheduler.scheduled_job('interval', minutes=5, id='news_bot',
                          coalesce=True, max_instances=1)
def news_job():
    logger.info('[Scheduler] 뉴스 크롤링 중...')
    run_news_bot()

if __name__ == '__main__':
    logger.info(f'[Scheduler] 시작 — {INTERVAL_MINUTES}분마다 유튜브 RSS 피드 확인')
    check_and_post_new_videos(app)
    scheduler.start()
