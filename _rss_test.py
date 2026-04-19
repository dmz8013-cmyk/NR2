"""8개 신문사 RSS URL 테스트 스크립트 (배포 X, 진단용)"""
import requests
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
}

TESTS = [
    ('국민일보',     'https://rss.kmib.co.kr/data/kmibEditRss.xml'),
    ('세계일보',     'https://rss.segye.com/rss/opinion.xml'),
    ('중앙일보',     'https://rss.joins.com/joins_news_list.xml'),
    ('이데일리',     'https://rss.edaily.co.kr/edaily_opinion.xml'),
    ('파이낸셜뉴스', 'https://www.fnnews.com/rss/fn_opinion.xml'),
    ('매일경제',     'https://www.mk.co.kr/rss/30100041/'),
    ('디지털타임스', 'https://www.dt.co.kr/rss/rss_news.xml'),
    ('머니투데이',   'https://rss.mt.co.kr/rss/010020.xml'),
]

results = []

for name, url in TESTS:
    row = {'name': name, 'url': url, 'status': None, 'size': 0,
           'items': 0, 'editorial': 0, 'sample': '', 'note': ''}
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        r.encoding = r.apparent_encoding or r.encoding
        row['status'] = r.status_code
        row['size'] = len(r.text)

        if r.status_code != 200 or row['size'] < 200:
            row['note'] = f'HTTP {r.status_code}, body={row["size"]}b'
        else:
            soup = BeautifulSoup(r.text, 'xml')
            items = soup.find_all('item') or soup.find_all('entry')
            row['items'] = len(items)

            if not items:
                row['note'] = 'XML 파싱됨 but item 0개'
            else:
                editorials = []
                first_title = ''
                for it in items[:30]:
                    t = it.find('title')
                    if not t:
                        continue
                    title = t.get_text(strip=True)
                    if not first_title:
                        first_title = title
                    if '사설' in title:
                        editorials.append(title)
                row['editorial'] = len(editorials)
                if editorials:
                    row['sample'] = editorials[0][:50]
                    row['note'] = f'✅ 사설 {len(editorials)}개 탐지'
                else:
                    row['sample'] = first_title[:50] if first_title else ''
                    row['note'] = '⚠️ 사설 키워드 없음 (일반 뉴스 피드일 수 있음)'
    except Exception as e:
        row['note'] = f'❌ {type(e).__name__}: {str(e)[:50]}'

    results.append(row)


# ── 표 출력 ─────────────────────────────────────────
print()
print(f'{"언론사":<10} {"status":<7} {"items":<6} {"사설":<5} {"비고":<45}')
print('─' * 90)
for r in results:
    print(f'{r["name"]:<12} '
          f'{str(r["status"]):<7} '
          f'{r["items"]:<6} '
          f'{r["editorial"]:<5} '
          f'{r["note"]}')
print()

print('─── 샘플 제목 ─────────────────────────────────')
for r in results:
    if r['sample']:
        print(f'  {r["name"]:<10} : {r["sample"]}')
