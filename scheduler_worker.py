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
from editorial_bot import send_editorial
from schedule_bot import send_schedule
from vip_alert_bot import run_vip_alert
from app.utils.bias_report import generate_weekly_report, send_weekly_report_to_telegram

scheduler = BlockingScheduler(timezone='Asia/Seoul')
INTERVAL_MINUTES = int(os.environ.get('YOUTUBE_CHECK_INTERVAL', 10))

@scheduler.scheduled_job('interval', minutes=INTERVAL_MINUTES, id='youtube_feed_check',
                          coalesce=True, max_instances=1)
def job():
    logger.info('[Scheduler] 유튜브 RSS 피드 확인 중...')
    check_and_post_new_videos(app)

@scheduler.scheduled_job('interval', minutes=10, id='news_bot',
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

@scheduler.scheduled_job('cron', hour=6, minute=0, id='editorial_bot', timezone='Asia/Seoul')
def editorial_job():
    logger.info('[Scheduler] 사설봇 실행 중...')
    send_editorial()

@scheduler.scheduled_job('cron', hour=6, minute=30, id='schedule_bot', timezone='Asia/Seoul')
def schedule_job():
    logger.info('[Scheduler] 일정봇 실행 중...')
    send_schedule()

@scheduler.scheduled_job('interval', minutes=15, id='vip_alert', misfire_grace_time=300)
def vip_alert_job():
    logger.info('[Scheduler] VIP 알림봇 실행 중...')
    run_vip_alert()

@scheduler.scheduled_job('cron', day_of_week='mon', hour=9, minute=0, id='weekly_bias_report', timezone='Asia/Seoul')
def weekly_bias_report():
    logger.info('[Scheduler] 주간 편향 리포트 생성 및 전송 중...')
    with app.app_context():
        report = generate_weekly_report()
        result = send_weekly_report_to_telegram(report['telegram_text'])
        if result['success']:
            logger.info('[Scheduler] 주간 편향 리포트 전송 완료')
        else:
            logger.error(f'[Scheduler] 주간 편향 리포트 전송 실패: {result["message"]}')

if __name__ == '__main__':
    logger.info(f'[Scheduler] 시작 — {INTERVAL_MINUTES}분마다 유튜브 RSS 피드 확인')
    check_and_post_new_videos(app)
    scheduler.start()