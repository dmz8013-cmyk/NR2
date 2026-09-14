"""단독 스크랩봇 중복 제거(scrap_dedup) 테스트.

실행: python -m pytest tests/test_scrap_dedup.py -v
(rapidfuzz 필요 — requirements.txt 포함)
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytz
from scrap_dedup import normalize_title, dedup_items, filter_seen

KST = pytz.timezone('Asia/Seoul')
T0 = KST.localize(datetime(2026, 9, 15, 6, 0))


def _item(press, title, minutes=0, link=None):
    dt = T0 + timedelta(minutes=minutes)
    return {
        'pub_dt': dt,
        'datetime_str': dt.strftime('%Y-%m-%d %H:%M'),
        'title': title,
        'link': link or f'https://n.news.naver.com/article/{press}/{minutes}',
        'short_link': f'https://nr2.kr/s/{press}{minutes}',
        'press': press,
        'category': '📌 기타',
    }


def _run(items):
    """send 파이프라인과 동일하게 최신순 정렬 후 dedup."""
    items = sorted(items, key=lambda x: x['pub_dt'], reverse=True)
    return dedup_items(items, threshold=85)


# ── normalize_title ─────────────────────────────────
def test_normalize_strips_tags_punct_ellipsis():
    assert normalize_title('[단독] 검찰, 백종헌 의원실 사기 채용 정황 포착') == \
           normalize_title('(단독) 검찰 백종헌 의원실 "사기 채용" 정황 포착…')
    assert normalize_title('[속보] Ａ사 적발') == normalize_title('a사 적발')  # 전각→반각+소문자
    assert len(normalize_title('가' * 100)) == 40                              # 40자 절단


# ── 1. KBS 백종헌 3건(기사 ID 변경 재수집) → 1건 + 업데이트 2회 ──
def test_kbs_baek_three_versions_merge():
    title = '[단독] 검찰, 백종헌 의원실 사기 채용 정황 포착'
    items = [
        _item('KBS', title, minutes=0,
              link='https://n.news.naver.com/article/056/0012257077'),
        _item('KBS', title, minutes=60,
              link='https://n.news.naver.com/article/056/0012257223'),
        _item('KBS', title + '…', minutes=120,
              link='https://n.news.naver.com/article/056/0012257287'),
    ]
    kept, removed = _run(items)
    assert len(kept) == 1 and removed == 2
    it = kept[0]
    assert '(업데이트 2회)' in it['title']
    assert it['link'].endswith('0012257287')          # 링크 = 가장 최근
    assert it['datetime_str'] == T0.strftime('%Y-%m-%d %H:%M')  # 시각 = 최초


# ── 2. 잘린 제목: "5시간 내달렸다" vs "시간 내달렸다" → 1건 ──
def test_kbs_truncated_title_merges():
    items = [
        _item('KBS', '[단독] 음주 뺑소니 5시간 내달렸다 결국 검거', minutes=0),
        _item('KBS', '[단독] 음주 뺑소니 시간 내달렸다 결국 검거...', minutes=30),
    ]
    kept, removed = _run(items)
    assert len(kept) == 1 and removed == 1
    assert '(업데이트 1회)' in kept[0]['title']


# ── 3. 서울신문 어순 재배열 → 1건 (token_set 유사도) ──
def test_seoul_reordered_title_merges():
    items = [
        _item('서울신문', "[단독] 회장·사외이사도 '성적표' 받는다… 금융사 '연임 동맹' 제동", minutes=0),
        _item('서울신문', "[단독] 금융지주 '연임 동맹' 제동…회장·사외이사 '성적표' 받는다", minutes=45),
    ]
    kept, removed = _run(items)
    assert len(kept) == 1 and removed == 1


# ── 4. 같은 사건이라도 언론사 다르면 절대 병합 금지 → 2건 유지 ──
def test_different_outlets_never_merge():
    title = '[단독] 검찰, 백종헌 의원실 사기 채용 정황 포착'
    items = [
        _item('조선일보', title, minutes=0),
        _item('경향신문', title, minutes=10),
    ]
    kept, removed = _run(items)
    assert len(kept) == 2 and removed == 0
    assert not any('업데이트' in it['title'] for it in kept)


# ── 5. 실행 간 기억: 48시간 내 발송된 동일 키 → 제외 ──
def test_seen_within_ttl_excluded():
    item = _item('KBS', '[단독] 검찰, 백종헌 의원실 사기 채용 정황 포착')
    seen = {('KBS', normalize_title(item['title']))}   # TTL 내 발송 이력
    kept, removed = filter_seen([item], seen)
    assert kept == [] and removed == 1
    # 이력에 없는(=TTL 경과로 정리된) 키는 정상 발송
    kept2, removed2 = filter_seen([item], set())
    assert len(kept2) == 1 and removed2 == 0
    # DB 불가(None) 시 필터 생략 — 발송 우선
    kept3, removed3 = filter_seen([item], None)
    assert len(kept3) == 1 and removed3 == 0


# ── 부가: 무관 기사끼리는 병합되지 않음 (과병합 방어) ──
def test_unrelated_same_outlet_not_merged():
    items = [
        _item('KBS', '[단독] 검찰, 백종헌 의원실 사기 채용 정황 포착', minutes=0),
        _item('KBS', '[단독] 네이버, 11월 멤버십 전용 새벽배송 가동', minutes=5),
    ]
    kept, removed = _run(items)
    assert len(kept) == 2 and removed == 0
