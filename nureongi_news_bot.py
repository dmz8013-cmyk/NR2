"""누렁이 뉴스봇 v2 - 언론사 표시 + 속보/단독 강화 + DB 저장"""
import os
import asyncio
import requests
import json
from bs4 import BeautifulSoup
from telegram import Bot

BOT_TOKEN = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
CHAT_ID = "@gazzzza2025"
SENT_FILE = '/tmp/sent_news.json'

# --- DB 저장용 ---
BIAS_DATA = None

def _load_bias_data():
    global BIAS_DATA
    if BIAS_DATA is not None:
        return BIAS_DATA
    data_path = os.path.join(os.path.dirname(__file__), 'app', 'data', 'korean_media_bias.json')
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            BIAS_DATA = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        BIAS_DATA = {'media': []}
    return BIAS_DATA

def get_media_bias(source_name):
    """언론사 이름으로 편향 점수 조회"""
    result = {'political': None, 'geopolitical': None, 'economic': None}
    if not source_name:
        return result
    data = _load_bias_data()
    name = source_name.strip()
    for m in data.get('media', []):
        if name in (m.get('name'), m.get('short'), m.get('id')):
            return {
                'political': m.get('political'),
                'geopolitical': m.get('geopolitical'),
                'economic': m.get('economic'),
            }
    return result

def _get_db_conn():
    """PostgreSQL 연결"""
    try:
        import psycopg2
        db_url = os.environ.get('DATABASE_URL') or os.environ.get('DATABASE_PRIVATE_URL', '')
        if not db_url:
            return None
        if db_url.startswith('postgres://'):
            db_url = db_url.replace('postgres://', 'postgresql://', 1)
        return psycopg2.connect(db_url)
    except Exception as e:
        print(f"[DB] 연결 실패: {e}")
        return None

def save_article_to_db(art):
    """기사를 news_articles 테이블에 저장"""
    conn = _get_db_conn()
    if not conn:
        return
    try:
        bias = get_media_bias(art['press'])
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO news_articles (title, url, source, source_political, source_geopolitical, source_economic, submitted_by, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, 1, NOW())
               ON CONFLICT (url) DO NOTHING""",
            (art['title'], art['link'], art['press'],
             bias['political'], bias['geopolitical'], bias['economic'])
        )
        conn.commit()
        if cur.rowcount > 0:
            print(f"  📥 DB 저장: {art['title'][:30]}")
        cur.close()
    except Exception as e:
        print(f"  ❌ DB 저장 실패: {e}")
        conn.rollback()
    finally:
        conn.close()

def load_sent_news():
    try:
        with open(SENT_FILE, 'r') as f:
            return set(json.load(f))
    except:
        return set()

def save_sent_news(sent):
    try:
        with open(SENT_FILE, 'w') as f:
            json.dump(list(sent)[-500:], f)
    except:
        pass

KEYWORDS = [
    "삼성", "SK", "LG", "현대", "AI", "챗GPT", "테슬라", "엔비디아",
    "환율", "금리", "HBM", "반도체", "머스크", "애플", "코스피",
    "팔란티어", "안두릴", "UAM", "AAM", "드론", "클로드", "젠슨황",
    "피터틸", "아모데이",
    "손흥민", "오타니",
    "이재명", "장동혁", "한동훈", "민주당", "국민의힘",
    "정청래", "조국", "김어준", "윤석열", "김건희",
    "이준석", "선거", "지방선거",
    "트럼프", "푸틴", "시진핑", "다카이치", "네타냐후", "에르도안",
]

SPECIAL_TAGS = ['[단독]', '[속보]', '[여론조사]', '[기획]', '[인터뷰]', '(단독)', '[긴급]', '[breaking]']

# 섹션 + 속보 페이지
SOURCES = [
    ("정치", "https://news.naver.com/section/100"),
    ("경제", "https://news.naver.com/section/101"),
    ("세계", "https://news.naver.com/section/104"),
    ("IT/과학", "https://news.naver.com/section/105"),
]

# 속보 전용 페이지 (최신순 정렬)
BREAKING_SOURCES = [
    ("정치", "https://news.naver.com/breakingnews/section/100"),
    ("경제", "https://news.naver.com/breakingnews/section/101"),
    ("세계", "https://news.naver.com/breakingnews/section/104"),
    ("IT/과학", "https://news.naver.com/breakingnews/section/105"),
]

# 속보 전문 언론사 (이 언론사의 [속보][단독]은 우선 전송)
WIRE_SERVICES = ['연합뉴스', '뉴시스', '뉴스1']

SECTION_EMOJI = {
    "경제": "💰", "정치": "🏛️", "IT/과학": "💻", "세계": "🌍"
}


def parse_articles(url, section_name, limit=30):
    """네이버 뉴스 섹션 파싱 - 언론사 포함"""
    articles = []
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        items = soup.select('.sa_item')[:limit]
        for item in items:
            title_el = item.select_one('a.sa_text_title')
            press_el = item.select_one('.sa_text_press')
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = title_el.get('href', '')
            press = press_el.get_text(strip=True) if press_el else '미상'
            if not link.startswith('http'):
                continue
            articles.append({
                'title': title,
                'link': link,
                'press': press,
                'section': section_name,
            })
    except Exception as e:
        print(f"크롤링 오류 [{section_name}]: {e}")
    return articles


def get_news():
    """키워드/태그 매칭 기사 수집"""
    all_articles = []
    seen_links = set()

    # 1) 속보 페이지 먼저 (최신순)
    for section_name, url in BREAKING_SOURCES:
        for art in parse_articles(url, section_name, limit=60):
            if art['link'] not in seen_links:
                seen_links.add(art['link'])
                all_articles.append(art)

    # 2) 일반 섹션
    for section_name, url in SOURCES:
        for art in parse_articles(url, section_name, limit=30):
            if art['link'] not in seen_links:
                seen_links.add(art['link'])
                all_articles.append(art)

    # 3) 필터: 키워드 또는 특수태그 매칭
    matched = []
    for art in all_articles:
        title = art['title']
        has_tag = any(tag.lower() in title.lower() for tag in SPECIAL_TAGS)
        has_keyword = any(kw in title for kw in KEYWORDS)
        is_wire_breaking = (art['press'] in WIRE_SERVICES and has_tag)

        if has_tag or has_keyword or is_wire_breaking:
            art['is_breaking'] = has_tag
            art['is_wire'] = art['press'] in WIRE_SERVICES
            matched.append(art)

    # 속보/단독 우선 정렬
    matched.sort(key=lambda x: (x['is_breaking'] and x['is_wire'], x['is_breaking']), reverse=True)
    return matched


def format_message(art):
    """새 포맷: 언론사 + 제목 + URL"""
    emoji = SECTION_EMOJI.get(art['section'], '📰')

    # 속보/단독 강조
    prefix = ""
    if any(tag in art['title'] for tag in ['[속보]', '[긴급]']):
        prefix = "🚨 "
    elif any(tag in art['title'] for tag in ['[단독]', '(단독)']):
        prefix = "⚡ "

    return (
        f"{prefix}{emoji} <b>[{art['section']}]</b>\n"
        f"🏷️ 언론사: {art['press']}\n"
        f"📝 제목: {art['title']}\n"
        f"🔗 {art['link']}"
    )


async def send_news():
    if not BOT_TOKEN:
        print("NUREONGI_NEWS_BOT_TOKEN 환경변수 없음")
        return
    sent_news = load_sent_news()
    first_run = len(sent_news) == 0
    bot = Bot(BOT_TOKEN)
    articles = get_news()
    sent_titles = set()
    new_count = 0
    for art in articles:
        if art['link'] in sent_news:
            continue
        if any(t in art['title'] for t in sent_titles):
            continue
        if first_run:
            sent_news.add(art['link'])
            continue
        sent_news.add(art['link'])
        sent_titles.add(art['title'])
        if new_count >= 15:
            break
        message = format_message(art)
        try:
            await bot.send_message(
                CHAT_ID, message,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            tag = "🚨속보" if art['is_breaking'] else "📰"
            print(f"✅ {tag} [{art['press']}] {art['title'][:30]}")
            save_article_to_db(art)
            new_count += 1
            await asyncio.sleep(2)
        except Exception as e:
            print(f"❌ 전송 실패: {e}")
    save_sent_news(sent_news)
    print(f"[뉴스봇v2] 완료 — {new_count}개 전송")

    # 랭킹 기사 수집 (네이버 + 다음 교집합 우선, 나머지도 저장)
    try:
        naver_ranking = fetch_naver_ranking()
        daum_ranking = fetch_daum_ranking()
        cross = cross_platform_ranking(naver_ranking, daum_ranking)

        # 교집합 기사 우선 저장
        for art in cross:
            save_ranking_to_db(art)

        # 나머지 네이버 랭킹도 저장
        cross_links = {a['link'] for a in cross}
        for art in naver_ranking:
            if art['link'] not in cross_links:
                save_ranking_to_db(art)

        print(f"[랭킹] 완료 — 네이버 {len(naver_ranking)}건, 다음 {len(daum_ranking)}건, 교집합 {len(cross)}건")
    except Exception as e:
        print(f"[랭킹] 수집 오류: {e}")


# --- 네이버 랭킹 수집 ---

RANKING_SECTIONS = {
    '정치': 100,
    '경제': 101,
    '사회': 102,
    '국제': 104,
}


def fetch_naver_ranking():
    """네이버 뉴스 분야별 많이 본 뉴스 TOP 10 수집

    Returns:
        list of dicts with keys: title, link, press, section, rank, is_ranking
    """
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    all_ranking = []

    for section_name, section_id in RANKING_SECTIONS.items():
        url = f'https://news.naver.com/main/ranking/popularDay.naver?rankingType=popular_day&sectionId={section_id}'
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')

            boxes = soup.select('.rankingnews_box')
            seen_links = set()

            for box in boxes:
                press_el = box.select_one('.rankingnews_name')
                press = press_el.get_text(strip=True) if press_el else '미상'

                items = box.select('.rankingnews_list li')
                for item in items:
                    link_el = item.select_one('a.list_title')
                    rank_el = item.select_one('.list_ranking_num')
                    if not link_el:
                        continue

                    link = link_el.get('href', '')
                    if not link.startswith('http') or link in seen_links:
                        continue
                    seen_links.add(link)

                    title = link_el.get_text(strip=True)
                    rank = int(rank_el.get_text(strip=True)) if rank_el else 0

                    if rank >= 1 and rank <= 10:
                        all_ranking.append({
                            'title': title,
                            'link': link,
                            'press': press,
                            'section': section_name,
                            'rank': rank,
                            'is_ranking': True,
                        })

            print(f"[랭킹] {section_name}: {sum(1 for a in all_ranking if a['section'] == section_name)}건")
        except Exception as e:
            print(f"[랭킹] {section_name} 수집 오류: {e}")

    return all_ranking


DAUM_SECTIONS = {
    '정치': 'https://news.daum.net/politics',
    '경제': 'https://news.daum.net/economic',
    '사회': 'https://news.daum.net/society',
    '국제': 'https://news.daum.net/foreign',
}


def fetch_daum_ranking():
    """다음 뉴스 섹션별 상위 기사 수집 (에디터 큐레이션 기반)

    Returns:
        list of dicts with keys: title, link, press, section
    """
    import re
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}
    all_articles = []

    for section_name, url in DAUM_SECTIONS.items():
        try:
            res = requests.get(url, headers=headers, timeout=10)
            res.encoding = 'utf-8'
            res.raise_for_status()
            soup = BeautifulSoup(res.text, 'html.parser')

            items = soup.select('.cont_thumb')[:10]
            for item in items:
                title_el = item.select_one('.tit_txt')
                link_el = item.select_one('a')
                info_el = item.select_one('.info_txt')

                if not title_el:
                    continue

                title = title_el.get_text(strip=True)
                href = link_el.get('href', '') if link_el else ''

                # 언론사 이름 추출 (시간 정보 제거)
                press = ''
                if info_el:
                    raw = info_el.get_text(strip=True)
                    press = re.sub(r'\d+[분시간일]+\s*전$', '', raw).strip()

                if title and href:
                    all_articles.append({
                        'title': title,
                        'link': href,
                        'press': press or '미상',
                        'section': section_name,
                    })

            print(f"[다음] {section_name}: {sum(1 for a in all_articles if a['section'] == section_name)}건")
        except Exception as e:
            print(f"[다음] {section_name} 수집 오류: {e}")

    return all_articles


def cross_platform_ranking(naver_articles, daum_articles):
    """네이버·다음 교집합 기사 계산 (제목 유사도 70% 이상)

    Returns:
        list of naver article dicts that also appear on daum
    """
    import difflib
    cross = []
    used_daum = set()

    for nav in naver_articles:
        for i, daum in enumerate(daum_articles):
            if i in used_daum:
                continue
            ratio = difflib.SequenceMatcher(None, nav['title'], daum['title']).ratio()
            if ratio >= 0.70:
                nav['is_cross_platform'] = True
                cross.append(nav)
                used_daum.add(i)
                break

    print(f"[교집합] 네이버 {len(naver_articles)}건 × 다음 {len(daum_articles)}건 → 교집합 {len(cross)}건")
    return cross


def save_ranking_to_db(art):
    """랭킹 기사를 news_articles에 저장 (무조건 저장, 키워드 필터 X)"""
    conn = _get_db_conn()
    if not conn:
        return
    try:
        bias = get_media_bias(art['press'])
        cur = conn.cursor()
        is_cross = art.get('is_cross_platform', False)
        cur.execute(
            """INSERT INTO news_articles
               (title, url, source, source_political, source_geopolitical, source_economic,
                is_ranking, ranking_section, ranking_rank, is_cross_platform, submitted_by, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, NOW())
               ON CONFLICT (url) DO UPDATE SET
                 is_ranking = EXCLUDED.is_ranking,
                 ranking_section = EXCLUDED.ranking_section,
                 ranking_rank = EXCLUDED.ranking_rank,
                 is_cross_platform = EXCLUDED.is_cross_platform""",
            (art['title'], art['link'], art['press'],
             bias['political'], bias['geopolitical'], bias['economic'],
             True, art['section'], art.get('rank'), is_cross)
        )
        conn.commit()
        if cur.rowcount > 0:
            print(f"  📥 랭킹 DB: [{art['section']}{art.get('rank', '')}위] {art['title'][:30]}")
        cur.close()
    except Exception as e:
        print(f"  ❌ 랭킹 DB 실패: {e}")
        conn.rollback()
    finally:
        conn.close()


def run_news_bot():
    asyncio.run(send_news())


def run_ranking_collector():
    """랭킹 수집만 별도 실행 (네이버 + 다음 교집합)"""
    naver = fetch_naver_ranking()
    daum = fetch_daum_ranking()
    cross = cross_platform_ranking(naver, daum)

    for art in cross:
        save_ranking_to_db(art)
    cross_links = {a['link'] for a in cross}
    for art in naver:
        if art['link'] not in cross_links:
            save_ranking_to_db(art)

    print(f"[랭킹 수집] 완료 — 네이버 {len(naver)}건, 다음 {len(daum)}건, 교집합 {len(cross)}건")