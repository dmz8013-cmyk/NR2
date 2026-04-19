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

def extract_first_json(text):
    """Claude 응답에서 첫 번째 JSON 객체만 추출 (코드펜스/복수 블록 대응)"""
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()
    brace_count = 0
    start = None
    for i, ch in enumerate(text):
        if ch == '{':
            if start is None:
                start = i
            brace_count += 1
        elif ch == '}':
            brace_count -= 1
            if brace_count == 0 and start is not None:
                return text[start:i+1]
    return None

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

REGIONS = list(CANDIDATES.keys())

BASIC_TARGETS = {
    "서울 노원구": [("조세라","무소속"),("최용갑","민주"),("홍기웅","진보")],
    "경남 김해시": [("홍태용","국힘")],
    "경기 성남시": [("신상진","국힘")],
    "울산 동구": [("김대연","민주")],
    "서울 강남구": [],
    "서울 마포구": [],
    "서울 성동구": [],
    "경기 수원시": [],
    "경기 고양시": [],
    "부산 해운대구": [],
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

def init_db():
    conn = get_db_connection()
    if not conn:
        return
    
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS election_polls (
                id SERIAL PRIMARY KEY,
                region VARCHAR(50) NOT NULL,
                candidate VARCHAR(30) NOT NULL,
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
        logger.info("election_polls DB 초기화 완료.")
    except Exception as e:
        logger.error(f"DB 초기화 중 오류: {e}")
        conn.rollback()
    finally:
        conn.close()

def search_naver_news(query):
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.warning("Naver API 키가 없습니다.")
        return []

    url = "https://openapi.naver.com/v1/search/news.json"
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
            if 'naver.com' in link: links.append(link)
            else: links.append(item.get('originallink', link))
        return links
    except Exception as e:
        logger.error(f"[{query}] 네이버 뉴스 검색 오류: {e}")
        return []

async def fetch_article_text(url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until='domcontentloaded', timeout=15000)
            
            content = ""
            if "naver.com" in url:
                elem = await page.query_selector("#dic_area")
                if elem: content = await elem.inner_text()
            
            if not content:
                paragraphs = await page.query_selector_all("p")
                content = "\n".join([await p_elem.inner_text() for p_elem in paragraphs])
                
            await browser.close()
            return content.strip()
    except Exception as e:
        logger.error(f"본문 로드 오류 ({url}): {e}")
        return ""

def parse_poll_data_with_claude(prompt_context, text, poll_type):
    if not ANTHROPIC_API_KEY:
        return None
        
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    system_prompt = "선거 여론조사 수치 추출 전문가. JSON만 반환."
    
    if poll_type == "party":
         user_prompt = f"""
         다음 기사에서 2026 지방선거 관련 또는 정례 정당 지지율 여론조사 수치를 추출해줘.
         더불어민주당, 국민의힘, 조국혁신당, 개혁신당의 수치만 찾아줘.
         없으면 null. 양식:
         {{
           "pollster": "조사기관명",
           "poll_date": "YYYY.MM.DD",
           "results": [ {{"candidate": "정당명", "percentage": 숫자}} ]
         }}
         기사: {text[:2000]}
         """
    elif poll_type == "edu":
         user_prompt = f"""
         다음 기사에서 2026 지방선거 {prompt_context} 교육감 여론조사 수치를 추출해줘.
         없으면 null. 양식:
         {{
           "pollster": "조사기관명",
           "poll_date": "YYYY.MM.DD",
           "results": [ {{"candidate": "후보명", "percentage": 숫자, "party": "진보/보수/중도 등 성향"}} ]
         }}
         기사: {text[:2000]}
         """
    else:
         user_prompt = f"""
         다음 기사에서 2026 지방선거 {prompt_context} 단체장(광역/기초) 여론조사 수치를 추출해줘.
         없으면 null. 양식:
         {{
           "pollster": "조사기관명",
           "poll_date": "YYYY.MM.DD",
           "results": [ {{"candidate": "후보명", "percentage": 숫자}} ]
         }}
         기사: {text[:2000]}
         """
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        
        content = response.content[0].text.strip()
        if content == "null" or content.strip() == "null":
            return None

        raw = extract_first_json(content)
        if raw:
            data = json.loads(raw)
        else:
            data = None
        return data
    except Exception as e:
        logger.error(f"[{prompt_context}] Claude API 파싱 오류: {e}")
        return None

def upsert_poll_data(region, poll_data, default_candidate_party_map=None):
    if not poll_data or "results" not in poll_data:
        return False
        
    pollster = poll_data.get("pollster", "미확인")
    poll_date = poll_data.get("poll_date", "미확인")
    results = poll_data.get("results", [])
    
    conn = get_db_connection()
    if not conn: return False
    
    is_new = False
    try:
        cur = conn.cursor()
        
        # 먼저 해당 조사가 이미 있는지 체크
        cur.execute("""
            SELECT 1 FROM election_polls 
            WHERE region = %s AND pollster = %s AND poll_date = %s LIMIT 1
        """, (region, pollster, poll_date))
        if not cur.fetchone():
            is_new = True
        
        for res in results:
            candidate = res.get("candidate")
            percentage = res.get("percentage")
            
            if not candidate or percentage is None: continue
            
            party = res.get("party") 
            if not party and default_candidate_party_map:
                party = default_candidate_party_map.get(candidate, "기타")
            elif not party:
                party = "기타"
                
            cur.execute("""
                INSERT INTO election_polls (region, candidate, party, percentage, pollster, poll_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (region, candidate, pollster, poll_date) DO NOTHING
            """, (region, candidate, party, percentage, pollster, poll_date))
            
        conn.commit()
        cur.close()
    except Exception as e:
        logger.error(f"[{region}] DB 저장 오류: {e}")
        conn.rollback()
    finally:
        conn.close()
        
    return is_new

def send_telegram_targets(message):
    targets = []
    if BOT_TOKEN_SCRAP: targets.append((BOT_TOKEN_SCRAP, CHAT_ID_SCRAP))
    if BOT_TOKEN_NR: targets.append((BOT_TOKEN_NR, CHAT_ID_NR))
        
    parts = []
    current = ""
    for line in message.split('\n'):
        if len(current) + len(line) + 1 > 4000:
            parts.append(current)
            current = line
        else:
            current += '\n' + line if current else line
    if current: parts.append(current)

    for token, chat_id in targets:
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        for part in parts:
            try:
                requests.post(url, json={
                    'chat_id': chat_id,
                    'text': part,
                }, timeout=10)
            except Exception as e:
                logger.error(f"텔레그램 발송 오류: {e}")

def format_poll_message():
    conn = get_db_connection()
    if not conn: return "여론조사 데이터를 불러올 수 없습니다."
        
    lines = []
    lines.append("📊 2026 지방선거 광역단체장 여론조사 현황 📊")
    lines.append("")
    
    try:
        cur = conn.cursor()
        for region in REGIONS:
            lines.append(f"◇{region}")
            for candidate, party in CANDIDATES[region]:
                lines.append(f"({party}) {candidate}")
                
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
            lines.append("")
        cur.close()
    except Exception as e:
        logger.error(f"메시지 포맷팅 중 오류: {e}")
        return "데이터 처리 중 오류가 발생했습니다."
    finally:
        conn.close()
    return "\n".join(lines).strip()

async def run_poll_tracker_async():
    logger.info("여론조사 트래커 (광역) 시작...")
    init_db()
    for region in REGIONS:
        links = search_naver_news(f"2026 지방선거 여론조사 {region} 광역단체장")
        for link in links:
            text = await fetch_article_text(link)
            if len(text) > 100:
                poll_data = parse_poll_data_with_claude(region, text, "wide")
                if poll_data:
                    c_map = {name: party for name, party in CANDIDATES.get(region, [])}
                    upsert_poll_data(region, poll_data, c_map)
        await asyncio.sleep(2)
        
    message = format_poll_message()
    send_telegram_targets(message)
    logger.info("여론조사 트래커 (광역) 완료.")

def run_poll_tracker():
    asyncio.run(run_poll_tracker_async())


async def check_basic_polls_async():
    logger.info("기초/교육감/정당 여론조사 확인 시작...")
    
    # 1. 기초단체장 경합지
    for region, cands in BASIC_TARGETS.items():
        links = search_naver_news(f"2026 지방선거 여론조사 {region}")
        for link in links:
            text = await fetch_article_text(link)
            if len(text) > 100:
                poll_data = parse_poll_data_with_claude(region, text, "basic")
                if poll_data:
                    c_map = {name: party for name, party in cands}
                    is_new = upsert_poll_data(region, poll_data, c_map)
                    if is_new:
                        # 즉시 발송 포맷
                        pollster = poll_data.get("pollster", "")
                        poll_date = poll_data.get("poll_date", "")
                        msg = f"📊 기초단체장 여론조사 속보\n◇{region}\n"
                        for res in sorted(poll_data.get("results", []), key=lambda x: x.get("percentage", 0), reverse=True):
                            c = res.get("candidate")
                            p = c_map.get(c, "기타")
                            pct = res.get("percentage")
                            msg += f"({p}) {c} ▶ {pct}%\n"
                        msg += f"📈 [{pollster} / {poll_date}]\n\n출처: https://t.me/gazzzza2025"
                        send_telegram_targets(msg)
        await asyncio.sleep(2)
                        
    # 2. 교육감 17개 시도
    for region in REGIONS:
        db_region = f"{region} 교육감"
        links = search_naver_news(f"2026 지방선거 여론조사 {region} 교육감")
        for link in links:
            text = await fetch_article_text(link)
            if len(text) > 100:
                poll_data = parse_poll_data_with_claude(region, text, "edu")
                if poll_data:
                    is_new = upsert_poll_data(db_region, poll_data)
                    if is_new:
                        pollster = poll_data.get("pollster", "")
                        poll_date = poll_data.get("poll_date", "")
                        msg = f"📊 교육감 여론조사 속보\n◇{region}\n"
                        for res in sorted(poll_data.get("results", []), key=lambda x: x.get("percentage", 0), reverse=True):
                            c = res.get("candidate")
                            p = res.get("party", "성향미상")
                            pct = res.get("percentage")
                            msg += f"{c} ({p}) ▶ {pct}%\n"
                        msg += f"📈 [{pollster} / {poll_date}]\n\n출처: https://t.me/gazzzza2025"
                        send_telegram_targets(msg)
        await asyncio.sleep(2)
                        
    # 3. 정당 지지율
    links = search_naver_news("정당 지지율 여론조사 2026")
    for link in links:
        text = await fetch_article_text(link)
        if len(text) > 100:
            poll_data = parse_poll_data_with_claude("전국", text, "party")
            if poll_data:
                is_new = upsert_poll_data("정당지지율", poll_data)
                if is_new:
                    pollster = poll_data.get("pollster", "")
                    poll_date = poll_data.get("poll_date", "")
                    msg = "📊 정당 지지율 업데이트\n"
                    # 민주당, 국민의힘, 조국혁신당, 개혁신당 포맷 출력
                    party_order = ["더불어민주당", "민주당", "국민의힘", "조국혁신당", "개혁신당"]
                    found_parties = {r.get("candidate"): r.get("percentage") for r in poll_data.get("results", [])}
                    
                    for p in party_order:
                        if p in found_parties:
                            # 길이에 맞춰 정렬 (단순 출력)
                            msg += f"{p[:5]:<5} ▶ {found_parties[p]}%\n"
                    msg += f"📈 [{pollster} / {poll_date}]\n\n출처: https://t.me/gazzzza2025"
                    send_telegram_targets(msg)
    
    logger.info("기초/교육감/정당 여론조사 확인 완료.")

def check_basic_polls():
    asyncio.run(check_basic_polls_async())

if __name__ == "__main__":
    run_poll_tracker()
