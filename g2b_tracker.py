"""
g2b_tracker.py — AI 행정 트래커 공유 라이브러리 (Phase 1)

나라장터(G2B) 공고에서 지자체 AI 사업을 수집·판정·집계하기 위한 공용 모듈.
  - DB 스키마 (ai_projects / g2b_state) — CREATE IF NOT EXISTS
  - 수요기관명 → 지자체 매핑 (config/gov_mapping.json, 광역16·기초228)
  - 1차 키워드 필터 + 2차 Haiku 판정(예/아니오/애매)
  - 일 호출한도(1,000) 카운터 + 체크포인트 (g2b_state)

사용처: g2b_backfill.py(백필), g2b_daily.py(일일), app/routes/ai_tracker.py(웹)

안전 규칙: 모든 함수는 실패 시 로그만 남기고 None/기본값 반환 —
AESA 브리핑 등 기존 파이프라인에 영향을 주지 않는다.
API 키는 환경변수 G2B_API_KEY 로만 읽는다 (하드코딩 금지).
"""

import os
import json
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("g2b_tracker")

KST = ZoneInfo("Asia/Seoul")
_HERE = os.path.dirname(os.path.abspath(__file__))
MAPPING_PATH = os.path.join(_HERE, "config", "gov_mapping.json")

# ── API (키는 환경변수로만) ───────────────────────
G2B_API_KEY_ENV = "G2B_API_KEY"
G2B_BASE = "http://apis.data.go.kr/1230000/ad/BidPublicInfoService"
G2B_OPS = {  # 오퍼레이션: 용역 기본 + 물품·공사 포함
    "용역": "getBidPblancListInfoServcPPSSrch",
    "물품": "getBidPblancListInfoThngPPSSrch",
    "공사": "getBidPblancListInfoCnstwkPPSSrch",
}
CNTRCT_BASE = "http://apis.data.go.kr/1230000/ao/CntrctInfoService"
CNTRCT_OP = "getCntrctInfoListServcPPSSrch"
DAILY_CALL_LIMIT = 1000

# ── 1차 필터 키워드 (공고명) ──────────────────────
AI_KEYWORDS = ["인공지능", "AI", "생성형", "챗봇", "지능형", "머신러닝",
               "딥러닝", "LLM", "거대언어모델", "RPA", "AI아바타"]

JUDGE_MODEL = "claude-haiku-4-5-20251001"
JUDGE_PROMPT = """다음 공공 입찰공고가 "AI 기술의 도입·활용이 핵심인 사업"인지 판정하라.

공고명: {bid_name}
수요기관: {org_name}

판정 기준:
- 예: AI/생성형/챗봇/머신러닝/LLM/RPA 등 AI 기술 구축·도입·운영이 사업의 핵심
- 아니오: 공고명에 키워드가 있어도 AI가 핵심이 아닌 경우
  (예: 'AI' 가 회사명/제품명 일부, 지능형CCTV 단순 구매, 에어컨(AIR) 오탐 등)
- 애매: 공고명만으로 판단 곤란

반드시 아래 JSON 으로만 응답:
{{"verdict": "예" 또는 "아니오" 또는 "애매", "reason": "판정 근거 1문장"}}"""


# ══════════════════════════════════════════════════
#  1. DB
# ══════════════════════════════════════════════════
def db_conn():
    """DATABASE_URL 기반 psycopg2 연결. 실패 시 None."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.warning("[G2B] DATABASE_URL 없음")
        return None
    try:
        import psycopg2
        return psycopg2.connect(url)
    except Exception as e:
        logger.warning(f"[G2B] DB 연결 실패: {e}")
        return None


def init_db() -> bool:
    """ai_projects / g2b_state 테이블 생성 (CREATE IF NOT EXISTS)."""
    conn = db_conn()
    if not conn:
        return False
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_projects (
                bid_no          VARCHAR(60) PRIMARY KEY,   -- 공고번호(-차수)
                bid_name        TEXT NOT NULL,             -- 공고명
                org_name        TEXT,                      -- 수요기관명
                gov_level       VARCHAR(10),               -- 광역/기초/미분류
                gov_name        VARCHAR(40),               -- 지자체명(광역 or 광역·기초)
                org_tag         VARCHAR(20),               -- 지자체/교육청/공사공단/미분류
                est_price       BIGINT,                    -- 추정가격(원)
                notice_date     DATE,                      -- 공고일
                contract_amount BIGINT,                    -- 계약금액(null 허용)
                status          VARCHAR(20),               -- 공고 상태
                ai_verdict      VARCHAR(10),               -- 예/아니오/애매
                ai_reason       TEXT,                      -- 판정근거
                src_type        VARCHAR(10),               -- 용역/물품/공사
                collected_at    TIMESTAMP DEFAULT NOW()    -- 수집일시
            )""")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS g2b_state (
                key   VARCHAR(60) PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT NOW()
            )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_projects_gov ON ai_projects (gov_name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_projects_date ON ai_projects (notice_date)")
        # 차수 dedup 체계: base_no(차수 제외 공고번호) + is_latest(최신 차수만 TRUE)
        cur.execute("ALTER TABLE ai_projects ADD COLUMN IF NOT EXISTS base_no VARCHAR(50)")
        cur.execute("ALTER TABLE ai_projects ADD COLUMN IF NOT EXISTS bid_ord VARCHAR(6)")
        cur.execute("ALTER TABLE ai_projects ADD COLUMN IF NOT EXISTS is_latest BOOLEAN DEFAULT TRUE")
        cur.execute("ALTER TABLE ai_projects ADD COLUMN IF NOT EXISTS notice_url TEXT")
        # 지방재정365 예산 편성액 축 — Phase 2 선반영 (스키마만)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_budgets (
                id           SERIAL PRIMARY KEY,
                gov_name     VARCHAR(40) NOT NULL,   -- gov_mapping 표기와 동일 ('서울', '경기 수원시')
                fiscal_year  INT NOT NULL,           -- 회계연도
                budget_amount BIGINT,                -- AI 관련 편성액(원)
                category     VARCHAR(60),            -- 세부 분야(선택)
                source       VARCHAR(200),           -- 출처(지방재정365 URL 등)
                note         TEXT,
                collected_at TIMESTAMP DEFAULT NOW(),
                UNIQUE (gov_name, fiscal_year, category)
            )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_projects_base ON ai_projects (base_no)")
        conn.commit()
        conn.close()
        logger.info("[G2B] DB 스키마 확인/생성 완료")
        return True
    except Exception as e:
        logger.warning(f"[G2B] 스키마 생성 실패: {e}")
        try:
            conn.close()
        except Exception:
            pass
        return False


# ── g2b_state: 체크포인트 + 일 호출 카운터 ─────────
def state_get(key: str) -> str | None:
    conn = db_conn()
    if not conn:
        return None
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM g2b_state WHERE key=%s", (key,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def state_set(key: str, value: str) -> None:
    conn = db_conn()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""INSERT INTO g2b_state (key, value, updated_at)
                       VALUES (%s, %s, NOW())
                       ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()""",
                    (key, value))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[G2B] state 저장 실패({key}): {e}")


def api_calls_today() -> int:
    key = f"api_calls_{date.today().isoformat()}"
    try:
        return int(state_get(key) or 0)
    except (TypeError, ValueError):
        return 0


def bump_api_calls(n: int = 1) -> int:
    """호출 카운터 증가 후 현재값 반환."""
    key = f"api_calls_{date.today().isoformat()}"
    cur_val = api_calls_today() + n
    state_set(key, str(cur_val))
    return cur_val


def under_call_limit(margin: int = 20) -> bool:
    """일 한도(1,000) 이내인지 — margin 만큼 여유를 남기고 중단."""
    return api_calls_today() < (DAILY_CALL_LIMIT - margin)


# ══════════════════════════════════════════════════
#  2. 수요기관명 → 지자체 매핑
# ══════════════════════════════════════════════════
_mapping_cache = None


def _load_mapping() -> dict:
    global _mapping_cache
    if _mapping_cache is None:
        with open(MAPPING_PATH, encoding="utf-8") as f:
            _mapping_cache = json.load(f)
    return _mapping_cache


def map_org(org_name: str) -> dict:
    """수요기관명 → {gov_level, gov_name, org_tag}.

    - 교육청/교육지원청, 지방공사·공단은 org_tag 로 별도 태깅 후 소속 지자체 연결
    - 매핑 실패 시 미분류로 보존 (버리지 않음)
    - 동명 기초(중구·동구 등 7개)는 광역 병기된 경우에만 확정
    """
    result = {"gov_level": "미분류", "gov_name": "미분류", "org_tag": "미분류"}
    if not org_name:
        return result
    name = " ".join(org_name.split())

    try:
        m = _load_mapping()
    except Exception as e:
        logger.warning(f"[G2B] 매핑 로드 실패: {e}")
        return result

    # 1) 광역 탐지
    metro_hit = None
    for metro, aliases in m["광역"].items():
        if any(a in name for a in aliases):
            metro_hit = metro
            break

    # 2) 기관 유형 태그
    if "교육지원청" in name:
        org_tag = "교육청"
    elif "교육청" in name:
        org_tag = "교육청"
    elif any(k in name for k in ("공사", "공단", "도시공사", "시설공단", "개발공사", "교통공사")):
        org_tag = "공사공단"
    else:
        org_tag = "지자체"

    # 3) 기초 탐지 (광역보다 구체적이면 기초 우선)
    basic_hit, basic_metro = None, None
    for metro, basics in m["기초"].items():
        for b in basics:
            if b in name:
                # 동명 기초(여러 광역에 존재)는 광역 병기 필수
                owners = [mm for mm, bl in m["기초"].items() if b in bl]
                if len(owners) > 1:
                    if metro_hit and metro_hit in owners:
                        basic_hit, basic_metro = b, metro_hit
                    # 광역 미병기 동명 구 → 확정 불가 (미분류 유지)
                else:
                    basic_hit, basic_metro = b, metro
        if basic_hit:
            break

    if basic_hit:
        result = {"gov_level": "기초", "gov_name": f"{basic_metro} {basic_hit}",
                  "org_tag": org_tag}
    elif metro_hit:
        result = {"gov_level": "광역", "gov_name": metro_hit, "org_tag": org_tag}
    else:
        # 지자체 미탐지 — 교육청/공사공단이라도 소속 불명이면 미분류 보존
        result = {"gov_level": "미분류", "gov_name": "미분류",
                  "org_tag": org_tag if org_tag != "지자체" else "미분류"}
    return result


# ══════════════════════════════════════════════════
#  3. 1차 키워드 필터 + 2차 AI 판정
# ══════════════════════════════════════════════════
def keyword_hit(bid_name: str) -> bool:
    """공고명 1차 필터. 'AI'는 대소문자 무관 단어로."""
    if not bid_name:
        return False
    upper = bid_name.upper()
    for kw in AI_KEYWORDS:
        if kw == "AI":
            import re
            if re.search(r"(?<![A-Z])AI(?![A-Z])", upper):
                return True
        elif kw.upper() in upper:
            return True
    return False


def judge_ai_project(bid_name: str, org_name: str = "") -> tuple[str, str]:
    """2차 판정: Haiku 로 예/아니오/애매. 실패 시 ('애매', 사유)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return "애매", "ANTHROPIC_API_KEY 없음 — 판정 보류"
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key, timeout=30.0)
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(
                bid_name=bid_name, org_name=org_name or "미상")}],
        )
        text = resp.content[0].text
        s, e = text.find("{"), text.rfind("}")
        data = json.loads(text[s:e + 1])
        verdict = (data.get("verdict") or "").strip()
        if verdict not in ("예", "아니오", "애매"):
            verdict = "애매"
        return verdict, (data.get("reason") or "").strip()[:300]
    except Exception as ex:
        logger.warning(f"[G2B] AI 판정 실패(애매 처리): {ex}")
        return "애매", f"판정 오류: {str(ex)[:100]}"


# ══════════════════════════════════════════════════
#  4. 적재
# ══════════════════════════════════════════════════
def _split_bid_no(bid_no: str) -> tuple[str, str]:
    """'공고번호-차수' → (base_no, 차수). 마지막 '-' 기준 분리."""
    if "-" in bid_no:
        base, _, ord_ = bid_no.rpartition("-")
        return base, ord_ or "00"
    return bid_no, "00"


def upsert_project(row: dict) -> bool:
    """ai_projects upsert + 같은 공고번호(base_no)의 최신 차수만 is_latest 유지."""
    conn = db_conn()
    if not conn:
        return False
    base_no, bid_ord = _split_bid_no(row["bid_no"])
    row = {**row, "base_no": base_no, "bid_ord": bid_ord}
    try:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ai_projects
              (bid_no, base_no, bid_ord, bid_name, org_name, gov_level, gov_name,
               org_tag, est_price, notice_date, contract_amount, status,
               ai_verdict, ai_reason, src_type, notice_url)
            VALUES (%(bid_no)s, %(base_no)s, %(bid_ord)s, %(bid_name)s, %(org_name)s,
                    %(gov_level)s, %(gov_name)s, %(org_tag)s, %(est_price)s,
                    %(notice_date)s, %(contract_amount)s, %(status)s, %(ai_verdict)s,
                    %(ai_reason)s, %(src_type)s, %(notice_url)s)
            ON CONFLICT (bid_no) DO UPDATE SET
                contract_amount = COALESCE(EXCLUDED.contract_amount, ai_projects.contract_amount),
                status = COALESCE(EXCLUDED.status, ai_projects.status),
                notice_url = COALESCE(EXCLUDED.notice_url, ai_projects.notice_url)
        """, row)
        # 같은 공고의 다른 차수 정리: 최신 차수만 is_latest=TRUE
        cur.execute("""
            UPDATE ai_projects a SET is_latest = (a.bid_no = b.latest)
            FROM (SELECT (ARRAY_AGG(bid_no ORDER BY lpad(bid_ord,6,'0') DESC,
                                    collected_at DESC))[1] AS latest
                  FROM ai_projects WHERE base_no = %s) b
            WHERE a.base_no = %s
        """, (base_no, base_no))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"[G2B] upsert 실패({row.get('bid_no')}): {e}")
        try:
            conn.close()
        except Exception:
            pass
        return False


def reconcile_duplicates() -> dict:
    """소급 정리(멱등): base_no 미기입 보정 + base_no별 최신 차수만 is_latest.

    구버전 코드로 적재된 행(백필 러너 등)도 다음 실행 시 자동 정리된다.
    """
    conn = db_conn()
    if not conn:
        return {}
    try:
        cur = conn.cursor()
        cur.execute("""
            UPDATE ai_projects
            SET base_no = regexp_replace(bid_no, '-[^-]*$', ''),
                bid_ord = regexp_replace(bid_no, '^.*-', '')
            WHERE base_no IS NULL""")
        filled = cur.rowcount
        cur.execute("""
            UPDATE ai_projects a SET is_latest = (a.bid_no = b.latest)
            FROM (SELECT base_no,
                         (ARRAY_AGG(bid_no ORDER BY lpad(bid_ord,6,'0') DESC,
                                    collected_at DESC))[1] AS latest
                  FROM ai_projects GROUP BY base_no) b
            WHERE a.base_no = b.base_no
              AND a.is_latest IS DISTINCT FROM (a.bid_no = b.latest)""")
        flipped = cur.rowcount
        cur.execute("SELECT COUNT(*) FROM ai_projects WHERE NOT is_latest")
        superseded = cur.fetchone()[0]
        conn.commit()
        conn.close()
        logger.info(f"[G2B] dedup 정리 — base_no 보정 {filled}건, 플래그 변경 {flipped}건, "
                    f"구차수(무효) 총 {superseded}건")
        return {"filled": filled, "flipped": flipped, "superseded": superseded}
    except Exception as e:
        logger.warning(f"[G2B] dedup 정리 실패(무시): {e}")
        try:
            conn.close()
        except Exception:
            pass
        return {}


if __name__ == "__main__":
    # 매핑 단위 테스트 (DB/API 불필요)
    cases = [
        "서울특별시 강남구", "경기도 수원시", "전라남도 나주시", "광주광역시 광산구",
        "부산광역시 중구", "중구청",  # 동명 — 광역 없으면 미분류
        "경상북도교육청", "성남시 분당구보건소", "서울특별시교육청 강남서초교육지원청",
        "한국전력공사", "화성시도시공사", "행정안전부",
    ]
    for c in cases:
        print(f"{c:28s} → {map_org(c)}")
    print()
    for t in ["AI 기반 민원 챗봇 구축", "옥외 LED 전광판 구매", "생성형 인공지능 행정혁신 ISP",
              "에어컨(AIRCON) 구매", "지능형 CCTV 관제"]:
        print(f"{t:28s} → 키워드 {'HIT' if keyword_hit(t) else 'MISS'}")
