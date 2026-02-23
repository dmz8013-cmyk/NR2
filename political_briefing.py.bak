"""
ai_briefing.py — 누렁이 생태계 AI 브리핑 모듈 (v2.0)

sent_news.json 의존 없이 브리핑 시점에 RSS 직접 크롤링.
Claude Haiku API로 4개 분야 요약 후 텔레그램 전송.

호출: scheduler_worker.py → send_briefing()
스케줄: 매일 06:00 / 18:00 KST
"""

import os
import logging
import feedparser
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime

try:
    import anthropic
except ImportError:
    anthropic = None

# ── 로깅 ──────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("ai_briefing")

# ── 상수 ──────────────────────────────────────────
KST = ZoneInfo("Asia/Seoul")
HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_ARTICLES_PER_CATEGORY = 15
BRIEFING_MIN_CHARS = 600
BRIEFING_MAX_CHARS = 800
TELEGRAM_MAX_LENGTH = 4096

# ── RSS 피드 설정 (카테고리별) ────────────────────
RSS_FEEDS = {
    "정치/시사": [
        "https://news.google.com/rss/headlines/section/topic/NATION?hl=ko&gl=KR&ceid=KR:ko",
    ],
    "경제/산업": [
        "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=ko&gl=KR&ceid=KR:ko",
    ],
    "AI/기술": [
        "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=ko&gl=KR&ceid=KR:ko",
    ],
    "기타(스포츠/연예)": [
        "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=ko&gl=KR&ceid=KR:ko",
    ],
}

# ── 환경변수 ──────────────────────────────────────
def _env(key: str) -> str | None:
    return os.environ.get(key)


# ══════════════════════════════════════════════════
#  1. 시간대 계산
# ══════════════════════════════════════════════════
def get_time_window() -> tuple[datetime, datetime, str]:
    """
    브리핑 시점에 따라 뉴스 수집 시간대를 결정.
    - 아침 브리핑(06:00): 전날 18:00 ~ 당일 06:00
    - 저녁 브리핑(18:00): 당일 06:00 ~ 당일 18:00
    """
    now = datetime.now(KST)

    if now.hour < 12:
        # 아침 브리핑
        start = (now - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        end = now.replace(hour=6, minute=0, second=0, microsecond=0)
        period = "🌅 아침"
    else:
        # 저녁 브리핑
        start = now.replace(hour=6, minute=0, second=0, microsecond=0)
        end = now.replace(hour=18, minute=0, second=0, microsecond=0)
        period = "🌆 저녁"

    return start, end, period


# ══════════════════════════════════════════════════
#  2. RSS 뉴스 수집
# ══════════════════════════════════════════════════
def _parse_pub_date(entry) -> datetime | None:
    """RSS entry에서 발행 시각을 KST datetime으로 파싱."""
    # 방법 1: published 문자열 직접 파싱 (RFC 2822)
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            dt = parsedate_to_datetime(raw)
            return dt.astimezone(KST)
        except Exception:
            pass

    # 방법 2: feedparser의 *_parsed 튜플
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                from calendar import timegm
                ts = timegm(parsed)
                return datetime.fromtimestamp(ts, tz=KST)
            except Exception:
                pass

    return None


def fetch_news_by_category(
    start_time: datetime,
    end_time: datetime,
) -> dict[str, list[dict]]:
    """카테고리별 RSS 뉴스를 수집하고 시간 필터링."""
    categorized: dict[str, list[dict]] = {}

    for category, feed_urls in RSS_FEEDS.items():
        articles: list[dict] = []

        for url in feed_urls:
            try:
                feed = feedparser.parse(url)
                if feed.bozo and not feed.entries:
                    logger.warning(f"RSS 파싱 경고 [{category}]: {url}")
                    continue

                for entry in feed.entries:
                    pub = _parse_pub_date(entry)

                    # 시간 필터: 시간 정보가 있으면 범위 체크
                    if pub and (pub < start_time or pub > end_time):
                        continue

                    title = (entry.get("title") or "").strip()
                    if not title:
                        continue

                    # 중복 제거 (같은 제목)
                    if any(a["title"] == title for a in articles):
                        continue

                    articles.append({
                        "title": title,
                        "link": entry.get("link", ""),
                        "published": pub.isoformat() if pub else None,
                    })

            except Exception as e:
                logger.warning(f"RSS 수집 실패 [{category}] {url}: {e}")

        categorized[category] = articles[:MAX_ARTICLES_PER_CATEGORY]
        logger.info(f"  [{category}] {len(categorized[category])}건 수집")

    return categorized


# ══════════════════════════════════════════════════
#  3. Claude Haiku로 브리핑 생성
# ══════════════════════════════════════════════════
def generate_briefing_with_ai(
    categorized_news: dict[str, list[dict]],
    period: str,
) -> str | None:
    """수집된 헤드라인을 Claude Haiku에게 보내 브리핑 생성."""
    api_key = _env("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
    if anthropic is None:
        raise ImportError("anthropic 패키지가 설치되지 않았습니다. pip install anthropic")

    # 헤드라인 텍스트 조합
    news_block = ""
    total_count = 0
    for cat, articles in categorized_news.items():
        news_block += f"\n[{cat}]\n"
        for a in articles:
            news_block += f"- {a['title']}\n"
            total_count += 1

    if total_count == 0:
        return None

    today_str = datetime.now(KST).strftime("%Y년 %m월 %d일")

    prompt = f"""당신은 '누렁이 정보방'의 뉴스 브리핑 AI입니다.
아래 뉴스 헤드라인들을 바탕으로 {period} 브리핑을 작성하세요.

[작성 규칙]
1. 첫 줄: "{period} 브리핑 | {today_str}"
2. 4개 분야(정치/시사, 경제/산업, AI/기술, 기타)별로 핵심 내용을 3~5문장으로 요약
3. 전체 글자 수: {BRIEFING_MIN_CHARS}~{BRIEFING_MAX_CHARS}자 (한글 기준, 반드시 준수)
4. 이모지를 분야 제목에 사용하여 가독성 확보 (🏛️ 💰 🤖 🎯 등)
5. 마지막 줄: "📰 더 많은 정보: nr2.kr"
6. 공식적이지만 친근한 톤
7. 각 분야는 빈 줄로 구분

[오늘의 뉴스 헤드라인]
{news_block}"""

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    logger.info(f"AI 브리핑 생성 완료 — {len(text)}자")
    return text


# ══════════════════════════════════════════════════
#  4. 텔레그램 전송
# ══════════════════════════════════════════════════
def send_to_telegram(text: str) -> dict:
    """텔레그램 채널/그룹으로 브리핑 전송."""
    bot_token = _env("NUREONGI_NEWS_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        raise EnvironmentError(
            "NUREONGI_NEWS_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다."
        )

    # 텔레그램 메시지 길이 제한 처리
    if len(text) > TELEGRAM_MAX_LENGTH:
        text = text[:TELEGRAM_MAX_LENGTH - 20] + "\n\n(... 이하 생략)"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    logger.info(f"텔레그램 전송 성공 (message_id: {result.get('result', {}).get('message_id')})")
    return result


# ══════════════════════════════════════════════════
#  5. 메인 진입점
# ══════════════════════════════════════════════════
def send_briefing():
    """
    scheduler_worker.py에서 호출하는 메인 함수.
    RSS 수집 → AI 요약 → 텔레그램 전송 전체 파이프라인.
    """
    try:
        logger.info("=" * 50)
        logger.info("AI 브리핑 파이프라인 시작")
        logger.info("=" * 50)

        # 1) 시간대 계산
        start, end, period = get_time_window()
        logger.info(f"브리핑 유형: {period}")
        logger.info(f"수집 범위 : {start.strftime('%m/%d %H:%M')} ~ {end.strftime('%m/%d %H:%M')} KST")

        # 2) RSS 수집
        categorized = fetch_news_by_category(start, end)
        total = sum(len(v) for v in categorized.values())
        logger.info(f"총 수집 뉴스: {total}건")

        if total == 0:
            logger.warning("수집된 뉴스가 없어 브리핑을 건너뜁니다.")
            return

        # 3) AI 요약
        briefing = generate_briefing_with_ai(categorized, period)
        if not briefing:
            logger.warning("AI 브리핑 생성 실패 — 건너뜁니다.")
            return

        # 4) 텔레그램 전송
        send_to_telegram(briefing)

        logger.info("=" * 50)
        logger.info("AI 브리핑 파이프라인 완료 ✅")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"AI 브리핑 오류: {e}", exc_info=True)


# ── 직접 실행 (테스트용) ──────────────────────────
if __name__ == "__main__":
    send_briefing()
