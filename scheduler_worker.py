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
from ai_briefing import send_briefing
from political_briefing import afternoon_political_briefing, evening_political_briefing

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

@scheduler.scheduled_job('cron', hour=6, minute=0, id='morning_briefing', timezone='Asia/Seoul')
def morning_briefing():
    logger.info('[Scheduler] 아침 AI 브리핑 생성 중...')
    send_briefing()

@scheduler.scheduled_job('cron', hour=18, minute=0, id='evening_briefing', timezone='Asia/Seoul')
def evening_briefing():
    logger.info('[Scheduler] 저녁 AI 브리핑 생성 중...')
    send_briefing()

@scheduler.scheduled_job('cron', hour=13, minute=0, id='afternoon_political', timezone='Asia/Seoul')
def afternoon_political():
    logger.info('[Scheduler] 오후 정치 브리핑 생성 중...')
    afternoon_political_briefing()

@scheduler.scheduled_job('cron', hour=22, minute=0, id='evening_political', timezone='Asia/Seoul')
def evening_political():
    logger.info('[Scheduler] 저녁 정치 브리핑 생성 중...')
    evening_political_briefing()

if __name__ == '__main__':
    logger.info(f'[Scheduler] 시작 — {INTERVAL_MINUTES}분마다 유튜브 RSS 피드 확인')
    check_and_post_new_videos(app)
    scheduler.start()