import os
import re
import asyncio
import html
import requests
import urllib.parse
from datetime import datetime, date
import logging
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# 이메일 주소 패턴 — 뉴스1 기사 본문에 기자 이메일이 섞여 나오는 문제 방지
EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

logger = logging.getLogger(__name__)

# 수집할 섹션 목록 - 뉴스1
NEWS1_TARGETS = [
    '◇청와대', '◇대통령실', '◇국무총리실', '◇국회', 
    '◇더불어민주당', '◇국민의힘', '◇조국혁신당', 
    '◇진보당', '◇개혁신당', '◇기본소득당', '◇사회민주당'
]

# 수집할 섹션 목록 - 국회
ASSEMBLY_TARGETS = [
    '◇본회의 및 상임위원회', '◇의원실 세미나', '◇소통관 기자회견'
]

def fetch_news1_schedule_url():
    """네이버 검색 API로 당일 뉴스1 정치 일정 기사 URL 획득 (fallback 쿼리 지원)"""
    client_id = os.environ.get('NAVER_CLIENT_ID')
    client_secret = os.environ.get('NAVER_CLIENT_SECRET')
    if not client_id or not client_secret:
        logger.error("NAVER API credentials missing")
        return None

    queries = [
        '주요일정 정치',
        '오늘의 주요일정 정치',
        '주요일정 정치 정부',
    ]
    headers = {
        'X-Naver-Client-Id': client_id,
        'X-Naver-Client-Secret': client_secret
    }

    for query in queries:
        url = f'https://openapi.naver.com/v1/search/news.json?query={urllib.parse.quote(query)}&display=100&sort=date'
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            data = resp.json()
            for item in data.get('items', []):
                originallink = item.get('originallink', '')
                if 'news1.kr' in originallink:
                    logger.info(f"뉴스1 기사 발견 (쿼리: '{query}'): {originallink}")
                    return originallink
            logger.info(f"쿼리 '{query}'에서 news1.kr 기사 없음, 다음 쿼리 시도")
        except Exception as e:
            logger.error(f"Naver API error (쿼리: '{query}'): {e}")

    logger.warning("모든 쿼리에서 뉴스1 기사를 찾지 못했습니다.")
    return None

async def parse_schedule_text(url, locator_selector_primary, targets):
    """Playwright로 해당 URL의 특정 영역 텍스트를 추출해 타겟 섹션만 파싱"""
    results = {t: [] for t in targets}
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page(user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36')
            await page.goto(url, wait_until='domcontentloaded', timeout=15000)
            await page.wait_for_timeout(3000) # JS Render 대기
            
            selectors = [locator_selector_primary, '.detail_body', '#articleBody', '.article_body', '.news_body', '#nowNa-text', 'article']
            
            raw_text = ""
            for sel in selectors:
                try:
                    target_el = page.locator(sel).first
                    await target_el.wait_for(timeout=2000)
                    text = await target_el.inner_text()
                    if len(text) > 50:
                        raw_text = text
                        break
                except:
                    continue
            
            if not raw_text:
                # Fallback to BeautifulSoup
                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                for sel in selectors:
                    target_el = soup.select_one(sel)
                    if target_el:
                        raw_text = target_el.get_text('\n', strip=True)
                        if len(raw_text) > 50:
                            break
            
            if raw_text:
                lines = raw_text.split('\n')
                current_section = None
                
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # 체크: 헤더 라인인가?
                    if line.startswith('◇') or line.startswith('◆') or line.startswith('['):
                        normalized_line = line.replace(' ', '')
                        current_section = None
                        for t in targets:
                            if t.replace(' ', '') == normalized_line or t == line:
                                current_section = t
                                break
                    elif current_section:
                        # 예외 정리
                        if line.startswith('※') or '상기 일정은' in line or '받아보실 수 있습니다' in line or '무단 전재' in line or '기사제보 및' in line:
                            continue
                        # 이메일 주소 포함 라인 제거
                        if EMAIL_PATTERN.search(line):
                            continue
                        if 'mailto:' in line:
                            continue
                        results[current_section].append(line)
        except Exception as e:
            logger.error(f"Playwright error on {url}: {e}")
        finally:
            await browser.close()
            
    return results

def format_schedule_message(news1_data, assembly_data):
    today_dt = datetime.now()
    today_date = date.today()
    date_str = today_dt.strftime('%Y.%m.%d')
    lines = []
    
    election_day = date(2026, 6, 3)
    dday = (election_day - today_date).days

    schedule_items = [
        ("예비후보 등록 마감", date(2026, 4, 30)),
        ("본후보 등록", date(2026, 5, 15)),
        ("공식 선거운동 시작", date(2026, 5, 20)),
        ("사전투표", date(2026, 5, 29)),
        ("선거일", date(2026, 6, 3)),
    ]

    lines.append(f'⏳ 6.3 지방선거까지 D-{dday}')
    for name, item_date in schedule_items:
        diff = (item_date - today_date).days
        if diff > 0:
            status = f"D-{diff}"
        elif diff == 0:
            status = "오늘!"
        else:
            status = "✅완료"
        lines.append(f"- {name}: {status}")
    lines.append('')
    
    # 헤더
    lines.append(f'📌📌📌주요 일정({date_str})📌📌📌')
    lines.append('')
    lines.append('출처 : https://buly.kr/7mBN720')
    lines.append('')
    
    # 1. 뉴스1 수집 결과
    for category in NEWS1_TARGETS:
        items = news1_data.get(category, [])
        if items:
            lines.append(f'<b>{category}</b>')
            for item in items:
                lines.append(html.escape(item))
            lines.append('')

    # 2. 국회 수집 결과
    for category in ASSEMBLY_TARGETS:
        items = assembly_data.get(category, [])
        if items:
            lines.append(f'<b>{category}</b>')
            for item in items:
                lines.append(html.escape(item))
            lines.append('')
            
    # 푸터
    lines.append('출처: https://t.me/gazzzza2025')
    lines.append('(실시간 텔레그램 정보방)')
    
    return '\n'.join(lines).strip()

def _run_schedule_job(bot_token, chat_id, job_name="일정봇"):
    logger.info(f"=== {job_name} 시작 ===")

    news1_url = fetch_news1_schedule_url()

    # 명시적 loop 생성 후 try/finally로 반드시 close — Playwright 서브프로세스 누수 방지.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        news1_data = {t: [] for t in NEWS1_TARGETS}
        if news1_url:
            logger.info(f"파싱 시작: News1 ({news1_url})")
            news1_data = loop.run_until_complete(parse_schedule_text(news1_url, '.detail_body', NEWS1_TARGETS))
        else:
            logger.warning("뉴스1 일정 기사를 찾지 못했습니다.")

        logger.info("파싱 시작: 국회 (https://assembly.go.kr/portal/main/main.do)")
        assembly_url = 'https://assembly.go.kr/portal/main/main.do'
        assembly_data = loop.run_until_complete(parse_schedule_text(assembly_url, '#nowNa-text', ASSEMBLY_TARGETS))
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()
    
    message = format_schedule_message(news1_data, assembly_data)
    
    # 분할 전송 방어 로직
    parts = []
    current = ''
    for line in message.split('\n'):
        if len(current) + len(line) + 1 > 4000:
            parts.append(current)
            current = line
        else:
            current += '\n' + line if current else line
    if current:
        parts.append(current)
        
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    for part in parts:
        try:
            resp = requests.post(url, json={
                'chat_id': chat_id,
                'text': part,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
            }, timeout=10)
            if resp.status_code == 200:
                logger.info(f"{job_name} 발송 완료 ({len(part)}자)")
                print(f"{job_name} 발송 완료 ({len(part)}자)")
            else:
                logger.error(f"발송 에러: {resp.text}")
                print(f"발송 에러: {resp.text}")
        except Exception as e:
            logger.error(f"전송 예외: {e}")
            
    logger.info(f"=== {job_name} 종료 ===")

def send_schedule():
    BOT_TOKEN = os.environ.get('SCRAP_BOT_TOKEN')
    CHAT_ID = os.environ.get('SCRAP_CHAT_ID', '5132309076')
    
    if not BOT_TOKEN:
        logger.error("SCRAP_BOT_TOKEN 없음")
        return
        
    _run_schedule_job(BOT_TOKEN, CHAT_ID, "일정봇")

def send_schedule_nureongi():
    """누렁이 정보방용 주요 일정 - 오전 7:30 발송"""
    NUREONGI_TOKEN = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
    NUREONGI_CHAT = '@gazzzza2025'
    
    if not NUREONGI_TOKEN:
        print('NUREONGI_NEWS_BOT_TOKEN 없음')
        return
        
    _run_schedule_job(NUREONGI_TOKEN, NUREONGI_CHAT, "누렁이 일정봇")

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    send_schedule()
    send_schedule_nureongi()
