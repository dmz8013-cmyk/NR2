import os
import time
import logging
import feedparser
import anthropic
import requests
from datetime import datetime, time as dtime
from app import create_app, db
from app.models.aesa_article import AesaArticle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# RSS Feeds List (23개 소스)
# 자체 RSS 없는 소스 → Google News RSS 프록시 사용
RSS_FEEDS = {
    # ── 기존 8개 ──
    'MIT Tech Review': 'https://www.technologyreview.com/feed/',
    'Foreign Policy': 'https://foreignpolicy.com/feed/',
    'The Economist': 'https://www.economist.com/the-world-this-week/rss.xml',
    'SCMP': 'https://www.scmp.com/rss/4/feed',
    'Nikkei Asia': 'https://news.google.com/rss/search?q=site:asia.nikkei.com+when:1d&hl=en&gl=US&ceid=US:en',
    'Axios': 'https://api.axios.com/feed/',
    'Reuters': 'https://news.google.com/rss/search?q=site:reuters.com+when:1d&hl=en&gl=US&ceid=US:en',
    'Bloomberg': 'https://feeds.bloomberg.com/markets/news.rss',
    # ── 신규 15개 (2026-04-06 추가) ──
    'Foreign Affairs': 'https://www.foreignaffairs.com/rss.xml',
    'The Atlantic': 'https://www.theatlantic.com/feed/all/',
    'Wired': 'https://www.wired.com/feed/rss',
    'Politico': 'https://rss.politico.com/politics-news.xml',
    'Financial Times': 'https://www.ft.com/?format=rss',
    'The Diplomat': 'https://thediplomat.com/feed/',
    'Asia Times': 'https://asiatimes.com/feed/',
    'Caixin Global': 'https://news.google.com/rss/search?q=site:caixinglobal.com+when:2d&hl=en&gl=US&ceid=US:en',
    'Al Jazeera': 'https://www.aljazeera.com/xml/rss/all.xml',
    'Brookings': 'https://news.google.com/rss/search?q=site:brookings.edu+when:3d&hl=en&gl=US&ceid=US:en',
    'CFR': 'https://news.google.com/rss/search?q=site:cfr.org+when:3d&hl=en&gl=US&ceid=US:en',
    'Der Spiegel Intl': 'https://www.spiegel.de/international/index.rss',
    'Le Monde Diplo': 'https://mondediplo.com/backend',
    'Arab News': 'https://news.google.com/rss/search?q=site:arabnews.com+when:1d&hl=en&gl=US&ceid=US:en',
    'RAND': 'https://www.rand.org/blog.xml',
}

# Google News RSS 프록시를 사용하는 소스: entry.link가 Google 리다이렉트 URL일 수 있음
GOOGLE_NEWS_SOURCES = {'Nikkei Asia', 'Reuters', 'Caixin Global', 'Brookings', 'CFR', 'Arab News'}

PROMPT_TEMPLATE = """
다음 뉴스 기사를 분석하여 AESA 4개 렌즈 기준으로 0점부터 10점 사이의 점수를 매겨주세요.

[AESA 4개 렌즈]
[A] AI·기술권력 — AI, 반도체, 빅테크 플랫폼 권력, 기술 패권 경쟁
[B] 국제정치·지정학 — 전쟁, 외교, 동맹 재편, 제재, 영토 분쟁, 패권 경쟁
[C] 문화트렌드 — 세대 변화, 소비 패턴, 미디어·콘텐츠, 사회 운동
[D] 투자·금융·경제권력 — 글로벌 금리·환율·원자재, 중앙은행 정책(Fed/ECB/BOJ/PBOC), 빅테크·방산·에너지 실적·M&A, 헤지펀드·국부펀드 포지션, 무역전쟁·관세·공급망 재편, AI·반도체 투자 흐름, 암호화폐 기관 자금

결과물은 오직 다음 JSON 포맷으로만 반환하세요:
{{
  "score": 0~10의 정수,
  "lenses": ["A", "B", "C", "D"] 중 해당하는 렌즈 배열 (복수 가능),
  "korea_investment_link": true 또는 false (한국 투자시장과 연결고리 존재 여부),
  "korean_summary": "한국 언론 관점에서의 해당 기사 한 줄 요약",
  "reason": "점수 부여 이유 (짧게)"
}}

[채점 기준]
- 0~5점: 평범한 뉴스
- 6~8점: [A] [B] [C] [D] 중 하나 이상 관련성이 깊은 경우
- 9~10점: 위 4개 렌즈에 부합하고 파급력이 매우 큰 특종/비공개 분석
* 한국 언론에서 아직 널리 보도되지 않은 각도(Angle)나 신선한 관점(Blind spot)이 존재하면 +2점 보너스
* [D] 렌즈 해당 기사 중 한국 투자시장과 직접 연결고리가 있으면(예: Fed 금리→원달러→코스피, 원자재→한국 수출기업) +1점 보너스

기사 제목: {title}
기사 요약: {summary}
출처: {source}
"""

def _resolve_google_news_url(entry):
    """Google News RSS entry에서 실제 기사 URL을 추출"""
    link = entry.get('link', '')
    # Google News 링크는 보통 리다이렉트 URL
    # source 태그에서 원본 URL을 가져오거나, link 그대로 사용
    if 'news.google.com' in link:
        # source 속성에 원본 도메인이 있을 수 있음
        source_obj = entry.get('source', {})
        # feedparser는 source를 dict로 파싱
        if hasattr(source_obj, 'get'):
            href = source_obj.get('href', '')
            if href:
                return href
    return link


def _clean_title(title):
    """Google News RSS 제목에서 ' - 소스명' 접미사 제거"""
    # 패턴: "Article Title - Reuters" → "Article Title"
    for suffix in [' - Reuters', ' - Bloomberg', ' - Nikkei Asia',
                   ' - The Japan Times', ' - South China Morning Post',
                   ' - Caixin Global', ' - Brookings Institution',
                   ' - Council on Foreign Relations', ' - Arab News',
                   ' - Brookings', ' - CFR']:
        if title.endswith(suffix):
            return title[:-len(suffix)]
    return title


def process_rss_feeds():
    import json
    app = create_app()
    with app.app_context():
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

        stats = {}  # 소스별 통계 수집

        for source_name, feed_url in RSS_FEEDS.items():
            logger.info(f"[AESA] Polling RSS: {source_name}")
            source_stats = {'fetched': 0, 'skipped_dup': 0, 'scored': 0, 'sent': 0, 'low_score': 0, 'errors': 0}

            try:
                # HTTP 요청에 User-Agent 설정 (일부 피드가 봇 차단)
                resp = requests.get(feed_url, timeout=20, headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; AESA-Monitor/1.0)'
                })
                if resp.status_code != 200:
                    logger.error(f"[AESA] {source_name}: HTTP {resp.status_code} — RSS 피드 접근 실패")
                    source_stats['errors'] = 1
                    stats[source_name] = source_stats
                    continue

                feed = feedparser.parse(resp.content)
                entries = feed.entries[:10]  # 최대 10개 확인
                source_stats['fetched'] = len(entries)

                if not entries:
                    logger.warning(f"[AESA] {source_name}: RSS 파싱 성공하나 entries 0개 (bozo={feed.bozo})")
                    stats[source_name] = source_stats
                    continue

                for entry in entries:
                    # URL 추출 (Google News 프록시 소스는 별도 처리)
                    if source_name in GOOGLE_NEWS_SOURCES:
                        url = _resolve_google_news_url(entry)
                    else:
                        url = entry.get('link', '')

                    if not url:
                        continue

                    # 중복 확인
                    existing = AesaArticle.query.filter_by(url=url).first()
                    if existing:
                        source_stats['skipped_dup'] += 1
                        continue

                    title = _clean_title(entry.get('title', 'No title'))
                    summary_text = entry.get('summary', '') or entry.get('description', '')

                    # Claude 점수 책정
                    prompt = PROMPT_TEMPLATE.format(title=title, summary=summary_text[:1500], source=source_name)

                    lenses = []
                    korea_link = False

                    try:
                        response = client.messages.create(
                            model="claude-sonnet-4-20250514",
                            max_tokens=400,
                            system="당신은 최고 수준의 국제정치, 기술 트렌드, 글로벌 금융 분석가입니다.",
                            messages=[{"role": "user", "content": prompt}]
                        )

                        response_text = response.content[0].text
                        if "{" in response_text and "}" in response_text:
                            start = response_text.find("{")
                            end = response_text.rfind("}") + 1
                            json_str = response_text[start:end]
                            result = json.loads(json_str)
                            score = min(int(result.get("score", 0)), 10)
                            summary = result.get("korean_summary", "")
                            lenses = result.get("lenses", [])
                            korea_link = bool(result.get("korea_investment_link", False))
                        else:
                            score = 0
                            summary = ""
                    except Exception as e:
                        logger.error(f"[AESA] {source_name}: Claude API 또는 JSON 파싱 에러: {e}")
                        score = 0
                        summary = "분석 실패"
                        source_stats['errors'] += 1

                    # 렌즈 태그 문자열 생성
                    lens_tag = ''.join(f'[{l}]' for l in lenses) if lenses else '[?]'

                    source_stats['scored'] += 1
                    logger.info(f"[AESA] {source_name}: score={score} lens={lens_tag} kr_link={korea_link} | {title[:50]}")

                    # 9점 이상은 즉시 알림, 7~8점은 별도, 6점 이하는 요약 대기
                    # 야간 시간(02:00 ~ 06:00)에는 발송 보류
                    now = datetime.now()
                    is_night = dtime(2, 0) <= now.time() < dtime(6, 0)

                    status = 'pending'
                    if score >= 9:
                        if is_night:
                            status = 'queued_for_morning'
                        else:
                            send_telegram_alert(source_name, title, url, score, summary,
                                                lenses=lenses, korea_link=korea_link, is_urgent=True)
                            status = 'sent'
                            source_stats['sent'] += 1
                    elif 7 <= score <= 8:
                        if is_night:
                            status = 'queued_for_morning'
                        else:
                            send_telegram_alert(source_name, title, url, score, summary,
                                                lenses=lenses, korea_link=korea_link)
                            status = 'sent'
                            source_stats['sent'] += 1
                    else:
                        status = 'queued_for_summary'
                        source_stats['low_score'] += 1

                    article = AesaArticle(
                        url=url,
                        title=title,
                        source=source_name,
                        score=score,
                        summary=summary,
                        status=status
                    )
                    db.session.add(article)
                    db.session.commit()

            except Exception as e:
                logger.error(f"[AESA] {source_name}: 폴링 중 에러 발생: {e}", exc_info=True)
                source_stats['errors'] += 1

            stats[source_name] = source_stats

        # 전체 소스 통계 요약 로그
        logger.info("[AESA] ========== 폴링 사이클 완료 ==========")
        for src, s in stats.items():
            logger.info(f"[AESA] {src}: fetched={s['fetched']} dup={s['skipped_dup']} scored={s['scored']} sent={s['sent']} low={s['low_score']} err={s['errors']}")

def send_telegram_alert(source, title, url, score, summary,
                        lenses=None, korea_link=False, is_urgent=False):
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('AESA_TELEGRAM_CHANNEL_ID', os.environ.get('TELEGRAM_CHAT_ID'))

    if not bot_token or not chat_id:
        logger.warning("Telegram config missing.")
        return

    # 렌즈 태그
    lens_tag = ''.join(f'[{l}]' for l in (lenses or [])) or '[?]'
    kr_flag = " 🇰🇷" if korea_link else ""

    icon = "🚨 [긴급/특종 AESA 알림]" if is_urgent else "🔔 [AESA 주요 알림]"
    text = f"{icon}\n\n"
    text += f"*{source}* (점수: {score}/10)\n"
    text += f"[{title}]({url})\n\n"
    text += f"💡 1줄 요약:\n{summary}\n\n"
    text += f"🔍 렌즈: {lens_tag}{kr_flag}"
    
    try:
        api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': False
        }
        response = requests.post(api_url, json=payload)
        if not response.ok:
            logger.error(f"Telegram API Error: {response.text}")
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

def flush_nighttime_queue():
    app = create_app()
    with app.app_context():
        queued = AesaArticle.query.filter_by(status='queued_for_morning').all()
        if not queued:
            logger.info("야간 발송 대기열 비어있음.")
            return
            
        logger.info(f"야간 발송 대기열 {len(queued)}건 발송 시작.")
        for item in queued:
            send_telegram_alert(item.source, item.title, item.url, item.score, item.summary, is_urgent=(item.score >= 9))
            item.status = 'sent'
        db.session.commit()

def send_daily_summary_email():
    app = create_app()
    with app.app_context():
        # 어제/오늘 사이클의 요약. 점수 6 이하 위주 + 전체
        from datetime import timedelta
        yesterday = datetime.now() - timedelta(days=1)
        items = AesaArticle.query.filter(
            AesaArticle.status == 'queued_for_summary',
            AesaArticle.created_at >= yesterday
        ).order_by(AesaArticle.score.desc()).all()
        
        if not items:
            return
            
        logger.info(f"Daily summary {len(items)} items email send...")
        from flask_mail import Message
        from app import mail
        
        html_content = "<h2>AESA 일간 해외언론 모니터링 요약 (6점 이하 잔여 기사)</h2>"
        for i, item in enumerate(items, 1):
            html_content += f"<p>{i}. <b>[{item.source}]</b> <a href='{item.url}'>{item.title}</a> (Score: {item.score})<br/>{item.summary}</p>"
        
        recipients_str = os.environ.get('AESA_EMAIL_RECIPIENTS', os.environ.get('ADMIN_EMAIL', ''))
        recipients = [r.strip() for r in recipients_str.split(',') if r.strip()]
        
        if not recipients:
            logger.warning("No email recipients configured for daily summary.")
            return

        msg = Message("AESA 해외언론 일간 요약 브리핑", recipients=recipients, html=html_content)
        try:
            mail.send(msg)
            for item in items:
                item.status = 'sent_summary'
            db.session.commit()
            logger.info("Daily summary sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send daily summary: {e}")

if __name__ == "__main__":
    process_rss_feeds()
