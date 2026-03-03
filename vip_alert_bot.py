"""VIP 알림봇 - 실시간 뉴스 모니터링 (네이버 API) — 중복 필터링 강화"""
import os
import re
import time
import requests
import json
import logging
import urllib.parse

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('SCHEDULE_BOT_TOKEN', '8734510853:AAHsqC3fQfC0K02-xrWEZgnh9ZDGUIi2P44')
CHAT_ID = '5132309076'
SENT_FILE = '/tmp/vip_sent.json'

TARGETS = [
    {'name': '앤트로픽/AI', 'emoji': '🤖', 'queries': ['앤트로픽', 'Anthropic', 'AI 인공지능']},
    {'name': '일론 머스크', 'emoji': '🚀', 'queries': ['일론 머스크', '머스크']},
    {'name': '도널드 트럼프', 'emoji': '🇺🇸', 'queries': ['트럼프', '도널드 트럼프']},
    {'name': '섹스', 'emoji': '🔞', 'queries': ['섹스', '성관계 뉴스']},
    {'name': '공모사업', 'emoji': '📋', 'queries': ['공모사업', '정부지원사업 공모']},
]

# 제목 정규화용: 특수문자/태그 제거
_STRIP_RE = re.compile(r'[^\w가-힣a-zA-Z0-9]')


def _normalize(title):
    """제목 정규화 — 유사도 비교용"""
    return _STRIP_RE.sub('', title).lower()


def _is_similar(title, existing_titles, threshold=0.55):
    """새 제목이 기존 제목과 유사한지 판별"""
    norm = _normalize(title)
    if len(norm) < 4:
        return False
    for ex in existing_titles:
        ex_norm = _normalize(ex)
        if len(ex_norm) < 4:
            continue
        # 1) 한쪽이 다른쪽을 포함
        if norm in ex_norm or ex_norm in norm:
            return True
        # 2) 글자 집합 Jaccard 유사도
        s1, s2 = set(norm), set(ex_norm)
        jaccard = len(s1 & s2) / len(s1 | s2) if s1 | s2 else 0
        if jaccard >= threshold:
            # 추가 검증: 앞 8글자 겹침
            min_len = min(len(norm), len(ex_norm))
            prefix = min(8, min_len)
            if norm[:prefix] == ex_norm[:prefix]:
                return True
            # 공통 부분문자열 비율
            common = _lcs_len(norm, ex_norm)
            if common >= min_len * 0.5:
                return True
    return False


def _lcs_len(s1, s2):
    """최장 공통 부분문자열 길이 (DP)"""
    if not s1 or not s2:
        return 0
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    m, n = len(s1), len(s2)
    prev = [0] * (m + 1)
    best = 0
    for j in range(1, n + 1):
        curr = [0] * (m + 1)
        for i in range(1, m + 1):
            if s1[i-1] == s2[j-1]:
                curr[i] = prev[i-1] + 1
                best = max(best, curr[i])
        prev = curr
    return best


def load_sent():
    """전송 이력 로드 (링크 + 제목)"""
    try:
        with open(SENT_FILE, 'r') as f:
            data = json.load(f)
            if isinstance(data, dict):
                return set(data.get('links', [])), list(data.get('titles', []))
            return set(data), []
    except:
        return set(), []


def save_sent(sent_links, sent_titles):
    """전송 이력 저장"""
    try:
        with open(SENT_FILE, 'w') as f:
            json.dump({
                'links': list(sent_links)[-500:],
                'titles': sent_titles[-200:]
            }, f, ensure_ascii=False)
    except:
        pass


def fetch_naver_news(query, limit=10):
    """네이버 뉴스 검색 API"""
    articles = []
    naver_id = os.environ.get('NAVER_CLIENT_ID', '')
    naver_secret = os.environ.get('NAVER_CLIENT_SECRET', '')
    if not naver_id:
        return articles
    try:
        params = urllib.parse.urlencode({'query': query, 'display': limit, 'sort': 'date'})
        url = f'https://openapi.naver.com/v1/search/news.json?{params}'
        r = requests.get(url, headers={
            'X-Naver-Client-Id': naver_id,
            'X-Naver-Client-Secret': naver_secret,
        }, timeout=10)
        data = r.json()
        for item in data.get('items', []):
            title = item.get('title', '')
            title = title.replace('<b>', '').replace('</b>', '')
            title = title.replace('&quot;', '"').replace('&amp;', '&')
            title = title.replace('&lt;', '<').replace('&gt;', '>')
            link = item.get('originallink', item.get('link', ''))
            articles.append({
                'title': title,
                'link': link,
            })
    except Exception as e:
        logger.error(f"네이버 검색 실패 [{query}]: {e}")
    return articles


def check_and_send():
    """새 뉴스 확인 후 전송 — 중복 필터링 강화"""
    sent_links, sent_titles = load_sent()
    first_run = len(sent_links) == 0
    new_count = 0

    # 이번 사이클에서 전송한 제목 (타겟 간 중복 방지)
    cycle_titles = list(sent_titles)

    for target in TARGETS:
        all_articles = []
        seen_in_target = set()

        for query in target['queries']:
            articles = fetch_naver_news(query, limit=10)
            for art in articles:
                # 같은 타겟 내 제목 중복 제거
                if art['title'] not in seen_in_target:
                    seen_in_target.add(art['title'])
                    all_articles.append(art)

        target_count = 0
        for art in all_articles:
            # 1) 링크 중복
            if art['link'] in sent_links:
                continue
            # 2) 제목 유사도 중복 (과거 이력 + 이번 사이클 전체)
            if _is_similar(art['title'], cycle_titles):
                sent_links.add(art['link'])  # 링크도 기록해서 다음에 안 봄
                continue
            # 3) 타겟당 최대 2개
            if target_count >= 2:
                break

            if first_run:
                sent_links.add(art['link'])
                cycle_titles.append(art['title'])
                continue

            sent_links.add(art['link'])
            cycle_titles.append(art['title'])

            message = (
                f"{target['emoji']} <b>{target['name']} 관련 뉴스</b>\n\n"
                f"📝 {art['title']}\n"
                f"🔗 {art['link']}"
            )

            try:
                url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                resp = requests.post(url, json={
                    'chat_id': CHAT_ID,
                    'text': message,
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': True,
                }, timeout=10)
                if resp.status_code == 200:
                    print(f"✅ {target['emoji']} {art['title'][:40]}")
                    new_count += 1
                    target_count += 1
                    time.sleep(3)
                else:
                    print(f"❌ 전송 실패: {resp.text}")
            except Exception as e:
                print(f"❌ 오류: {e}")

    # 이번 사이클 제목도 이력에 저장
    save_sent(sent_links, cycle_titles)
    print(f"[VIP알림봇] 완료 — {new_count}개 전송")


def run_vip_alert():
    check_and_send()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    check_and_send()