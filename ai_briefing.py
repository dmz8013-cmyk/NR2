import os
import json
import logging
from datetime import datetime, timedelta
import anthropic
import requests

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
SENT_NEWS_FILE = '/tmp/sent_news.json'

def get_recent_articles():
    try:
        with open(SENT_NEWS_FILE, 'r', encoding='utf-8') as f:
            sent_news = json.load(f)
    except:
        return []
    now = datetime.now()
    cutoff = now - timedelta(hours=12)
    recent = []
    for url, data in sent_news.items():
        try:
            sent_at = datetime.fromisoformat(data.get('sent_at', ''))
            if sent_at >= cutoff:
                recent.append({'title': data.get('title', ''), 'section': data.get('section', '')})
        except:
            continue
    return recent

def generate_briefing(articles):
    if not articles:
        return None
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    period = '아침' if datetime.now().hour < 12 else '저녁'
    date_str = datetime.now().strftime('%Y년 %m월 %d일')
    article_text = '
'.join(['[' + a['section'] + '] ' + a['title'] for a in articles])
    lines = [
        '다음은 최근 12시간 동안 수집된 뉴스 기사 목록입니다:',
        '',
        article_text,
        '',
        '위 기사들을 바탕으로 한국어로 간결한 뉴스 브리핑을 작성해주세요.',
        '형식:',
        '- ' + date_str + ' ' + period + ' 브리핑으로 시작',
        '- 경제, AI/기술, 정치, 세계 카테고리로 분류',
        '- 각 카테고리별 핵심 내용 2-3줄 요약',
        '- 전체 길이 300자 이내',
        '- 마지막에 더 많은 뉴스: nr2.kr 추가',
    ]
    prompt = '
'.join(lines)
    message = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=1024,
        messages=[{'role': 'user', 'content': prompt}]
    )
    return message.content[0].text

def send_briefing():
    logger.info('[AI브리핑] 시작...')
    articles = get_recent_articles()
    if not articles:
        logger.info('[AI브리핑] 최근 12시간 기사 없음')
        return
    logger.info('[AI브리핑] ' + str(len(articles)) + '개 기사 수집')
    briefing = generate_briefing(articles)
    if not briefing:
        return
    url = 'https://api.telegram.org/bot' + TELEGRAM_TOKEN + '/sendMessage'
    requests.post(url, json={'chat_id': TELEGRAM_CHAT_ID, 'text': briefing, 'parse_mode': 'HTML'})
    logger.info('[AI브리핑] 전송 완료!')
