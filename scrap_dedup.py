"""scrap_dedup.py — 단독 스크랩봇 발송 직전 중복 제거 단계.

배경: 같은 기사가 업데이트되면 네이버 기사 ID(oid/aid)가 바뀌어 새 기사로
수집됨 (예: KBS 백종헌 기사 1건이 0012257077/223/287 세 번 발송).
제목이 "..."로 잘린 채 수집되는 경우도 있음.

3단 방어 (전부 발송 직전 단계 — 수집 로직 불변):
  1) 배치 내 정확 키 dedup — 키 = (언론사, 정규화 제목 40자)
  2) 배치 내 유사도 dedup — 같은 언론사 안에서만 token_set_ratio ≥ 임계값 병합.
     언론사가 다르면 같은 사건이라도 절대 병합하지 않음(각자 취재 가치).
  3) 실행 간 기억 — Postgres scrap_seen 테이블, TTL(기본 48h) 내 발송분 제외

병합 규칙: 링크는 가장 최근 기사, 발생 시각은 최초 기사, 제목 뒤 " (업데이트 N회)".
설정: config/scrap_dedup.json (similarity_threshold=85, seen_ttl_hours=48 기본값).
안전: 어떤 실패(설정/DB/rapidfuzz 부재)도 발송을 막지 않음 — 해당 단계만 스킵.
"""
import os
import re
import json
import logging
import unicodedata
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_HERE, 'config', 'scrap_dedup.json')

DEFAULT_THRESHOLD = 85
DEFAULT_TTL_HOURS = 48

# [단독]/(단독)/<단독>/【단독】/[속보]/[단독보도] 등 괄호 태그 — 위치 무관 제거
_TAG_RE = re.compile(r'[\[\(<【]\s*(?:단독(?:보도|입수|취재)?|특종|속보)\s*[\]\)>】]')
# 한글·영문·숫자 외 전부(구두점·말줄임 …/...·공백·따옴표 등) 제거용
_STRIP_RE = re.compile(r'[^가-힣a-z0-9]')
_STRIP_KEEP_SPACE_RE = re.compile(r'[^가-힣a-z0-9\s]')
KEY_LEN = 40


def load_config() -> dict:
    """설정 로드 — 실패 시 기본값 (발송 우선)."""
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            data = json.load(f)
        return {
            'similarity_threshold': int(data.get('similarity_threshold', DEFAULT_THRESHOLD)),
            'seen_ttl_hours': int(data.get('seen_ttl_hours', DEFAULT_TTL_HOURS)),
        }
    except Exception as e:
        logger.warning(f'[dedup] 설정 로드 실패 — 기본값 사용: {e}')
        return {'similarity_threshold': DEFAULT_THRESHOLD, 'seen_ttl_hours': DEFAULT_TTL_HOURS}


def normalize_title(title: str, keep_spaces: bool = False) -> str:
    """제목 정규화.

    단독/속보류 태그 제거 → NFKC(전각/반각 통일) → 소문자 → 구두점·말줄임 제거.
    keep_spaces=False(기본): 공백까지 제거 후 앞 40자 절단 — 정확 키용.
    keep_spaces=True: 공백(단어 경계) 유지, 절단 없음 — 유사도(token_set) 비교용.
    """
    t = _TAG_RE.sub(' ', title or '')
    t = unicodedata.normalize('NFKC', t).lower()
    if keep_spaces:
        return ' '.join(_STRIP_KEEP_SPACE_RE.sub(' ', t).split())
    return _STRIP_RE.sub('', t)[:KEY_LEN]


def _fuzzy_ratio(a: str, b: str) -> float:
    try:
        from rapidfuzz import fuzz
        return fuzz.token_set_ratio(a, b)
    except ImportError:
        logger.warning('[dedup] rapidfuzz 미설치 — 유사도 병합 생략(정확 키만)')
        return 0.0


def dedup_items(items: list[dict], threshold: int | None = None) -> tuple[list[dict], int]:
    """배치 내 dedup — 섹션 무관 전역.

    입력은 pub_dt 내림차순(최신 우선) 가정 — send 파이프라인의 정렬 그대로.
    같은 키(언론사, 정규화 제목) 또는 같은 언론사 내 유사도 ≥ threshold 를
    1클러스터로 묶고, 클러스터당 1건만 남김:
      - 링크(link/short_link)·제목·분류 = 가장 최근 기사 것
      - 발생 시각(pub_dt/datetime_str) = 최초 기사 것
      - 병합이 있으면 제목 뒤 " (업데이트 N회)" (N = 병합된 이전 버전 수)
    반환: (남긴 목록[pub_dt 내림차순], 제거 건수)
    """
    if threshold is None:
        threshold = load_config()['similarity_threshold']

    clusters = []   # 각 원소: {'rep': item, 'key', 'fuzzy', 'outlet', 'members': [...]}
    for it in items:
        outlet = it.get('press') or ''
        key = normalize_title(it.get('title', ''))
        fuzzy = normalize_title(it.get('title', ''), keep_spaces=True)

        target = None
        for c in clusters:
            if c['outlet'] != outlet:
                continue                    # 언론사 다르면 절대 병합 금지
            if c['key'] == key:
                target = c
                break
            if _fuzzy_ratio(c['fuzzy'], fuzzy) >= threshold:
                target = c
                break
        if target:
            target['members'].append(it)
        else:
            clusters.append({'rep': it, 'key': key, 'fuzzy': fuzzy,
                             'outlet': outlet, 'members': [it]})

    kept, removed = [], 0
    for c in clusters:
        members = c['members']
        item = dict(c['rep'])               # 최신 기사(입력이 최신순이라 첫 멤버)
        n_updates = len(members) - 1
        item['_updates'] = n_updates        # scrap_seen 기록용 (표시 안 됨)
        if n_updates:
            earliest = min(members, key=lambda x: x['pub_dt'])
            item['pub_dt'] = earliest['pub_dt']
            item['datetime_str'] = earliest['datetime_str']
            item['title'] = f"{item['title']} (업데이트 {n_updates}회)"
            removed += n_updates
        kept.append(item)

    kept.sort(key=lambda x: x['pub_dt'], reverse=True)
    return kept, removed


# ══════════════════════════════════════════════════
#  실행 간 기억 — Postgres scrap_seen
# ══════════════════════════════════════════════════
def _db_conn():
    from g2b_tracker import db_conn
    return db_conn()


def _ensure_table(cur) -> None:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scrap_seen (
            outlet       TEXT NOT NULL,
            title_key    TEXT NOT NULL,
            first_seen   TIMESTAMPTZ NOT NULL,
            last_url     TEXT,
            update_count INT DEFAULT 0,
            PRIMARY KEY (outlet, title_key)
        )""")


def load_seen_keys(ttl_hours: int | None = None) -> set[tuple[str, str]] | None:
    """TTL 내 발송 이력 키 집합. 지난 행은 매 실행 시 정리.

    DB 불가 시 None — 호출부는 실행 간 필터만 생략(배치 dedup은 유지).
    """
    if ttl_hours is None:
        ttl_hours = load_config()['seen_ttl_hours']
    conn = None
    try:
        conn = _db_conn()
        if not conn:
            return None
        cur = conn.cursor()
        _ensure_table(cur)
        cur.execute("DELETE FROM scrap_seen WHERE first_seen < NOW() - %s * INTERVAL '1 hour'",
                    (ttl_hours,))
        cur.execute("SELECT outlet, title_key FROM scrap_seen")
        seen = {(r[0], r[1]) for r in cur.fetchall()}
        conn.commit()
        conn.close()
        return seen
    except Exception as e:
        logger.warning(f'[dedup] seen 조회 실패 — 실행 간 필터 생략: {e}')
        try:
            conn and conn.close()
        except Exception:
            pass
        return None


def filter_seen(items: list[dict], seen: set[tuple[str, str]] | None) -> tuple[list[dict], int]:
    """TTL 내 이미 발송된 키 제외 (순수 함수 — seen 집합 주입)."""
    if not seen:
        return items, 0
    kept = [it for it in items
            if (it.get('press') or '', normalize_title(it.get('title', ''))) not in seen]
    return kept, len(items) - len(kept)


def record_sent(items: list[dict]) -> None:
    """발송 성공분 upsert — 다음 실행의 재발송 차단 근거. 실패는 로그만."""
    if not items:
        return
    conn = None
    try:
        conn = _db_conn()
        if not conn:
            return
        cur = conn.cursor()
        _ensure_table(cur)
        for it in items:
            cur.execute("""
                INSERT INTO scrap_seen (outlet, title_key, first_seen, last_url, update_count)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (outlet, title_key) DO UPDATE
                  SET last_url = EXCLUDED.last_url,
                      update_count = scrap_seen.update_count + 1
            """, (it.get('press') or '', normalize_title(it.get('title', '')),
                  it['pub_dt'], it.get('link', ''), int(it.get('_updates', 0))))
        conn.commit()
        conn.close()
        logger.info(f'[dedup] scrap_seen 기록 {len(items)}건')
    except Exception as e:
        logger.warning(f'[dedup] scrap_seen 기록 실패(무시): {e}')
        try:
            conn and conn.close()
        except Exception:
            pass


def dedup_pipeline(items: list[dict]) -> tuple[list[dict], int]:
    """발송 직전 전체 파이프라인: 배치 dedup → 실행 간 seen 필터.

    반환: (발송 목록, 제거 총 건수). 어떤 실패도 발송을 막지 않음.
    """
    cfg = load_config()
    deduped, removed_batch = dedup_items(items, cfg['similarity_threshold'])
    seen = load_seen_keys(cfg['seen_ttl_hours'])
    final, removed_seen = filter_seen(deduped, seen)
    if removed_batch or removed_seen:
        logger.info(f'[dedup] 배치 병합 {removed_batch}건 · 기발송 제외 {removed_seen}건 '
                    f'→ {len(final)}건 발송')
    return final, removed_batch + removed_seen
