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

# RSS Feeds List
RSS_FEEDS = {
    'MIT Tech Review': 'https://www.technologyreview.com/feed/',
    'Foreign Policy': 'https://foreignpolicy.com/feed/',
    'The Economist': 'https://www.economist.com/the-world-this-week/rss.xml',
    'SCMP': 'https://www.scmp.com/rss/4/feed',
    'Nikkei Asia': 'https://asia.nikkei.com/rss/feed/free',
    'Axios': 'https://api.axios.com/feed/',
    'Reuters': 'https://www.reutersagency.com/feed/',
    'Bloomberg': 'https://www.bloomberg.com/authors/AP1v-wzxyZg/bloomberg-news.rss'
}

PROMPT_TEMPLATE = """
다음 뉴스 기사를 분석하여 AESA 3개 렌즈 기준으로 0점부터 10점 사이의 점수를 매겨주세요.

[AESA 3개 렌즈]
결과물은 오직 다음 JSON 포맷으로만 반환하세요:
{{
  "score": 0~10의 정수,
  "korean_summary": "한국 언론 관점에서의 해당 기사 한 줄 요약",
  "reason": "점수 부여 이유 (짧게)"
}}

[채점 기준]
- 0~5점: 평범한 뉴스
- 6~8점: [A] AI·기술권력, [B] 지정학·패권, [C] 문화트렌드 중 하나 이상 관련성이 깊은 경우
- 9~10점: 위 3개 렌즈에 부합하고 파급력이 매우 큰 특종/비공개 분석.
* 만약 한국 언론에서 아직 널리 보도되지 않은 각도(Angle)나 신선한 관점(Blind spot)이 존재한다고 판단되면 +2점 보너스를 주세요.

기사 제목: {title}
기사 요약: {summary}
출처: {source}
"""

def process_rss_feeds():
    app = create_app()
    with app.app_context():
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
        
        for source_name, feed_url in RSS_FEEDS.items():
            logger.info(f"Polling RSS: {source_name}")
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:5]: # top 5 recent
                    url = entry.link
                    
                    # 중복 확인
                    existing = AesaArticle.query.filter_by(url=url).first()
                    if existing:
                        continue
                        
                    title = entry.get('title', 'No title')
                    summary_text = entry.get('summary', '') or entry.get('description', '')
                    
                    # Claude 점수 책정
                    prompt = PROMPT_TEMPLATE.format(title=title, summary=summary_text[:1500], source=source_name)
                    
                    response = client.messages.create(
                        model="claude-3-haiku-20240307",
                        max_tokens=300,
                        system="당신은 최고 수준의 국제정치 및 기술 트렌드 분석가입니다.",
                        messages=[{"role": "user", "content": prompt}]
                    )
                    
                    response_text = response.content[0].text
                    import json
                    try:
                        # Find json block if surrounded by markdown
                        if "{" in response_text and "}" in response_text:
                            start = response_text.find("{")
                            end = response_text.rfind("}") + 1
                            json_str = response_text[start:end]
                            result = json.loads(json_str)
                            score = min(int(result.get("score", 0)), 10)
                            summary = result.get("korean_summary", "")
                        else:
                            score = 0
                            summary = ""
                    except Exception as e:
                        logger.error(f"Failed to parse Claude output: {e}")
                        score = 0
                        summary = "분석 실패"
                    
                    # 9점 이상은 즉시 알림, 7~8점은 별도, 6점 이하는 요약 대기
                    # 야간 시간(02:00 ~ 06:00)에는 발송 보류
                    now = datetime.now()
                    is_night = dtime(2, 0) <= now.time() < dtime(6, 0)
                    
                    status = 'pending'
                    if score >= 9:
                        if is_night:
                            status = 'queued_for_morning'
                        else:
                            send_telegram_alert(source_name, title, url, score, summary, is_urgent=True)
                            status = 'sent'
                    elif 7 <= score <= 8:
                        if is_night:
                            status = 'queued_for_morning'
                        else:
                            send_telegram_alert(source_name, title, url, score, summary)
                            status = 'sent'
                    else:
                        status = 'queued_for_summary'
                        
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
                logger.error(f"Error polling {source_name}: {e}")

def send_telegram_alert(source, title, url, score, summary, is_urgent=False):
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('AESA_TELEGRAM_CHANNEL_ID', os.environ.get('TELEGRAM_CHAT_ID'))
    
    if not bot_token or not chat_id:
        logger.warning("Telegram config missing.")
        return
        
    icon = "🚨 [긴급/특종 AESA 알림]" if is_urgent else "🔔 [AESA 주요 알림]"
    text = f"{icon}\n\n"
    text += f"*{source}* (점수: {score}/10)\n"
    text += f"[{title}]({url})\n\n"
    text += f"💡 1줄 요약:\n{summary}"
    
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
