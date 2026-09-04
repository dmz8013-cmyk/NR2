"""누렁이 사설봇 - 매일 아침 주요 신문 사설 (언론사 RSS/HTML 직접 크롤링)

데이터 소스
- RSS 지원 언론사: 경향·동아·조선·한겨레·한국경제
- HTML 크롤링: 서울신문 (공식 사설 섹션에 [사설] 태그 직접 노출)
- 기타 언론사는 공개 RSS가 없어 네이버 사설 페이지 Playwright 보완 수집
- 폴백 규칙: 어떤 매체든 1차 수집 0건이면 네이버 보완으로 자동 전환,
  RSS/HTML 매체의 0건 폴백은 관리자 DM 한 줄 로그
- 발행은 잡별 화이트리스트에 있는 매체만 (목록 밖 매체는 수집돼도 미발행)
- 2026-09-04: 아침(PAPERS 16개, 06:00/07:00)과 석간(EVENING_PAPERS 3개,
  13:30/13:31)을 완전 분리 — 문화일보·내일신문·헤럴드경제는 석간 전용,
  아시아경제는 제외 유지. 두 목록은 교차 발행 금지(화이트리스트 게이트가 차단).
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


def _run_async(coro):
    """asyncio.run 대체: event loop를 명시적으로 생성/종료해 자원 누수를 방지.

    asyncio.run()은 내부에서 shutdown_default_executor()가 새 스레드를 시작하는데,
    워커 프로세스가 스레드 포화 상태면 여기서 RuntimeError('can't start new thread')가 발생한다.
    명시적으로 loop를 관리하면 누수 원인이 되는 executor/asyncgen 정리 단계를 통제할 수 있다.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        loop.close()

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

# 석간 전용 목록 (13:30/13:31 잡) — 아침 PAPERS와 완전 분리, 교차 발행 금지.
# 문화일보·헤럴드경제는 자체 수집 경로가 없어 네이버 보완, 내일신문은 전용 파서.
# 아시아경제는 제외 유지 (2026-09-04 결정).
EVENING_PAPERS = {
    '석간지': [
        {'name': '문화일보', 'kind': 'none'},
        {'name': '내일신문', 'kind': 'direct'},
        {'name': '헤럴드경제', 'kind': 'none'},
    ],
}

# 잡별 발행 화이트리스트 — 목록 밖 매체는 수집돼도 발행하지 않음 (format_message 최종 게이트).
# 아침 16개 / 석간 3개, 서로 교차 발행 금지.
ALLOWED_PAPERS = {p['name'] for _cat in PAPERS.values() for p in _cat}
EVENING_ALLOWED = {p['name'] for _cat in EVENING_PAPERS.values() for p in _cat}





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
    if r.status_code == 403:
        # 한국경제 WAF가 브라우저형 풀 UA를 403 차단(짧은 UA는 통과) — 최소 UA로 1회 재시도
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
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
    from playwright.async_api import async_playwright
    from datetime import datetime, timedelta
    
    today = datetime.now()
    dates = [
        today.strftime("%Y%m%d"),
        (today - timedelta(days=1)).strftime("%Y%m%d")
    ]
    
    results = {paper: [] for paper in target_papers}
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                for date_str in dates:
                    url = f"https://news.naver.com/opinion/editorial?date={date_str}"
                    page = await browser.new_page(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
                    )
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    for _ in range(15):
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await page.wait_for_timeout(800)
                    html = await page.content()
                    await page.close()

                    soup = BeautifulSoup(html, "html.parser")
                    for item in soup.find_all(class_='opinion_editorial_item'):
                        press_tag = item.find(class_='press_name')
                        if not press_tag:
                            continue
                        press_name = press_tag.get_text(strip=True)

                        if press_name in target_papers:
                            desc_tag = item.find(class_='description')
                            if desc_tag:
                                title = _clean_title(desc_tag.get_text(strip=True))
                                if title and len(results[press_name]) < 3:
                                    if title not in results[press_name]:
                                        results[press_name].append(title)
            finally:
                await browser.close()
    except Exception as e:
        logger.error(f"Playwright 에러: {e}")
        
    return results


NAEIL_TAG = '[내일시론]'  # 내일신문은 사설 대신 '내일시론' 섹션을 사설격으로 운영


def fetch_naeil_direct(limit=3):
    """내일신문 /opinion/editorial 페이지에서 [내일시론] prefix 제목 추출."""
    url = 'https://www.naeil.com/opinion/editorial'
    try:
        r = requests.get(url, headers=REQ_HEADERS, timeout=8)
        r.encoding = r.apparent_encoding or r.encoding
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, 'html.parser')
    except Exception as e:
        logger.warning(f'내일신문 크롤링 실패: {e}')
        return []

    seen = set()
    titles = []
    for a in soup.find_all('a', href=True):
        if '/news/read/' not in a['href']:
            continue
        text = a.get_text(strip=True)
        if not text.startswith(NAEIL_TAG):
            continue
        clean = unescape(text[len(NAEIL_TAG):]).strip()
        clean = re.sub(r'<[^>]+>', '', clean)
        if clean and len(clean) > 5 and clean not in seen:
            seen.add(clean)
            titles.append(clean)
            if len(titles) >= limit:
                break
    return titles


def fetch_titles(paper):
    """언론사 정의를 보고 적절한 fetcher 호출"""
    kind = paper.get('kind')
    if kind == 'rss':
        return fetch_rss(paper['url'])
    if kind == 'html':
        return fetch_html(paper['url'])
    if kind == 'direct' and paper.get('name') == '내일신문':
        return fetch_naeil_direct()
    return None  # 미지원


def format_message(editorials, header=None, allowed=None):
    """allowed = 이 잡의 발행 화이트리스트 (기본: 아침 16개).

    교차 발행 금지: 석간 3사가 아침 메시지에, 아침 매체가 석간 메시지에
    섞이면 여기서 차단 + 경고 로그.
    """
    if allowed is None:
        allowed = ALLOWED_PAPERS
    today = datetime.now().strftime('%Y.%m.%d')
    lines = []

    if header is None:
        header = f'🗞️주요 신문 사설({today})🗞️'
    lines.append(header)
    lines.append('')
    lines.append('출처 : https://buly.kr/7mBN720')
    lines.append('')

    first_category = True
    for category, rows in editorials.items():
        if not first_category:
            lines.append('')
        lines.append(f'<b>{category}</b>')
        first_category = False

        first_paper = True
        for name, titles, note in rows:
            if name not in allowed:
                # 화이트리스트 최종 게이트 — 목록 밖/교차 매체는 수집돼도 발행 금지
                logger.warning(f'화이트리스트 밖 매체 발행 차단(교차 발행 금지): {name}')
                continue
            if not titles:
                continue
            if not first_paper:
                lines.append('')
            first_paper = False
            lines.append(f'◇{name}')
            for t in titles:
                lines.append(f'-{t}')
    
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━━')
    lines.append('')
    lines.append('출처: https://t.me/gazzzza2025')
    lines.append('(실시간 텔레그램 정보방)')
    lines.append('')
    lines.append('━━━━━━━━━━━━━━━━')
    
    return '\n'.join(lines)


def _notify_admin(text):
    """관리자 DM 한 줄 로그 (SOB Scrap 봇 → 관리자 챗). 실패해도 파이프라인 계속."""
    if not BOT_TOKEN:
        print(f'[관리자DM 생략] {text}')
        return
    try:
        requests.post(f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
                      json={'chat_id': CHAT_ID, 'text': text}, timeout=10)
    except Exception as e:
        logger.warning(f'관리자 DM 실패(무시): {e}')


def _collect_editorials(papers_def=None):
    """papers_def(기본: 아침 PAPERS, 석간은 EVENING_PAPERS) 수집 + 폴백.
    반환: (editorials dict, total).

    폴백 규칙(아침·석간 동일): 매체 불문 1차 수집 0건이면 네이버 사설 페이지
    보완 수집으로 전환. 수집 경로가 있는 매체(rss/html/direct)가 0건으로
    폴백되면 관리자 DM에 '매체명 RSS 0건 → 보완' 로그.
    """
    if papers_def is None:
        papers_def = PAPERS
    editorials, total = {}, 0
    papers_to_fallback, rss_zero = [], []

    for category, papers in papers_def.items():
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
                if not titles:
                    titles = []
                    note = 'RSS/HTML 결과 0건' if p['kind'] in ('rss', 'html', 'direct') else '수집 미지원'

            rows.append((name, titles, note))
            total += len(titles)
            if not titles:
                papers_to_fallback.append((category, name, p))
                if p['kind'] in ('rss', 'html', 'direct'):
                    rss_zero.append(name)

            print(f'  {name} (v1): {len(titles)}개' + (f' | {note}' if note else ''))
            for t in titles:
                print(f'    - {t}')
        editorials[category] = rows

    if rss_zero:
        _notify_admin('⚠️ 사설봇 폴백: ' + ' · '.join(f'{n} RSS 0건 → 보완' for n in rss_zero))

    if papers_to_fallback:
        target_names = [n for _, n, _ in papers_to_fallback]
        print(f'\n[Playwright] 네이버 사설 페이지 보완 수집 시작: {target_names}')
        fallback_res = _run_async(fetch_naver_editorials(target_names))
        for category, name, p in papers_to_fallback:
            added = fallback_res.get(name, [])
            rows = editorials[category]
            for idx, r in enumerate(rows):
                if r[0] == name:
                    if added:
                        rows[idx] = (name, added, None)
                        total += len(added)
                        print(f'  [Playwright] {name}: {len(added)}개 보완')
                        for t in added:
                            print(f'    - {t}')
                    else:
                        rows[idx] = (name, [], '네이버 크롤링 실패')
                    break

    return editorials, total


def _send_split(message, token, chat_id, label):
    """4,096자 제한 대응 분할 전송. 토큰 없으면 생략(드라이런 안전)."""
    if not token:
        print(f'[{label}] 토큰 없음 — 전송 생략')
        return
    if len(message) > 4000:
        parts, current = [], ''
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

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    for part in parts:
        try:
            resp = requests.post(url, json={
                'chat_id': chat_id,
                'text': part,
                'parse_mode': 'HTML',
                'disable_web_page_preview': True,
            }, timeout=10)
            if resp.status_code == 200:
                print(f'[{label}] 전송 완료 ({len(part)}자)')
            else:
                print(f'[{label}] 전송 실패: {resp.text[:200]}')
        except Exception as e:
            logger.error(f'[{label}] 전송 오류: {e}')


def send_editorial():
    """아침 사설 — SOB Scrap 채널 (06:00)."""
    logger.info('=== 사설봇 시작 ===')
    print('사설봇 시작...')
    editorials, total = _collect_editorials()
    print(f'\n총 수집: {total}건')
    _send_split(format_message(editorials), BOT_TOKEN, CHAT_ID, 'SOB Scrap')
    logger.info('=== 사설봇 완료 ===')
    print('사설봇 완료 ✅')


def send_editorial_nureongi():
    """아침 사설 — 누렁이 정보방 (07:00)."""
    NUREONGI_TOKEN = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
    NUREONGI_CHAT = '@gazzzza2025'
    if not NUREONGI_TOKEN:
        print('NUREONGI_NEWS_BOT_TOKEN 없음')
        return
    editorials, total = _collect_editorials()
    print(f'\n총 수집: {total}건')
    _send_split(format_message(editorials), NUREONGI_TOKEN, NUREONGI_CHAT, '누렁이 정보방')


def _evening_header():
    return f'📰 석간 사설 | {datetime.now().strftime("%m/%d")} 13:30'


def _evening_sent_today(key):
    """당일 발송 여부 (g2b_state KV) — 수동 발송 후 13:30 자동분 중복 차단.
    DB 불가 시 False(발송 우선)."""
    try:
        from g2b_tracker import state_get
        return state_get(key) == datetime.now().strftime('%Y-%m-%d')
    except Exception:
        return False


def _mark_evening_sent(key):
    try:
        from g2b_tracker import state_set
        state_set(key, datetime.now().strftime('%Y-%m-%d'))
    except Exception as e:
        logger.warning(f'[석간] 발송 기록 실패(무시): {e}')


def send_editorial_afternoon():
    """석간 사설 — SOB Scrap 채널 (13:30). 문화일보·내일신문·헤럴드경제만."""
    logger.info('=== 석간 사설봇 시작 (SOB Scrap) ===')
    print('석간 사설봇 시작 (SOB Scrap)...')
    if _evening_sent_today('evening_editorial_sent_sob'):
        logger.warning('[석간] 오늘 이미 발송됨(수동 실행 등) — 중복 발송 방지 스킵')
        print('[SKIP] 오늘 이미 발송됨 — 중복 방지')
        return
    editorials, total = _collect_editorials(EVENING_PAPERS)
    print(f'\n총 수집: {total}건')
    if total == 0:
        logger.warning('[석간] 수집 0건 — 발송 생략')
        _notify_admin('⚠️ 석간 사설 수집 0건 — 발송 생략')
        return
    _send_split(format_message(editorials, header=_evening_header(), allowed=EVENING_ALLOWED),
                BOT_TOKEN, CHAT_ID, 'SOB Scrap 석간')
    _mark_evening_sent('evening_editorial_sent_sob')
    logger.info('=== 석간 사설봇 완료 (SOB Scrap) ===')


def send_editorial_afternoon_nureongi():
    """석간 사설 — 누렁이 정보방 (13:31). 문화일보·내일신문·헤럴드경제만."""
    logger.info('=== 석간 사설봇 시작 (누렁이) ===')
    NUREONGI_TOKEN = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
    NUREONGI_CHAT = '@gazzzza2025'
    if not NUREONGI_TOKEN:
        print('NUREONGI_NEWS_BOT_TOKEN 없음')
        return
    if _evening_sent_today('evening_editorial_sent_nureongi'):
        logger.warning('[석간·누렁이] 오늘 이미 발송됨 — 중복 발송 방지 스킵')
        print('[SKIP] 오늘 이미 발송됨 — 중복 방지')
        return
    editorials, total = _collect_editorials(EVENING_PAPERS)
    print(f'\n총 수집: {total}건')
    if total == 0:
        logger.warning('[석간·누렁이] 수집 0건 — 발송 생략')
        return
    _send_split(format_message(editorials, header=_evening_header(), allowed=EVENING_ALLOWED),
                NUREONGI_TOKEN, NUREONGI_CHAT, '누렁이 정보방 석간')
    _mark_evening_sent('evening_editorial_sent_nureongi')
    logger.info('=== 석간 사설봇 완료 (누렁이) ===')


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)
    mode = sys.argv[1] if len(sys.argv) > 1 else 'morning'
    if mode == 'afternoon':
        send_editorial_afternoon()
    elif mode == 'afternoon_nureongi':
        send_editorial_afternoon_nureongi()
    else:
        send_editorial()
