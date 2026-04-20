import os
import json
import asyncio
import logging
import psycopg2
import requests
from bs4 import BeautifulSoup
from anthropic import Anthropic
from playwright.async_api import async_playwright
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 환경변수 로드
DATABASE_URL = os.environ.get('DATABASE_URL')
NAVER_CLIENT_ID = os.environ.get('NAVER_CLIENT_ID')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')

BOT_TOKEN_SCRAP = os.environ.get('SCRAP_BOT_TOKEN')
CHAT_ID_SCRAP = os.environ.get('SCRAP_CHAT_ID', '5132309076')
BOT_TOKEN_NR = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
CHAT_ID_NR = '@gazzzza2025'

CANDIDATES = {
    "서울": [("정원오", "민주"), ("오세훈", "국힘")],
    "경기": [("추미애", "민주"), ("양향자", "국힘"), ("함진규", "국힘"), ("조광한", "국힘"), ("이성배", "국힘")],
    "인천": [("박찬대", "민주"), ("유정복", "국힘")],
    "강원": [("우상호", "민주"), ("김진태", "국힘")],
    "대전": [("허태정", "민주"), ("이장우", "국힘")],
    "세종": [("조상호", "민주"), ("최민호", "국힘"), ("황운하", "혁신")],
    "충남": [("박수현", "민주"), ("김태흠", "국힘")],
    "충북": [("신용한", "민주"), ("김영환", "국힘"), ("윤갑근", "국힘")],
    "대구": [("김부겸", "민주"), ("유영하", "국힘"), ("추경호", "국힘"), ("주호영", "무소속"), ("이진숙", "무소속")],
    "경북": [("오중기", "민주"), ("이철우", "국힘")],
    "부산": [("전재수", "민주"), ("박형준", "국힘")],
    "울산": [("김상욱", "민주"), ("김두겸", "국힘"), ("김종훈", "진보"), ("박맹우", "무소속")],
    "경남": [("김경수", "민주"), ("박완수", "국힘")],
    "광주·전남": [("민형배", "민주"), ("이정현", "국힘"), ("안태욱", "국힘")],
    "전북": [("이원택", "민주")],
    "제주": [("위성곤", "민주"), ("문대림", "민주"), ("문성유", "국힘")]
}

def get_db_connection():
    db_url = DATABASE_URL
    if not db_url:
        logger.warning("DATABASE_URL is not set.")
        return None
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
    
    try:
        conn = psycopg2.connect(db_url)
        return conn
    except Exception as e:
        logger.error(f"DB 연결 오류: {e}")
        return None

def init_candidate_db():
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS candidate_status (
                id SERIAL PRIMARY KEY,
                region VARCHAR(30),
                level VARCHAR(10),
                candidate VARCHAR(20),
                party VARCHAR(10),
                status VARCHAR(20),
                note TEXT,
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(region, candidate, party)
            );
        """)
        
        # 초기 데이터 (CANDIDATES 전체를 '경선중' 상태로 등록. 이미 있으면 무시)
        for region, cands in CANDIDATES.items():
            for name, party in cands:
                cur.execute("""
                    INSERT INTO candidate_status (region, level, candidate, party, status)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (region, candidate, party) DO NOTHING
                """, (region, '광역', name, party, '경선중'))
                
        conn.commit()
        cur.close()
        logger.info("candidate_status DB 초기화 완료.")
    except Exception as e:
        logger.error(f"DB 초기화 중 오류: {e}")
        conn.rollback()
    finally:
        conn.close()

def search_candidate_news():
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.warning("Naver API 키가 없습니다.")
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    query = "2026 지방선거 후보 경선 확정 사퇴"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {
        "query": query,
        "display": 10,
        "sort": "date"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        links = []
        for item in data.get('items', []):
            link = item.get('link', '')
            if 'naver.com' in link:
                links.append(link)
            else:
                links.append(item.get('originallink', link))
        return links
    except Exception as e:
        logger.error(f"네이버 뉴스 검색 오류: {e}")
        return []

async def fetch_article_text(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until='domcontentloaded', timeout=15000)

                content = ""
                if "naver.com" in url:
                    elem = await page.query_selector("#dic_area")
                    if elem:
                        content = await elem.inner_text()

                if not content:
                    paragraphs = await page.query_selector_all("p")
                    text_blocks = []
                    for p_elem in paragraphs:
                        text_blocks.append(await p_elem.inner_text())
                    content = "\n".join(text_blocks)

                return content.strip()
            finally:
                await browser.close()
    except Exception as e:
        logger.error(f"본문 로드 오류 ({url}): {e}")
        return ""

def parse_candidate_updates(text):
    if not ANTHROPIC_API_KEY:
        return None
        
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    system_prompt = "선거 후보 변동사항 추출 전문가. 변경사항이 발견되면 JSON 배열을 반환하고 없으면 빈 배열 [] 반환."
    user_prompt = f"""
    다음 기사에서 2026년 지방선거 '광역/기초/교육감' 출마 후보자들의 상태 변동(경선확정, 단수공천, 사퇴 등)을 추출해줘.
    결과는 반드시 아래 JSON 배열 형식으로만 반환해줘. 없으면 [] 반환.
    
    [
      {{
        "region": "지역명 (서울, 경기 남양주시 등)",
        "level": "광역/기초/교육감 중 하나",
        "candidate": "후보명",
        "party": "정당명",
        "status": "예비후보/확정/경선중/사퇴 등 상태값 1개",
        "note": "변동사유 1문장"
      }}
    ]
    
    기사: {text[:2000]}
    """
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        
        content = response.content[0].text.strip()
        json_str = content
        if "```json" in content:
            json_str = content.split("```json")[-1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[-1].split("```")[0].strip()
            
        res = json.loads(json_str)
        if isinstance(res, list):
            return res
        return []
    except Exception as e:
        logger.error(f"Claude API 파싱 오류: {e}")
        return None

def broadcast_update(update_obj):
    # 포맷 구성
    region = update_obj.get("region", "미상")
    party = update_obj.get("party", "미정")
    candidate = update_obj.get("candidate", "무명")
    status = update_obj.get("status", "")
    note = update_obj.get("note", "")
    
    now_str = datetime.now().strftime("%Y.%m.%d %H:%M")
    
    message = f"""🚨 후보 현황 업데이트 ({now_str})

◇{region} {party}
→ {candidate} 후보: {status} ({note})

출처: https://t.me/gazzzza2025
(실시간 텔레그램 정보방)
"""
    # 텔레그램 발송
    targets = []
    if BOT_TOKEN_SCRAP:
        targets.append((BOT_TOKEN_SCRAP, CHAT_ID_SCRAP))
    if BOT_TOKEN_NR:
        targets.append((BOT_TOKEN_NR, CHAT_ID_NR))
        
    for token, chat_id in targets:
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        try:
            requests.post(url, json={
                'chat_id': chat_id,
                'text': message,
                'disable_web_page_preview': True
            }, timeout=10)
        except Exception as e:
            logger.error(f"텔레그램 발송 예외: {e}")

def process_and_check_updates(parsed_updates):
    if not parsed_updates:
        return
        
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cur = conn.cursor()
        for update in parsed_updates:
            region = update.get('region')
            candidate = update.get('candidate')
            party = update.get('party')
            status = update.get('status')
            level = update.get('level', '기타')
            note = update.get('note', '')
            
            if not region or not candidate or not party or not status:
                continue
                
            # 기존 상태 체크
            cur.execute("""
                SELECT status FROM candidate_status
                WHERE region = %s AND candidate = %s AND party = %s
            """, (region, candidate, party))
            
            row = cur.fetchone()
            if row:
                old_status = row[0]
                if old_status != status:
                    # 변경 발생
                    cur.execute("""
                        UPDATE candidate_status 
                        SET status = %s, note = %s, updated_at = NOW()
                        WHERE region = %s AND candidate = %s AND party = %s
                    """, (status, note, region, candidate, party))
                    broadcast_update(update)
            else:
                # 신규 후보 발견
                cur.execute("""
                    INSERT INTO candidate_status (region, level, candidate, party, status, note)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (region, level, candidate, party, status, note))
                broadcast_update(update)
                
        conn.commit()
    except Exception as e:
        logger.error(f"DB 처리 중 오류: {e}")
        conn.rollback()
    finally:
        conn.close()

async def run_candidate_tracker_async():
    logger.info("후보 현황 트래커 시작...")
    init_candidate_db()
    
    links = search_candidate_news()
    for link in links:
        text = await fetch_article_text(link)
        if len(text) > 100:
            updates = parse_candidate_updates(text)
            process_and_check_updates(updates)
            
    logger.info("후보 현황 트래커 작업 완료.")

def check_candidate_changes():
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(run_candidate_tracker_async())
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()

if __name__ == "__main__":
    check_candidate_changes()
