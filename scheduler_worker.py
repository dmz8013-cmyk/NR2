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
# [4월말 활성화 예정] YouTube Data API v3 기반 자동 게시
# from app.jobs.youtube_api import check_and_post_new_videos_api
from nureongi_news_bot import run_news_bot
from ai_briefing import send_briefing
from political_briefing import afternoon_political_briefing, evening_political_briefing
from editorial_bot import send_editorial
from schedule_bot import send_schedule
from vip_alert_bot import run_vip_alert
from app.utils.bias_report import generate_weekly_report, send_weekly_report_to_telegram
from scripts.daily_scrap import run as daily_scrap_run
from nr2_web_bot import poll_commands, send_youcheck_daily
from weekly_briefing import send_weekly_briefing
from aesa_monitoring_bot import process_rss_feeds, flush_nighttime_queue, send_daily_summary_email

scheduler = BlockingScheduler(timezone='Asia/Seoul')
INTERVAL_MINUTES = int(os.environ.get('YOUTUBE_CHECK_INTERVAL', 10))

# [비활성화] AESA 게시판에 이준석 관련 등 중복 글 자동생성 문제로 비활성화
# @scheduler.scheduled_job('interval', minutes=INTERVAL_MINUTES, id='youtube_feed_check',
#                           coalesce=True, max_instances=1)
# def job():
#     logger.info('[Scheduler] 유튜브 RSS 피드 확인 중...')
#     check_and_post_new_videos(app)

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

@scheduler.scheduled_job('cron', hour=7, minute=30, id='daily_scrap_morning', timezone='Asia/Seoul')
def daily_scrap_morning():
    logger.info('[Scheduler] 단독 뉴스 스크랩 — 오전판 실행 중...')
    daily_scrap_run('morning')

@scheduler.scheduled_job('cron', hour=16, minute=30, id='daily_scrap_afternoon', timezone='Asia/Seoul')
def daily_scrap_afternoon():
    logger.info('[Scheduler] 단독 뉴스 스크랩 — 오후판 실행 중...')
    daily_scrap_run('afternoon')

@scheduler.scheduled_job('interval', minutes=1, id='web_bot_poll',
                          coalesce=True, max_instances=1)
def web_bot_poll():
    """텔레그램 /web 명령어 폴링 (1분 간격)"""
    logger.info('[Scheduler] 웹봇 명령어 폴링 중...')
    poll_commands(app)

@scheduler.scheduled_job('cron', hour=8, minute=0, id='youcheck_daily', timezone='Asia/Seoul')
def youcheck_daily():
    """매일 오전 8시 YouCheck 기사 채널 발송"""
    logger.info('[Scheduler] YouCheck 일일 발송 중...')
    send_youcheck_daily(app)

@scheduler.scheduled_job('cron', day_of_week='sun', hour=20, minute=0,
                          id='weekly_briefing', timezone='Asia/Seoul')
def weekly_briefing_job():
    """매주 일요일 20:00 KST — 주간 TOP5 브리핑"""
    logger.info('[Scheduler] 주간 TOP5 브리핑 생성 중...')
    send_weekly_briefing(app)

@scheduler.scheduled_job('interval', minutes=5, id='aesa_rss_polling', coalesce=True, max_instances=1)
def aesa_rss_polling_job():
    logger.info('[Scheduler] AESA 해외언론 모니터링 폴링 중...')
    process_rss_feeds()

@scheduler.scheduled_job('cron', hour=6, minute=0, id='aesa_nighttime_flush', timezone='Asia/Seoul')
def aesa_nighttime_flush_job():
    logger.info('[Scheduler] AESA 야간 대기열 발송 중...')
    flush_nighttime_queue()

@scheduler.scheduled_job('cron', hour=7, minute=0, id='aesa_daily_summary', timezone='Asia/Seoul')
def aesa_daily_summary_job():
    logger.info('[Scheduler] AESA 일간 요약본 발송 중...')
    send_daily_summary_email()


# [4월말 활성화 예정] YouTube Data API v3 — 1시간마다 새 영상 체크
# @scheduler.scheduled_job('interval', hours=1, id='youtube_api_check',
#                           coalesce=True, max_instances=1)
# def youtube_api_job():
#     logger.info('[Scheduler] YouTube API v3 새 영상 확인 중...')
#     check_and_post_new_videos_api(app)

if __name__ == '__main__':
    logger.info('[Scheduler] 시작')
    # check_and_post_new_videos(app)  # 비활성화: AESA 중복 글 문제
    scheduler.start()