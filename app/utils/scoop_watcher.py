import os
import feedparser
import requests
from datetime import datetime
from app import db
from app.models.scoop_alert import ScoopAlert

# RSS 소스
RSS_SOURCES = {
    '연합뉴스': 'https://www.yonhapnews.co.kr/rss/0200000000.xml',
    '조선일보': 'https://www.chosun.com/arc/outboundfeeds/rss/',
    '한겨레': 'https://www.hani.co.kr/rss/',
    '경향신문': 'https://www.khan.co.kr/rss/rssdata/total_news.xml',
    '중앙일보': 'https://rss.joins.com/joins_news_list.xml',
    '동아일보': 'https://rss.donga.com/total.xml'
}

def send_telegram_alert(source, title, link):
    from flask import current_app
    
    token = current_app.config.get('TELEGRAM_BOT_TOKEN') or os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = current_app.config.get('TELEGRAM_CHAT_ID') or os.environ.get('TELEGRAM_CHAT_ID')
    
    if not token or not chat_id:
        return
        
    text = f"🚨 [단독] 포착\n\n📰 {source}\n{title}\n\n🔗 {link}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    try:
        requests.post(url, json={
            'chat_id': chat_id,
            'text': text,
            'disable_web_page_preview': False
        }, timeout=5)
    except Exception as e:
        print(f"ScoopWatcher Telegram 발송 에러: {e}")

def scoop_job(app_context):
    """지정된 RSS 피드에서 단독 기사를 감지합니다."""
    with app_context:
        for source, url in RSS_SOURCES.items():
            try:
                feed = feedparser.parse(url)
                
                for entry in feed.entries:
                    title = getattr(entry, 'title', '')
                    link = getattr(entry, 'link', '')
                    
                    if not title or not link:
                        continue
                        
                    if '[단독]' in title or '단독' in title:
                        # 중복 여부 확인
                        existing = ScoopAlert.query.filter_by(link=link).first()
                        if not existing:
                            # 새 알림 저장
                            new_alert = ScoopAlert(title=title, link=link, source=source)
                            db.session.add(new_alert)
                            db.session.commit()
                            
                            # 알림 발송
                            send_telegram_alert(source, title, link)
            except Exception as e:
                print(f"[{source}] 단독 기사 파싱 에러: {e}")
