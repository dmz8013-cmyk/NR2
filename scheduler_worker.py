"""
APScheduler 스케줄러 워커 - Railway worker 서비스 전용
"""
import os
import logging
import threading
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.events import (
    EVENT_JOB_SUBMITTED, EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED,
)

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
from editorial_bot import (
    send_editorial,
    send_editorial_nureongi,
    send_editorial_afternoon,
    send_editorial_afternoon_nureongi,
)
from schedule_bot import send_schedule, send_schedule_nureongi
from vip_alert_bot import run_vip_alert
from app.utils.bias_report import generate_weekly_report, send_weekly_report_to_telegram
from exclusive_news_bot import send_exclusive_news
from nr2_web_bot import poll_commands, send_youcheck_daily
from weekly_briefing import send_weekly_briefing
from aesa_monitoring_bot import process_rss_feeds, send_batch_alerts, flush_nighttime_queue, send_daily_summary_email, send_daily_content_report
from poll_tracker import run_poll_tracker, check_basic_polls
from candidate_tracker import check_candidate_changes

executors = {
    'default': ThreadPoolExecutor(max_workers=3)
}
# misfire_grace_time 기본 600초: APScheduler 기본값(1초)이면 재배포·스케줄러
# 지연(~5초)·장시간 잡 점유만으로 정각 잡이 조용히 스킵됨 — 9/4 단독 오후판
# 17:00 미발송 원인. 10분 내 워커가 살아나면 놓친 잡을 1회(coalesce) 실행.
scheduler = BlockingScheduler(
    executors=executors, timezone='Asia/Seoul',
    job_defaults={'misfire_grace_time': 600, 'coalesce': True},
)
INTERVAL_MINUTES = int(os.environ.get('YOUTUBE_CHECK_INTERVAL', 10))

# ─── 스케줄러 하드닝: 진단 로그 + 하트비트 자가복구 (telegram NetworkError: can't start new thread 대응) ───
# 목표는 ①관측가능성 ②자가복구 두 가지뿐. H1(asyncio default executor 스레드 회수) 근본픽스는
# editorial_bot.py:24 주석이 경고하는 부작용 영역이라 1주 진단 데이터로 확증 후 별도 Phase에서 진행.
THREAD_LIMIT = int(os.environ.get('THREAD_LIMIT', 40))

# 진단 로그: APScheduler 이벤트 리스너로 잡 본문을 전혀 건드리지 않고 실행 전후 스레드 수를 기록.
# (submitted=실행 직전, executed/error=실행 종료 → 잡별 스레드 증감 delta 특정)
# 주의: executor max_workers=3 으로 최대 3개 잡이 겹칠 수 있어 delta는 동시 실행 잡과 교란될 수 있음.
# 누수의 권위 신호는 하트비트의 절대 threads 수와 주간 추세이고, DIAG delta는 용의 잡 좁히기용.
_diag_before = {}

def _diag_on_submitted(event):
    if event.job_id == 'heartbeat':
        return
    _diag_before[event.job_id] = threading.active_count()

def _diag_on_done(event):
    if event.job_id == 'heartbeat':
        return
    before = _diag_before.pop(event.job_id, None)
    after = threading.active_count()
    if before is None:
        logger.info(f"[DIAG] job={event.job_id} after={after} (no before snapshot)")
    else:
        logger.info(f"[DIAG] job={event.job_id} before={before} after={after} delta={after - before}")

scheduler.add_listener(_diag_on_submitted, EVENT_JOB_SUBMITTED)
scheduler.add_listener(_diag_on_done, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

# ─── 미발송·에러 관리자 DM: 잡이 조용히 스킵/실패하면 즉시 한 줄 통보 ───
# (9/4 단독 오후판 17:00 misfire를 관리자가 채널 미도착으로 직접 발견한 사고 대응)
_ALERT_SKIP_IDS = {'heartbeat', 'web_bot_poll'}   # 고빈도 interval 잡 — DM 소음 방지


def _alert_admin(text):
    try:
        import requests
        token = os.environ.get('TELEGRAM_BOT_TOKEN')
        chat = os.environ.get('TELEGRAM_ADMIN_CHAT_ID', '5132309076')
        if token:
            requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                          json={'chat_id': chat, 'text': text}, timeout=10)
    except Exception as e:
        logger.warning(f'[알림] 관리자 DM 실패(무시): {e}')


def _on_job_missed(event):
    logger.warning(f'[MISSED] {event.job_id} (예정 {event.scheduled_run_time})')
    if event.job_id in _ALERT_SKIP_IDS:
        return
    _alert_admin(f'⚠️ 잡 미발송: {event.job_id} · misfire'
                 f'(예정 {event.scheduled_run_time.strftime("%H:%M")}, 유예 10분 초과)')


def _on_job_error(event):
    logger.error(f'[JOB ERROR] {event.job_id}: {event.exception}')
    if event.job_id in _ALERT_SKIP_IDS:
        return
    _alert_admin(f'⚠️ 잡 오류: {event.job_id} · {str(event.exception)[:150]}')


scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)
scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)

@scheduler.scheduled_job('interval', minutes=5, id='heartbeat', coalesce=True, max_instances=1)
def heartbeat_job():
    n = threading.active_count()
    jobs = scheduler.get_jobs()
    logger.info(f"[HEARTBEAT] threads={n} jobs={len(jobs)}")
    if n > THREAD_LIMIT:
        # 사후 부검용: 스레드 수 + 전체 잡 이름 목록 + 살아있는 스레드 이름 전체를 남기고 강제 종료.
        # 스케줄러 잡은 executor 워커 스레드에서 돌므로 sys.exit는 스레드만 죽임 → os._exit(1) 필수.
        job_ids = [j.id for j in jobs]
        thread_names = [t.name for t in threading.enumerate()]
        logger.critical(
            f"[HEARTBEAT] CRITICAL thread limit exceeded: threads={n} > THREAD_LIMIT={THREAD_LIMIT}. "
            f"jobs={job_ids} thread_names={thread_names}. "
            f"Forcing os._exit(1) -> Railway ON_FAILURE restart."
        )
        os._exit(1)

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

@scheduler.scheduled_job('cron', hour=6, minute=0, id='morning_briefing', timezone='Asia/Seoul',
                          misfire_grace_time=600, coalesce=True)
def morning_briefing():
    logger.info('[Scheduler] 아침 AI 브리핑 생성 중...')
    send_briefing()

@scheduler.scheduled_job('cron', hour=18, minute=0, id='evening_briefing', timezone='Asia/Seoul',
                          misfire_grace_time=600, coalesce=True)
def evening_briefing():
    logger.info('[Scheduler] 저녁 AI 브리핑 생성 중...')
    send_briefing()

@scheduler.scheduled_job('cron', hour=13, minute=0, id='afternoon_political', timezone='Asia/Seoul',
                          misfire_grace_time=600, coalesce=True)
def afternoon_political():
    logger.info('[Scheduler] 오후 정치 브리핑 생성 중...')
    afternoon_political_briefing()

@scheduler.scheduled_job('cron', hour=22, minute=0, id='evening_political', timezone='Asia/Seoul',
                          misfire_grace_time=600, coalesce=True)
def evening_political():
    logger.info('[Scheduler] 저녁 정치 브리핑 생성 중...')
    evening_political_briefing()

@scheduler.scheduled_job('cron', hour=6, minute=0, id='editorial_morning_brief', timezone='Asia/Seoul',
                          misfire_grace_time=600, coalesce=True)
def editorial_job():
    logger.info('[Scheduler] 사설봇 실행 중...')
    send_editorial()

@scheduler.scheduled_job('cron', hour=7, minute=0, id='editorial_nureongi_brief', timezone='Asia/Seoul',
                          misfire_grace_time=600, coalesce=True)
def editorial_nureongi_job():
    logger.info('[Scheduler] 누렁이 정보방 사설봇 실행 중 (07:00)...')
    send_editorial_nureongi()

@scheduler.scheduled_job('cron', hour=13, minute=30, id='evening_editorial_scrap_job',
                          timezone='Asia/Seoul', coalesce=True, max_instances=1,
                          misfire_grace_time=600)
def evening_editorial_scrap_job():
    logger.info('[Scheduler] 석간 사설봇 실행 중 (SOB Scrap, 13:30)...')
    send_editorial_afternoon()

@scheduler.scheduled_job('cron', hour=13, minute=31, id='evening_editorial_nureongi_job',
                          timezone='Asia/Seoul', coalesce=True, max_instances=1,
                          misfire_grace_time=600)
def evening_editorial_nureongi_job():
    logger.info('[Scheduler] 석간 사설봇 실행 중 (누렁이, 13:31)...')
    send_editorial_afternoon_nureongi()

@scheduler.scheduled_job('cron', hour=6, minute=30, id='schedule_bot', timezone='Asia/Seoul')
def schedule_job():
    logger.info('[Scheduler] 일정봇 실행 중...')
    send_schedule()

@scheduler.scheduled_job('cron', hour=7, minute=30, id='schedule_nureongi_brief', timezone='Asia/Seoul')
def schedule_nureongi_job():
    logger.info('[Scheduler] 누렁이 정보방 일정봇 실행 중 (07:30)...')
    send_schedule_nureongi()


@scheduler.scheduled_job('interval', minutes=15, id='vip_alert', misfire_grace_time=600)
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

@scheduler.scheduled_job('cron', hour=7, minute=31, id='exclusive_news_job', timezone='Asia/Seoul',
                          coalesce=True, max_instances=1)
def exclusive_news_job():
    """매일 07:31 KST — 단독 뉴스 오전판 SOB Scrap 발송"""
    logger.info('[Scheduler] 단독 뉴스 오전판 봇 실행 중...')
    send_exclusive_news('morning')

@scheduler.scheduled_job('cron', hour=17, minute=0, id='exclusive_news_afternoon', timezone='Asia/Seoul',
                          coalesce=True, max_instances=1)
def exclusive_news_afternoon_job():
    """매일 17:00 KST — 단독 뉴스 오후판 SOB Scrap 발송 (오전판과 동일 포맷)"""
    logger.info('[Scheduler] 단독 뉴스 오후판 봇 실행 중...')
    send_exclusive_news('afternoon')

@scheduler.scheduled_job('interval', minutes=1, id='web_bot_poll',
                          coalesce=True, max_instances=1)
def web_bot_poll():
    """텔레그램 /web 명령어 폴링 (1분 간격)"""
    logger.info('[Scheduler] 웹봇 명령어 폴링 중...')
    poll_commands(app)

# ── AI 거두 워치 Phase 2 (전 잡 lazy import — 워커 기동 보호) ──
def _leaders_safe(fn_name, *args):
    try:
        import collector
        getattr(collector, fn_name)(*args)
    except Exception as e:
        logger.error(f'[Scheduler] 거두워치 {fn_name} 실패(기존 파이프라인 무영향): {e}')

@scheduler.scheduled_job('cron', hour='6,12,18,22', minute=0, id='leaders_collect_t1',
                          timezone='Asia/Seoul', misfire_grace_time=600, coalesce=True, max_instances=1)
def leaders_collect_t1():
    logger.info('[Scheduler] 거두워치 T1 수집...')
    _leaders_safe('collect_tier', 1)

@scheduler.scheduled_job('cron', hour='6,18', minute=3, id='leaders_collect_t2',
                          timezone='Asia/Seoul', misfire_grace_time=600, coalesce=True, max_instances=1)
def leaders_collect_t2():
    logger.info('[Scheduler] 거두워치 T2 수집...')
    _leaders_safe('collect_tier', 2)

@scheduler.scheduled_job('cron', hour=6, minute=6, id='leaders_collect_t3',
                          timezone='Asia/Seoul', misfire_grace_time=600, coalesce=True, max_instances=1)
def leaders_collect_t3():
    logger.info('[Scheduler] 거두워치 T3 수집...')
    _leaders_safe('collect_tier', 3)

@scheduler.scheduled_job('cron', hour=6, minute=50, id='leaders_input_reminder',
                          timezone='Asia/Seoul', misfire_grace_time=600, coalesce=True, max_instances=1)
def leaders_input_reminder():
    logger.info('[Scheduler] 누렁이 시그널 입력 대기 리마인드...')
    _leaders_safe('input_reminder')

@scheduler.scheduled_job('cron', hour=7, minute=0, id='leaders_daily_edit',
                          timezone='Asia/Seoul', misfire_grace_time=600, coalesce=True, max_instances=1)
def leaders_daily_edit():
    logger.info('[Scheduler] 거두워치 07시 편집...')
    _leaders_safe('daily_edit')

@scheduler.scheduled_job('cron', day=1, hour=7, minute=30, id='leaders_monthly_report',
                          timezone='Asia/Seoul', misfire_grace_time=3600, coalesce=True)
def leaders_monthly_report():
    logger.info('[Scheduler] 거두워치 월간 리포트...')
    _leaders_safe('monthly_report')

@scheduler.scheduled_job('cron', hour=7, minute=30, id='g2b_ai_tracker_daily', timezone='Asia/Seoul',
                          misfire_grace_time=600, coalesce=True, max_instances=1)
def g2b_ai_tracker_daily():
    """매일 07:30 KST — AI 행정 트래커 전일 공고 수집.
    lazy import: 모듈 오류가 스케줄러 기동(기존 브리핑·AESA 잡)을 죽이지 않도록."""
    logger.info('[Scheduler] AI 행정 트래커 일일 수집 중...')
    try:
        from g2b_daily import run_daily
        run_daily()
    except Exception as e:
        logger.error(f'[Scheduler] AI 행정 트래커 실패(기존 파이프라인 무영향): {e}')

@scheduler.scheduled_job('cron', hour=8, minute=0, id='youcheck_daily', timezone='Asia/Seoul')
def youcheck_daily():
    """매일 오전 8시 YouCheck 기사 채널 발송"""
    logger.info('[Scheduler] YouCheck 일일 발송 중...')
    send_youcheck_daily(app)

@scheduler.scheduled_job('cron', day_of_week='sun', hour=20, minute=0,
                          id='weekly_briefing', timezone='Asia/Seoul',
                          misfire_grace_time=600, coalesce=True)
def weekly_briefing_job():
    """매주 일요일 20:00 KST — 주간 TOP5 브리핑"""
    logger.info('[Scheduler] 주간 TOP5 브리핑 생성 중...')
    send_weekly_briefing(app)

@scheduler.scheduled_job('interval', minutes=5, id='aesa_rss_polling', coalesce=True, max_instances=1)
def aesa_rss_polling_job():
    logger.info('[Scheduler] AESA 해외언론 모니터링 폴링 중...')
    process_rss_feeds()

@scheduler.scheduled_job('cron', minute='0,15,30,45', id='aesa_batch_send', timezone='Asia/Seoul',
                          coalesce=True, max_instances=1)
def aesa_batch_send_job():
    """매 15분마다 대기열 일괄 발송 (상위 5건)"""
    logger.info('[Scheduler] AESA 15분 배치 발송 중...')
    send_batch_alerts()

@scheduler.scheduled_job('cron', hour=6, minute=0, id='aesa_nighttime_flush', timezone='Asia/Seoul')
def aesa_nighttime_flush_job():
    logger.info('[Scheduler] AESA 야간 대기열 발송 중...')
    flush_nighttime_queue()

@scheduler.scheduled_job('cron', hour=7, minute=0, id='aesa_daily_summary', timezone='Asia/Seoul')
def aesa_daily_summary_job():
    logger.info('[Scheduler] AESA 일간 요약본 발송 중...')
    send_daily_summary_email()

@scheduler.scheduled_job('cron', hour=7, minute=0, id='aesa_content_report', timezone='Asia/Seoul')
def aesa_content_report_job():
    """매일 오전 7시 — 전날 기사 기반 영상 콘텐츠 후보 TOP3"""
    logger.info('[Scheduler] AESA 영상 콘텐츠 후보 TOP3 발송 중...')
    send_daily_content_report()

# [POLL_BOT] 비활성화 상태 안내 — 모듈 로드 시 1회 출력
if os.getenv("ENABLE_POLL_BOT", "false").lower() != "true":
    logger.info("[POLL_BOT] disabled by ENABLE_POLL_BOT flag — skipping job registration")

# 2026.05.03 일시 중단 - 데이터 정합성 문제.
# 6월 선거 후 옵션 B(중앙선거여론조사심의위 직접 연동) 방향으로 재구축 예정
# @scheduler.scheduled_job('cron', hour=8, minute=30, id='poll_tracker_daily', timezone='Asia/Seoul')
def poll_tracker_job():
    """매일 오전 8시 30분 여론조사 봇 실행"""
    logger.info('[Scheduler] 지방선거 여론조사 모니터링 봇 실행 중...')
    run_poll_tracker()

# 후보 매칭 데이터 부정확, 6월 선거 후 옵션 B로 재구축 예정
# @scheduler.scheduled_job('interval', hours=2, id='candidate_tracker_job', coalesce=True, max_instances=1)
def candidate_tracker_job():
    """매 2시간마다 후보 변동사항 확인"""
    logger.info('[Scheduler] 후보 현황 트래커 실행 중...')
    check_candidate_changes()

# 2026.05.03 일시 중단 - 데이터 정합성 문제.
# 6월 선거 후 옵션 B(중앙선거여론조사심의위 직접 연동) 방향으로 재구축 예정
# @scheduler.scheduled_job('interval', hours=3, id='basic_poll_tracker_job', coalesce=True, max_instances=1)
def basic_poll_tracker_job():
    """매 3시간마다 기초/교육감/정당 지지율 여론조사 확인"""
    logger.info('[Scheduler] 기초/교육감/정당 여론조사 봇 실행 중...')
    check_basic_polls()




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