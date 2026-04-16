"""누렁이 사설봇 - 매일 아침 주요 신문 사설 (언론사 RSS/HTML 직접 크롤링)

데이터 소스
- RSS 지원 언론사: 경향·동아·조선·한겨레·한국경제
- HTML 크롤링: 서울신문 (공식 사설 섹션에 [사설] 태그 직접 노출)
- 기타 언론사는 공개 RSS가 없어 현재 수집 미지원
"""
import os
import re
import requests
import logging
import urllib.parse
from datetime import datetime
from html import unescape
from bs4 import BeautifulSoup
import asyncio

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('SCRAP_BOT_TOKEN')
CHAT_ID = os.environ.get('SCRAP_CHAT_ID', '5132309076')

REQ_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
}

# 수집 방식별 언론사 정의
# 'rss'  — 공식 RSS 피드에서 [사설] 태그 제목 추출
# 'html' — 공식 사설 섹션 HTML에서 [사설] 태그 제목 추출
# 'none' — 공개 수집 경로를 찾지 못함 (추후 보완 필요)
PAPERS = {
    '종합지': [
        {'name': '경향신문', 'kind': 'rss', 'url': 'https://www.khan.co.kr/rss/rssdata/opinion_news.xml'},
        {'name': '국민일보', 'kind': 'none'},
        {'name': '동아일보', 'kind': 'rss', 'url': 'https://rss.donga.com/editorials.xml'},
        {'name': '서울신문', 'kind': 'html',
         'url': 'https://www.seoul.co.kr/news/newsList.php?section=editorial'},
        {'name': '세계일보', 'kind': 'none'},
        {'name': '조선일보', 'kind': 'rss',
         'url': 'https://www.chosun.com/arc/outboundfeeds/rss/category/opinion/?outputType=xml'},
        {'name': '중앙일보', 'kind': 'none'},
        {'name': '한겨레', 'kind': 'rss', 'url': 'https://www.hani.co.kr/rss/opinion/'},
        {'name': '한국일보', 'kind': 'none'},
    ],
    '경제지': [
        {'name': '디지털타임스', 'kind': 'none'},
        {'name': '매일경제', 'kind': 'none'},
        {'name': '머니투데이', 'kind': 'none'},
        {'name': '서울경제', 'kind': 'none'},
        {'name': '이데일리', 'kind': 'none'},
        {'name': '파이낸셜뉴스', 'kind': 'none'},
        {'name': '한국경제', 'kind': 'rss', 'url': 'https://www.hankyung.com/feed/opinion'},
    ],
}


def escape_md(text):
    """텔레그램 MarkdownV2 특수문자 escape"""
    special = r'\_*[]()~`>#+-=|{}.!'
    for ch in special:
        text = text.replace(ch, f'\\{ch}')
    return text


# ---- 제목 정리 공통 유틸 ----
EDITORIAL_TAG_PATTERNS = ('[사설]', '사설]', '【사설】', '<사설>')


def _clean_title(raw):
    """HTML 엔티티 제거 + 사설 태그 정리"""
    title = unescape(raw or '')
    title = re.sub(r'<[^>]+>', '', title)  # 남아있는 HTML 태그 제거
    # 사설 태그 패턴 제거
    for p in EDITORIAL_TAG_PATTERNS:
        title = title.replace(p, '')
    return title.strip()


def _is_editorial(title):
    """제목이 사설 포맷인지 판정"""
    return (
        '[사설]' in title
        or '사설]' in title
        or '【사설】' in title
    )


# ---- 소스별 fetcher ----
def fetch_rss(url, limit=3):
    """RSS 피드에서 [사설] 태그 제목 추출"""
    r = requests.get(url, headers=REQ_HEADERS, timeout=10)
    r.encoding = r.apparent_encoding or r.encoding
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code}')
    soup = BeautifulSoup(r.text, 'xml')
    items = soup.find_all('item') or soup.find_all('entry')
    titles = []
    for it in items:
        t = it.find('title')
        if not t:
            continue
        raw = t.get_text(strip=True)
        if _is_editorial(raw):
            clean = _clean_title(raw)
            if clean and len(clean) > 5:
                titles.append(clean)
    return titles[:limit]


def fetch_html(url, limit=3):
    """HTML 인덱스 페이지에서 [사설] 앵커 제목 추출"""
    r = requests.get(url, headers=REQ_HEADERS, timeout=10)
    r.encoding = r.apparent_encoding or r.encoding
    if r.status_code != 200:
        raise RuntimeError(f'HTTP {r.status_code}')
    soup = BeautifulSoup(r.text, 'lxml')
    seen = set()
    titles = []
    for a in soup.find_all('a'):
        text = a.get_text(strip=True)
        if not text or not _is_editorial(text):
            continue
        clean = _clean_title(text)
        if clean and len(clean) > 5 and clean not in seen:
            seen.add(clean)
            titles.append(clean)
            if len(titles) >= limit:
                break
    return titles


async def fetch_naver_editorials(target_papers):
    """Playwright 기반 네이버 사설 페이지 크롤링 보완 (최대 3개)"""
    from playwright.async_api import async_playwright
    
    today = datetime.now().strftime("%Y%m%d")
    url = f"https://news.naver.com/opinion/editorial?date={today}"
    results = {paper: [] for paper in target_papers}
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            await page.goto(url, wait_until="networkidle", timeout=30000)
            html = await page.content()
            await browser.close()
    except Exception as e:
        logger.error(f"Playwright 에러: {e}")
        return results

    soup = BeautifulSoup(html, "html.parser")
    for item in soup.find_all(class_='opinion_editorial_item'):
        press_tag = item.find(class_='press_name')
        if not press_tag:
            continue
        press_name = press_tag.get_text(strip=True)
        
        if press_name in target_papers:
            desc_tag = item.find(class_='description')
            if desc_tag:
                title = desc_tag.get_text(strip=True)
                title = _clean_title(title)
                if title and len(results[press_name]) < 3:
                    if title not in results[press_name]:
                        results[press_name].append(title)
                        
    return results


def fetch_titles(paper):
    """언론사 정의를 보고 적절한 fetcher 호출"""
    kind = paper.get('kind')
    if kind == 'rss':
        return fetch_rss(paper['url'])
    if kind == 'html':
        return fetch_html(paper['url'])
    return None  # 미지원


def format_message(editorials):
    """텔레그램 메시지 포맷 (MarkdownV2)"""
    today = datetime.now().strftime('%Y.%m.%d')
    lines = [f'🗞️주요 신문 사설\\({escape_md(today)}\\)🗞️\n']

    for category, rows in editorials.items():
        lines.append(f'\n*{escape_md(category)}*')
        for name, titles, note in rows:
            lines.append(f'◇{escape_md(name)}')
            if titles:
                for t in titles:
                    lines.append(f'\\-{escape_md(t)}')
            else:
                lines.append(f'\\-{escape_md(note or "사설을 찾지 못했습니다")}')

    lines.append(f'\n출처: {escape_md("https://t.me/gazzzza2025")}')
    lines.append(escape_md('(실시간 텔레그램 정보방)'))
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━━')
    lines.append('📖 오늘 브리핑 전문 \\+ 심층 토론')
    lines.append(f'👉 {escape_md("https://nr2.kr")}')
    lines.append('━━━━━━━━━━━━━━━━')
    return '\n'.join(lines)


def send_editorial():
    logger.info('=== 사설봇 시작 ===')
    print('사설봇 시작...')

    editorials = {}
    total = 0
    papers_to_fallback = []
    
    # RSS 성공하는 언론사 목록 (이들은 Playwright 보완에서 제외)
    rss_success_papers = ['경향신문', '동아일보', '서울신문', '조선일보', '한겨레', '한국경제']

    for category, papers in PAPERS.items():
        rows = []
        for p in papers:
            name = p['name']
            try:
                titles = fetch_titles(p)
            except Exception as e:
                logger.error(f'{name} 수집 실패: {e}')
                titles, note = [], f'수집 실패 ({type(e).__name__})'
            else:
                note = None
                if titles is None or len(titles) == 0:
                    if p['kind'] in ('rss', 'html'):
                        note = 'RSS/HTML 결과 0건'
                    else:
                        titles, note = [], '수집 미지원'
            
            rows.append((name, titles, note))
            total += len(titles or [])
            
            # 수집된 기사가 없고, 제외 대상이 아닌 10개 언론사면 fallback 대상에 추가
            if not titles and name not in rss_success_papers:
                papers_to_fallback.append((category, name, p))
                
            print(f'  {name} (v1): {len(titles or [])}개' + (f' | {note}' if note else ''))
            for t in (titles or []):
                print(f'    - {t}')
                
        editorials[category] = rows

    # Playwright 보완 수집 실행
    if papers_to_fallback:
        target_names = [name for _, name, _ in papers_to_fallback]
        print(f"\n[Playwright] 네이버 사설 페이지 보완 수집 시작: {target_names}")
        fallback_res = asyncio.run(fetch_naver_editorials(target_names))
        
        for category, name, p in papers_to_fallback:
            added_titles = fallback_res.get(name, [])
            rows = editorials[category]
            for idx, r in enumerate(rows):
                if r[0] == name:
                    if added_titles:
                        rows[idx] = (name, added_titles, None)
                        total += len(added_titles)
                        print(f"  [Playwright] {name}: {len(added_titles)}개 보완 완료")
                        for t in added_titles:
                            print(f'    - {t}')
                    else:
                        rows[idx] = (name, [], '네이버 크롤링 실패')
                    break
                    
    print(f'\n총 수집: {total}건')

    message = format_message(editorials)

    # 4096자 초과 시 분할
    if len(message) > 4000:
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
    else:
        parts = [message]

    if not BOT_TOKEN:
        print('SCRAP_BOT_TOKEN 없음 — 전송 생략')
        return

    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    for part in parts:
        try:
            resp = requests.post(url, json={
                'chat_id': CHAT_ID,
                'text': part,
                'parse_mode': 'MarkdownV2',
                'disable_web_page_preview': True,
            }, timeout=10)
            if resp.status_code == 200:
                print(f'전송 완료 ({len(part)}자)')
            else:
                print(f'전송 실패: {resp.text}')
        except Exception as e:
            logger.error(f'전송 오류: {e}')
            print(f'오류: {e}')

    logger.info('=== 사설봇 완료 ===')
    print('사설봇 완료 ✅')


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    send_editorial()
