import os
import re
import json
import asyncio
import logging
import psycopg2
import requests
from urllib.parse import urlparse
from datetime import datetime
from bs4 import BeautifulSoup
from anthropic import Anthropic
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 환경변수 로드
DATABASE_URL = os.environ.get('DATABASE_URL')
NAVER_CLIENT_ID = os.environ.get('NAVER_CLIENT_ID')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
BOT_TOKEN = os.environ.get('SCRAP_BOT_TOKEN')
CHAT_ID = os.environ.get('SCRAP_CHAT_ID', '5132309076')  # 기존 editorial_bot.py와 동일한 값으로 fallback

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

REGIONS = list(CANDIDATES.keys())

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

def init_db():
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS election_polls (
                id SERIAL PRIMARY KEY,
                region VARCHAR(20) NOT NULL,
                candidate VARCHAR(20) NOT NULL,
                party VARCHAR(10) NOT NULL,
                percentage FLOAT,
                pollster VARCHAR(50),
                poll_date VARCHAR(20),
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(region, candidate, pollster, poll_date)
            );
        """)
        
        initial_data = [
            ('서울', '정원오', '민주', 42.3, '여론조사꽃', '2026.04.17'),
            ('서울', '오세훈', '국힘', 21.7, '여론조사꽃', '2026.04.17'),
            ('서울', '정원오', '민주', 50.0, 'JTBC', '2026.04.15'),
            ('서울', '오세훈', '국힘', 34.0, 'JTBC', '2026.04.15'),
            ('부산', '전재수', '민주', 49.9, '여론조사꽃', '2026.04.17'),
            ('부산', '박형준', '국힘', 41.2, '여론조사꽃', '2026.04.17'),
            ('울산', '김상욱', '민주', 38.9, '여론조사꽃', '2026.04.17'),
            ('울산', '김두겸', '국힘', 29.2, '여론조사꽃', '2026.04.17'),
            ('대구', '김부겸', '민주', 54.0, '세계일보', '2026.04.13'),
            ('대구', '이진숙', '무소속', 37.0, '세계일보', '2026.04.13'),
            ('경북', '오중기', '민주', 30.5, '미확인', '미확인'),
            ('경북', '이철우', '국힘', 57.9, '미확인', '미확인')
        ]
        
        for row in initial_data:
            cur.execute("""
                INSERT INTO election_polls (region, candidate, party, percentage, pollster, poll_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (region, candidate, pollster, poll_date) DO NOTHING
            """, row)
            
        conn.commit()
        cur.close()
        logger.info("DB 초기화 완료.")
    except Exception as e:
        logger.error(f"DB 초기화 중 오류: {e}")
        conn.rollback()
    finally:
        conn.close()

def search_naver_news(region):
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.warning("Naver API 키가 없습니다.")
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
    query = f"2026 지방선거 여론조사 {region} 광역단체장"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    params = {
        "query": query,
        "display": 5,
        "sort": "date"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        links = []
        for item in data.get('items', []):
            link = item.get('link', '')
            # 네이버 뉴스 링크 선호, 없으면 원본 링크
            if 'naver.com' in link:
                links.append(link)
            else:
                links.append(item.get('originallink', link))
        return links
    except Exception as e:
        logger.error(f"[{region}] 네이버 뉴스 검색 오류: {e}")
        return []

async def fetch_article_text(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until='domcontentloaded', timeout=15000)
            
            # 본문을 찾기 위한 간단한 휴리스틱
            content = ""
            if "naver.com" in url:
                elem = await page.query_selector("#dic_area")
                if elem:
                    content = await elem.inner_text()
            
            if not content:
                # 일반 기사 본문 추출 (p 태그 위주)
                paragraphs = await page.query_selector_all("p")
                text_blocks = []
                for p_elem in paragraphs:
                    text_blocks.append(await p_elem.inner_text())
                content = "\n".join(text_blocks)
                
            await browser.close()
            return content.strip()
    except Exception as e:
        logger.error(f"본문 로드 중 오류 ({url}): {e}")
        return ""

def parse_poll_data_with_claude(region, text):
    if not ANTHROPIC_API_KEY:
        logger.warning("Anthropic API 키가 없습니다.")
        return None
        
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    
    system_prompt = "선거 여론조사 수치 추출 전문가. JSON만 반환."
    user_prompt = f"""
    다음 기사에서 2026 지방선거 {region} 광역단체장 여론조사 수치를 추출해줘.
    없으면 null 반환. 아래 JSON 형식으로만:
    {{
      "pollster": "조사기관명",
      "poll_date": "YYYY.MM.DD",
      "results": [
        {{"candidate": "후보명", "percentage": 숫자}}
      ]
    }}
    기사: {text[:2000]}
    """
    
    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=500,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_prompt}
            ]
        )
        
        # JSON 포맷팅 지원을 위해 앞뒤 정리
        content = response.content[0].text.strip()
        json_str = content
        if "```json" in content:
            json_str = content.split("```json")[-1].split("```")[0].strip()
        elif "```" in content:
            json_str = content.split("```")[-1].split("```")[0].strip()
            
        if json_str == "null":
            return None
            
        return json.loads(json_str)
    except Exception as e:
        logger.error(f"[{region}] Claude API 파싱 오류: {e}")
        return None

def upsert_poll_data(region, poll_data):
    if not poll_data or "results" not in poll_data:
        return
        
    pollster = poll_data.get("pollster", "미확인")
    poll_date = poll_data.get("poll_date", "미확인")
    results = poll_data.get("results", [])
    
    conn = get_db_connection()
    if not conn:
        return
        
    try:
        cur = conn.cursor()
        
        # 맵핑용 딕셔너리 생성 (CANDIDATES 기반)
        candidate_to_party = {name: party for name, party in CANDIDATES.get(region, [])}
        
        for res in results:
            candidate = res.get("candidate")
            percentage = res.get("percentage")
            
            if not candidate or percentage is None:
                continue
                
            # 정당 매칭 (미등록 후보는 '기타' 혹은 '무소속' 처리)
            party = candidate_to_party.get(candidate, "기타")
            
            cur.execute("""
                INSERT INTO election_polls (region, candidate, party, percentage, pollster, poll_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (region, candidate, pollster, poll_date) DO NOTHING
            """, (region, candidate, party, percentage, pollster, poll_date))
            
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"[{region}] DB 저장 중 오류: {e}")
        conn.rollback()
    finally:
        conn.close()

def format_poll_message():
    conn = get_db_connection()
    if not conn:
        return "여론조사 데이터를 불러올 수 없습니다."
        
    lines = []
    lines.append("📊 2026 지방선거 광역단체장 여론조사 현황 📊")
    lines.append("")
    
    try:
        cur = conn.cursor()
        
        for region in REGIONS:
            lines.append(f"◇{region}")
            
            # 1. 고정 후보자 리스트 출력
            for candidate, party in CANDIDATES[region]:
                lines.append(f"({party}) {candidate}")
                
            # 2. 최신 여론조사 결과 가져오기
            cur.execute("""
                SELECT DISTINCT pollster, poll_date 
                FROM election_polls 
                WHERE region = %s 
                ORDER BY poll_date DESC, pollster DESC
                LIMIT 2
            """, (region,))
            
            recent_polls = cur.fetchall()
            
            if not recent_polls:
                lines.append("▶ 여론조사 미발표")
            else:
                for pollster, poll_date in recent_polls:
                    # 해당 조사의 결과 가져오기
                    cur.execute("""
                        SELECT candidate, percentage 
                        FROM election_polls 
                        WHERE region = %s AND pollster = %s AND poll_date = %s
                        ORDER BY percentage DESC
                    """, (region, pollster, poll_date))
                    
                    results = cur.fetchall()
                    if results:
                        formatted_results = " / ".join([f"{cand} {pct}%" for cand, pct in results])
                        lines.append(f"📈 {formatted_results} [{pollster} / {poll_date}]")
            
            lines.append("") # 지역 간 공백
            
        cur.close()
    except Exception as e:
        logger.error(f"메시지 포맷팅 중 오류: {e}")
        return "데이터 처리 중 오류가 발생했습니다."
    finally:
        conn.close()
        
    return "\n".join(lines).strip()

def send_telegram_message(message):
    if not BOT_TOKEN:
        logger.error("SCRAP_BOT_TOKEN 이 설정되지 않았습니다.")
        return
        
    # 메시지 분할 전송 (텔레그램 글자 수 제한: 4096자)
    parts = []
    current = ""
    for line in message.split('\n'):
        if len(current) + len(line) + 1 > 4000:
            parts.append(current)
            current = line
        else:
            current += '\n' + line if current else line
    if current:
        parts.append(current)

    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    for part in parts:
        try:
            resp = requests.post(url, json={
                'chat_id': CHAT_ID,
                'text': part,
            }, timeout=10)
            if resp.status_code == 200:
                logger.info(f"텔레그램 메시지 전송 완료 ({len(part)}자)")
            else:
                logger.error(f"텔레그램 메시지 전송 실패: {resp.text}")
        except Exception as e:
            logger.error(f"텔레그램 메시지 전송 오류: {e}")

async def run_poll_tracker_async():
    logger.info("여론조사 트래커 시작...")
    init_db()
    
    for region in REGIONS:
        logger.info(f"[{region}] 수집 시작...")
        
        # 1. 네이버 뉴스 검색
        links = search_naver_news(region)
        
        # 2~4. 본문 로드 및 파싱, DB 저장
        for link in links:
            text = await fetch_article_text(link)
            if len(text) > 100:  # 너무 짧은 본문은 유효하지 않음
                poll_data = parse_poll_data_with_claude(region, text)
                if poll_data:
                    upsert_poll_data(region, poll_data)
                    logger.info(f"[{region}] 데이터 갱신 완료: {poll_data.get('pollster')}")
                    
        await asyncio.sleep(2) # rate limit 고려
        
    # 5. 메시지 생성 및 발송
    message = format_poll_message()
    send_telegram_message(message)
    
    logger.info("여론조사 트래커 완료.")

def run_poll_tracker():
    asyncio.run(run_poll_tracker_async())

if __name__ == "__main__":
    run_poll_tracker()
