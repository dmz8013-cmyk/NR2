import os
import json
import feedparser
from datetime import datetime, timedelta
import pytz
from time import sleep

from anthropic import Anthropic
from app import db
from app.models.post import Post
from app.models.briefing import Briefing
from app.utils.telegram_notify import notify_new_post

# RSS 소스
RSS_SOURCES = {
    '연합뉴스': 'https://www.yonhapnews.co.kr/rss/0200000000.xml',
    '한겨레': 'https://www.hani.co.kr/rss/',
    '조선일보': 'https://www.chosun.com/arc/outboundfeeds/rss/',
    '경향신문': 'https://www.khan.co.kr/rss/rssdata/total_news.xml'
}

# AESA 브리핑 프롬프트
SYSTEM_PROMPT = """당신은 누렁이 AESA 브리핑 에이전트입니다. 
기사를 분석하여 다음 형식으로 응답하세요:
- AESA축: [A]AI·Tech / [E]국제정치 / [A2]문화 / [S]전략 중 해당 항목
- 편향: 진보/보수/중립
- 친중/친미/중립
- 핵심요약: 2문장
형식: JSON으로만 응답
예시: {"aesa": "[E]국제정치", "bias": "보수", "stance": "친미", "summary": "첫번째 문장입니다. 두번째 문장입니다."}"""


def fetch_and_filter_rss(url, max_articles=5):
    """RSS 피드를 가져오고 최근 24시간 이내의 상위 N개 기사를 필터링합니다."""
    feed = feedparser.parse(url)
    articles = []
    
    # KST 기준 24시간 전 (UTC 기준 처리 지원)
    now = datetime.now(pytz.utc)
    one_day_ago = now - timedelta(hours=24)
    
    for entry in feed.entries:
        if len(articles) >= max_articles:
            break
            
        # 발행일 파싱
        try:
            # 파싱 성공 시
            dt = datetime(*entry.published_parsed[:6], tzinfo=pytz.utc)
            if dt >= one_day_ago:
                articles.append({
                    'title': entry.title,
                    'link': entry.link,
                    'summary': getattr(entry, 'summary', getattr(entry, 'description', '')),
                })
        except Exception:
            # 파싱 실패나 published_parsed가 없는 경우에도 담아줍니다.
            articles.append({
                'title': entry.title,
                'link': entry.link,
                'summary': getattr(entry, 'summary', getattr(entry, 'description', '')),
            })
            
    return articles


def analyze_article_with_claude(article):
    """클로드 API를 사용하여 기사를 분석합니다."""
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return None
        
    client = Anthropic(api_key=api_key)
    
    user_message = f"기사 제목: {article['title']}\n기사 내용: {article['summary']}"
    
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message}
            ],
            temperature=0.2
        )
        
        # JSON 부분 추출
        result_text = response.content[0].text.strip()
        if result_text.startswith('```'):
            lines = result_text.split('\n')
            if len(lines) >= 3:
                result_text = '\n'.join(lines[1:-1])
        
        return json.loads(result_text)
    except Exception as e:
        print(f"클로드 분석 에러: {str(e)}")
        return None


def run_briefing(app_context):
    """브리핑 수집, 분석 및 생성 메인 프로세스"""
    with app_context:
        all_analyses = {}
        total_count = 0
        
        for source_name, url in RSS_SOURCES.items():
            print(f"[{source_name}] RSS 수집 중...")
            articles = fetch_and_filter_rss(url, max_articles=5)
            
            source_results = []
            for article in articles:
                analysis = analyze_article_with_claude(article)
                if analysis:
                    source_results.append({
                        'article': article,
                        'analysis': analysis
                    })
                    total_count += 1
                sleep(1) # API Rate limit 방지
                
            if source_results:
                all_analyses[source_name] = source_results
                
        if total_count == 0:
            return False, "수집된 기사가 없습니다."
            
        # 본문 생성
        html_content = f"<p>AI 에이전트가 주요 언론사의 RSS를 분석한 오늘의 모닝 AESA 브리핑입니다. (총 {total_count}건)</p><hr/>"
        
        for source, items in all_analyses.items():
            html_content += f"<h3 style='color:#C1121F; margin-top:20px;'><strong>■ {source}</strong></h3>"
            for idx, item in enumerate(items, 1):
                art = item['article']
                ana = item['analysis']
                aesa = ana.get('aesa', '')
                bias = ana.get('bias', '')
                stance = ana.get('stance', '')
                summary = ana.get('summary', '')
                
                html_content += f"""
                <div style="margin-bottom: 16px; padding: 12px; background-color: #f9fafb; border-left: 4px solid #3b82f6; border-radius: 4px;">
                    <p style="margin-bottom: 8px;"><strong><a href="{art['link']}" target="_blank" style="text-decoration:none; color:#1a1a1a;">{idx}. {art['title']}</a></strong></p>
                    <p style="margin-bottom: 6px; font-size: 13px;">
                        <span style="background:#e0e7ff; color:#3730a3; padding:2px 6px; border-radius:4px; margin-right:4px; font-weight:600;">{aesa}</span>
                        <span style="background:#fce7f3; color:#9d174d; padding:2px 6px; border-radius:4px; margin-right:4px; font-weight:600;">{bias}</span>
                        <span style="background:#dcfce7; color:#166534; padding:2px 6px; border-radius:4px; font-weight:600;">{stance}</span>
                    </p>
                    <p style="font-size: 14px; color: #4b5563; line-height: 1.5; margin-bottom: 0;">{summary}</p>
                </div>
                """
                
        html_content += "<br/><p style='font-size:12px; color:#9ca3af;'>* 본 브리핑은 claude-haiku 기반으로 자동 생성되었습니다.</p>"
        
        today_str = datetime.now(pytz.timezone('Asia/Seoul')).strftime("%Y-%m-%d")
        title = f"🌅 AESA 모닝 브리핑 — {today_str}"
        
        # 1. Post 모델로 저장
        post = Post(
            title=title,
            content=html_content,
            board_type='aesa',
            user_id=1 # 관리자 계정 하드코딩
        )
        db.session.add(post)
        db.session.flush() # id 할당
        
        # 2. Briefing 모델에도 아카이빙
        briefing = Briefing(
            briefing_type='ai_morning',
            title=title,
            content=html_content,
            article_count=total_count
        )
        db.session.add(briefing)
        
        db.session.commit()
        
        # 3. 텔레그램 알림 발송
        try:
            notify_new_post(post)
        except Exception as e:
            print(f"텔레그램 발송 에러: {str(e)}")
            
        return True, "Success"
