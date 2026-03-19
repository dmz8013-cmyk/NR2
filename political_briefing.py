"""
정치 브리핑 봇 - 네이버 뉴스 검색 API + Claude 요약 + 텔레그램 발송
오후 1시: 당일 09시~13시 정치 기사 요약
오후 10시: 당일 13시~22시 정치 기사 요약 (실시간 랭킹 상위 위주)
"""

import os
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)

# ─── 환경변수 ───
NAVER_CLIENT_ID = os.environ.get('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
TELEGRAM_BOT_TOKEN = os.environ.get('NUREONGI_NEWS_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

KST = pytz.timezone('Asia/Seoul')

# ─── 검색 키워드 ───
SEARCH_QUERIES = [
    "이재명 대통령",
    "더불어민주당",
    "이재명 정부",
    "국민의힘",
    "보수 야당",
    "국회 법안",
    "한미 외교",
    "검찰 수사",
    "정치 속보",
    "여야 대치",
]


def search_naver_news(query, display=10, sort='date'):
    """네이버 뉴스 검색 API 호출"""
    try:
        params = urllib.parse.urlencode({'query': query, 'display': display, 'sort': sort})
        url = f"https://openapi.naver.com/v1/search/news.json?{params}"

        req = urllib.request.Request(url)
        req.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
        req.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('items', [])
    except Exception as e:
        logger.error(f"네이버 검색 실패 [{query}]: {e}")
        return []


def collect_political_news(is_afternoon=True):
    """
    정치 뉴스 수집
    is_afternoon=True: 오후 1시 브리핑 (09시~13시 기사)
    is_afternoon=False: 오후 10시 브리핑 (13시~22시 기사)
    """
    now = datetime.now(KST)

    all_articles = []
    seen_titles = set()

    for query in SEARCH_QUERIES:
        items = search_naver_news(query, display=15, sort='date')

        for item in items:
            title = item.get('title', '').replace('<b>', '').replace('</b>', '').replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            description = item.get('description', '').replace('<b>', '').replace('</b>', '').replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            link = item.get('originallink', '') or item.get('link', '')
            pub_date_str = item.get('pubDate', '')

            title_key = title[:30]
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            try:
                pub_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %z')
                pub_date_kst = pub_date.astimezone(KST)
            except Exception:
                continue

            today_9am = now.replace(hour=9, minute=0, second=0, microsecond=0)

            if is_afternoon:
                start_time = today_9am
                end_time = now.replace(hour=13, minute=0, second=0, microsecond=0)
            else:
                start_time = now.replace(hour=13, minute=0, second=0, microsecond=0)
                end_time = now.replace(hour=22, minute=0, second=0, microsecond=0)

            start_time = start_time - timedelta(hours=1)

            if start_time <= pub_date_kst <= end_time:
                all_articles.append({
                    'title': title,
                    'description': description,
                    'link': link,
                    'pub_date': pub_date_kst,
                    'query': query,
                })

    all_articles.sort(key=lambda x: x['pub_date'], reverse=True)
    all_articles = all_articles[:40]

    # 타임라인 필터 2차 검증 (절대 상한 체크)
    try:
        from timeline_filter import filter_naver_articles
        btype = 'political_afternoon' if is_afternoon else 'political_evening'
        before_count = len(all_articles)
        all_articles = filter_naver_articles(
            all_articles, start_time, end_time, briefing_type=btype
        )
        if len(all_articles) < before_count:
            logger.warning(
                f"[타임라인 필터] {before_count}건 → {len(all_articles)}건 "
                f"(구식 {before_count - len(all_articles)}건 제거)"
            )
    except Exception as tf_err:
        logger.error(f"[타임라인 필터] 실행 실패: {tf_err}")

    logger.info(f"수집된 정치 기사: {len(all_articles)}개 ({'오후' if is_afternoon else '저녁'})")
    return all_articles


def generate_political_briefing(articles, is_afternoon=True):
    """Claude API로 정치 브리핑 생성"""
    if not articles:
        logger.warning("수집된 기사가 없어 브리핑 생성 불가")
        return None

    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY 없음")
        return None

    now = datetime.now(KST)
    today_str = now.strftime('%y%m%d')
    time_label = "13:00" if is_afternoon else "22:00"
    time_range = "09시~13시" if is_afternoon else "13시~22시"

    news_block = ""
    for i, article in enumerate(articles, 1):
        news_block += f"{i}. [{article['title']}]\n   {article['description'][:150]}\n\n"

    # 팩트 컨텍스트 자동 주입
    try:
        from fact_checker import get_fact_context
        fact_context = get_fact_context()
    except Exception:
        fact_context = ""

    prompt = f"""{fact_context}당신은 한국 정치 전문 뉴스 브리핑 AI입니다.
아래 {len(articles)}개의 정치 뉴스 기사를 분석하여 텔레그램용 정치 브리핑을 작성하세요.

[포맷 - 반드시 정확히 따르세요. 한 글자도 빠짐없이 이 구조를 지키세요]

🔥【한방에 정리하는 정치권 이슈 - 반박시니말이맞음({today_str} {time_label})】🔥
[여기에 기사 내용을 종합한 자극적이고 핵심을 찌르는 한줄 제목을 작성 - 반드시 위 🔥 줄과 별도의 두번째 줄에 작성할 것]

출처: https://buly.kr/7mBN720
(실시간 카카오톡 오픈채팅)

⸻⸻⸻⸻

🇰🇷 이재명 정부 🇰🇷
(이재명 대통령/정부 관련 주요 이슈 3~5개를 각각 '-'로 시작하여 한줄 요약)

⸻⸻⸻⸻

🟦 더불어민주당 🟦
(당 내부 이슈, 의원 동향 등 3~5개를 '-'로 요약)

⸻⸻⸻⸻

🟥 국민의힘 🟥
(국민의힘 관련 이슈 3~5개를 '-'로 요약)

⸻⸻⸻⸻

🎸 비교섭단체 및 기타 정치 🪕
(조국혁신당, 개혁신당, 새로운미래, 기타 정치 이슈 2~4개를 '-'로 요약)

⸻⸻⸻⸻

🌐 법조 및 국제 🌐
(검찰 수사, 법원 판결, 외교, 국제 이슈 중 정치 관련 2~4개를 '-'로 요약)

⸻⸻⸻⸻

출처: https://t.me/gazzzza2025
(텔레그램 실시간 정보방)

⸻⸻⸻⸻

[작성 규칙]
1. 각 항목은 '-'로 시작하고 한줄~두줄로 간결하게 (핵심만)
2. 말투는 단정하고 날카롭게 (예: "~로 파장", "~논란 점화", "~세 과시")
3. 마침표 세 개(...) 대신 반드시 유니코드 말줄임표(…)를 사용
4. 제공된 기사 제목과 요약을 최대한 활용하여 브리핑을 작성하세요. 기사에 없는 내용을 지어내지는 말되, 제목에서 충분히 유추 가능한 내용은 자연스럽게 서술하세요.
5. 각 섹션에 해당 기사가 부족하면 1개까지 줄여도 됨. 해당 섹션에 기사가 전혀 없으면 "금일 주요 보도 없음"으로 짧게 처리
6. 총 분량: 텔레그램 한 메시지에 맞게 (3500자 이내)
7. 제목은 반드시 자극적이고 흥미를 유발하는 문구로
8. 첫 줄 🔥【한방에 정리하는 정치권 이슈 - 반박시니말이맞음(...)】🔥는 절대 수정하지 말것. 이 줄은 고정 텍스트이며 자극적 제목은 반드시 그 다음 줄에 별도로 작성
9. "정보가 부족합니다", "브리핑을 작성할 수 없습니다" 같은 거부 메시지는 절대 출력하지 마세요. 기사가 적더라도 반드시 위 포맷대로 브리핑을 완성하세요.
10. [팩트 정확도] 기사 제목과 요약에 명시된 내용만 사용하세요. 기사에 없는 감정("심기불편", "분노"), 반응, 발언을 지어내지 마세요. 사실 기반 서술만 허용됩니다.
11. [시의성] 제공된 기사는 모두 오늘자입니다. "최근", "지난달" 등 모호한 시점 대신 구체적 시점으로 작성하세요.

[오늘 {time_range} 정치 뉴스]
{news_block}"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )

        briefing = response.content[0].text
        logger.info(f"정치 브리핑 생성 완료: {len(briefing)}자")
        return briefing

    except Exception as e:
        logger.error(f"Claude API 오류: {e}")
        return None


def _split_text(text, limit=4096):
    """텍스트를 limit 이하 청크로 분할. 줄바꿈 기준으로 자른다."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


def send_telegram_message(text):
    """텔레그램으로 메시지 전송. 4096자 초과 시 분할 전송."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("텔레그램 설정 없음")
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        chunks = _split_text(text)

        for i, chunk in enumerate(chunks, 1):
            data = json.dumps({
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            }).encode('utf-8')

            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                if result.get('ok'):
                    logger.info(f"텔레그램 전송 성공 ({i}/{len(chunks)})")
                else:
                    logger.error(f"텔레그램 전송 실패: {result}")
                    return False

        return True

    except Exception as e:
        logger.error(f"텔레그램 전송 오류: {e}")
        return False


def send_political_briefing(is_afternoon=True):
    """정치 브리핑 메인 함수"""
    period = "오후 1시" if is_afternoon else "오후 10시"
    logger.info(f"=== 정치 브리핑 시작 ({period}) ===")

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.error("네이버 API 키 없음")
        return

    articles = collect_political_news(is_afternoon=is_afternoon)

    if not articles:
        logger.warning(f"수집된 기사 없음 - {period} 브리핑 건너뜀")
        return

    briefing = generate_political_briefing(articles, is_afternoon=is_afternoon)

    if not briefing:
        logger.error("브리핑 생성 실패")
        return

    # 팩트체크 — 발송 전 인물·직책 오류 자동 감지·수정
    try:
        from fact_checker import run_fact_check, auto_fix
        fc_result = run_fact_check(briefing)
        if not fc_result["passed"]:
            logger.warning(f"[팩트체크 오류] {fc_result['errors']}")
            briefing = auto_fix(briefing)

            # 관리자에게 수정 내역 별도 알림
            admin_msg = "⚠️ <b>정치 브리핑 팩트 자동수정</b>\n\n"
            for err in fc_result["errors"]:
                admin_msg += f"• '{err['found']}' → '{err['should_be']}'\n"
                admin_msg += f"  문맥: {err.get('context', '')}\n"
            try:
                from app.utils.telegram_notify import send_to_admin
                send_to_admin(admin_msg)
            except Exception:
                pass
        else:
            logger.info("[팩트체크] 오류 없음 — 통과")
    except Exception as fc_err:
        logger.error(f"[팩트체크] 실행 실패 (브리핑은 그대로 발송): {fc_err}")

    success = send_telegram_message(briefing)
# DB 저장
    try:
        from app import create_app, db
        from app.models.briefing import Briefing as BriefingModel
        _app = create_app()
        with _app.app_context():
            btype = 'political_afternoon' if is_afternoon else 'political_evening'
            first_line = briefing.split('\n')[0][:200]
            record = BriefingModel(
                briefing_type=btype,
                title=first_line,
                content=briefing,
                article_count=len(articles),
            )
            db.session.add(record)
            db.session.commit()
            logger.info(f"정치 브리핑 DB 저장 완료 (id={record.id})")
            # 채널 알림
            try:
                from app.utils.telegram_notify import notify_new_briefing
                notify_new_briefing(record)
            except Exception as ne:
                logger.error(f"정치 브리핑 채널 알림 실패: {ne}")
    except Exception as e:
        logger.error(f"정치 브리핑 DB 저장 실패: {e}")
    if success:
        logger.info(f"=== 정치 브리핑 완료 ({period}) ===")
    else:
        logger.error(f"=== 정치 브리핑 전송 실패 ({period}) ===")


def afternoon_political_briefing():
    """오후 1시 브리핑"""
    send_political_briefing(is_afternoon=True)


def evening_political_briefing():
    """오후 10시 브리핑"""
    send_political_briefing(is_afternoon=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("정치 브리핑 테스트 실행...")
    send_political_briefing(is_afternoon=True)
