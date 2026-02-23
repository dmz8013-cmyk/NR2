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

    prompt = f"""당신은 한국 정치 전문 뉴스 브리핑 AI입니다.
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
4. 기사에 없는 내용은 절대 만들지 말것
5. 각 섹션에 해당 기사가 부족하면 2개까지 줄여도 됨 (0개는 안됨)
6. 총 분량: 텔레그램 한 메시지에 맞게 (3500자 이내)
7. 제목은 반드시 자극적이고 흥미를 유발하는 문구로
8. 첫 줄 🔥【한방에 정리하는 정치권 이슈 - 반박시니말이맞음(...)】🔥는 절대 수정하지 말것. 이 줄은 고정 텍스트이며 자극적 제목은 반드시 그 다음 줄에 별도로 작성

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


def send_telegram_message(text):
    """텔레그램으로 메시지 전송"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("텔레그램 설정 없음")
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

        if len(text) > 4096:
            text = text[:4090] + "\n…"

        data = json.dumps({
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "disable_web_page_preview": True,
        }).encode('utf-8')

        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('ok'):
                logger.info("텔레그램 전송 성공")
                return True
            else:
                logger.error(f"텔레그램 전송 실패: {result}")
                return False

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

    success = send_telegram_message(briefing)

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
