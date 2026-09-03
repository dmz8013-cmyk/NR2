"""
verify_pass.py — 브리핑 발행 전 자가 검증 패스 (2차 팩트체크 패치)

발행 직전, 고위험 항목만 웹 검색으로 교차 검증한다.

흐름:
  1) 브리핑을 ▪ 불릿 항목 단위로 파싱
  2) 위험 태깅:
     (a) config/facts.json 에 없는 인명+직함 조합
     (b) 상태변화 동사(가결/부결/구형/선고/사망/지명/출범/체결/확정/돌파) 포함
     (c) 구체 수치 + 단정 종결(완곡 표현 없음)
     (d) 외화 금액(천/만/억/조 + 달러·엔 등) — 단위 자릿수 대조
  3) 태깅 항목만 Claude(haiku-4-5 + web_search)로 검증 — 회당 상한 8건
     · 일치     → 통과
     · 불일치   → 수정문으로 교체
     · 확인불가 → "~로 전해졌다" 완곡화 + 항목 앞 ⚠️
  4) 결과 24시간 캐시(/tmp) — 아침·저녁 동일 항목 재검증 방지
  5) 회차별 건수를 DB(verify_log)에 기록 (주간 리포트용)

실패 안전: 이 모듈의 어떤 오류도 발행을 중단시키지 않는다 —
run_verify_pass()는 예외를 삼키고 원문(또는 부분 수정본)을 반환한다.

비용(모델 선정 근거): haiku-4-5 기준 항목당 ~$0.03(토큰+검색 2회),
회당 최대 8건×2회/일 ≈ 월 $9~15. sonnet이면 월 $24+(3만원 초과)라 haiku 채택.
"""

import os
import re
import json
import time
import hashlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import anthropic
except ImportError:
    anthropic = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("verify_pass")

KST = ZoneInfo("Asia/Seoul")
_HERE = os.path.dirname(os.path.abspath(__file__))
FACTS_JSON_PATH = os.path.join(_HERE, "config", "facts.json")

VERIFY_MODEL = "claude-haiku-4-5-20251001"
MAX_VERIFY_PER_RUN = 8          # 회당 검증 상한 (비용 분석 결과 8건 유지 가능)
MAX_SEARCHES_PER_ITEM = 2
CACHE_PATH = "/tmp/verify_pass_cache.json"
CACHE_TTL_SEC = 24 * 3600

# (b) 상태변화 동사 — 활용형 포함 매칭을 위해 어간만
STATE_VERBS = ["가결", "부결", "구형", "선고", "사망", "지명", "출범", "체결", "확정", "돌파"]

# (a) 인명+직함 패턴 (이름 2~4자 + 직함어). 휴리스틱 — 미탐은 허용, 오탐은 검증에서 걸러짐
TITLE_WORDS = (
    "대통령|국무총리|총리|부총리|장관|차관|대표|원내대표|정책위의장|위원장|의원|"
    "대법원장|대법관|헌법재판관|총재|부총재|의장|지사|시장|검찰총장|경찰청장|"
    "감독|회장|사장|구청장|특검|수석|비서관|대변인"
)
# 직함 뒤는 조사/문장부호/공백/끝만 허용 — '대표팀'·'의원장'·'감독관' 같은 확장어 오매칭 방지
NAME_TITLE_RE = re.compile(
    rf"([가-힣]{{2,4}})\s+(?:전\s+)?({TITLE_WORDS})(?=[이가은는을를과와도의로에,.·;)\s]|$)")

# (c) 구체 수치 + 단정 종결
NUMBER_RE = re.compile(r"[0-9][0-9,.]*\s*(?:%|퍼센트|조|억|만|천|달러|원|명|건|배|년|개월|일|포인트|p|도|㎜|mm|km|㎞)")
SOFTENERS = ["전해", "알려", "보인다", "보이", "전망", "예정", "추정", "관측", "가능성", "예상", "계획", "논의", "검토"]

# (d) 외화 금액 — 천/만 단위 자릿수 오역이 잦아 완곡 여부와 무관하게 검증 대상
CURRENCY_RE = re.compile(r"[0-9][0-9,.]*\s*(?:조|억|만|천)\s*[0-9,.]*\s*(?:달러|엔|유로|위안|파운드)")

VERIFY_PROMPT = """다음 문장이 최근 보도와 일치하는지 검색해 판정하라.
일치/불일치(수정문 제시)/확인불가 중 하나로만 응답.
문장에 외화 금액이 있으면 통화 단위와 자릿수(천/만/억/조)가 원보도와 일치하는지
최우선으로 대조하라 — 천/만 단위 환산 오류(예: 8,890억↔8조8,900억)가 잦다.

오늘 날짜: {today}
검증 대상 문장: "{sentence}"

반드시 아래 JSON 형식으로만 최종 응답할 것 (설명 금지):
{{"verdict": "일치" 또는 "불일치" 또는 "확인불가",
 "corrected": "불일치면 보도에 부합하는 수정문 1문장, 확인불가면 원문을 '~로 전해졌다' 체로 완곡화한 1문장, 일치면 빈 문자열"}}"""


# ══════════════════════════════════════════════════
#  1. 파싱 & 위험 태깅
# ══════════════════════════════════════════════════
def _load_known_names() -> set:
    """config/facts.json 인물_직함의 등재 인명 집합."""
    try:
        with open(FACTS_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return set((data.get("인물_직함") or {}).keys())
    except Exception as e:
        logger.warning(f"[자가검증] facts.json 로드 실패(인명 태깅 완화): {e}")
        return set()


def parse_items(briefing: str) -> list[tuple[int, str]]:
    """▪ 불릿 항목 (줄번호, 본문) 목록. ▪ 없으면 빈 목록(검증 스킵)."""
    items = []
    for i, line in enumerate(briefing.split("\n")):
        s = line.strip()
        if s.startswith("▪"):
            items.append((i, s.lstrip("▪").strip()))
    return items


def tag_item(text: str, known_names: set) -> list[str]:
    """위험 사유 태깅. 빈 리스트 = 저위험(검증 생략)."""
    reasons = []
    # (a) 사전에 없는 인명+직함
    for m in NAME_TITLE_RE.finditer(text):
        name = m.group(1)
        if name not in known_names:
            reasons.append(f"미등재 인명+직함: {name} {m.group(2)}")
            break
    # (b) 상태변화 동사
    hit = next((v for v in STATE_VERBS if v in text), None)
    if hit:
        reasons.append(f"상태변화 동사: {hit}")
    # (c) 구체 수치 + 단정 종결 — '다.'체와 명사형·음슴체('~음/됨/임.') 모두 대응
    if (NUMBER_RE.search(text)
            and text.endswith(("다.", "음.", "됨.", "임.", "함."))
            and not any(s in text for s in SOFTENERS)):
        reasons.append("수치+단정 종결")
    # (d) 외화 금액 — 단위 자릿수 대조
    m = CURRENCY_RE.search(text)
    if m:
        reasons.append(f"외화 금액 단위: {m.group(0)}")
    return reasons


# ══════════════════════════════════════════════════
#  2. 24시간 캐시
# ══════════════════════════════════════════════════
def _item_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _cache_load() -> dict:
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        now = time.time()
        return {k: v for k, v in cache.items() if now - v.get("ts", 0) < CACHE_TTL_SEC}
    except Exception:
        return {}


def _cache_save(cache: dict) -> None:
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[자가검증] 캐시 저장 실패(무시): {e}")


# ══════════════════════════════════════════════════
#  3. 웹 검색 검증
# ══════════════════════════════════════════════════
def _verify_with_search(client, text: str) -> dict:
    """항목 1건 검증. 반환: {verdict, corrected, searches}. 오류 시 verdict='오류'."""
    try:
        resp = client.messages.create(
            model=VERIFY_MODEL,
            max_tokens=500,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": MAX_SEARCHES_PER_ITEM,
            }],
            messages=[{
                "role": "user",
                "content": VERIFY_PROMPT.format(
                    today=datetime.now(KST).strftime("%Y년 %m월 %d일"),
                    sentence=text,
                ),
            }],
        )
        # 최종 텍스트 블록에서 JSON 추출
        final_text = ""
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                final_text = block.text
        searches = 0
        try:
            searches = resp.usage.server_tool_use.web_search_requests
        except Exception:
            pass

        start, end = final_text.find("{"), final_text.rfind("}")
        if start != -1 and end > start:
            data = json.loads(final_text[start:end + 1])
            verdict = (data.get("verdict") or "").strip()
            if verdict in ("일치", "불일치", "확인불가"):
                return {"verdict": verdict,
                        "corrected": (data.get("corrected") or "").strip(),
                        "searches": searches}
        # JSON 파싱 실패 → 키워드 폴백
        for v in ("불일치", "확인불가", "일치"):
            if v in final_text:
                return {"verdict": v, "corrected": "", "searches": searches}
        return {"verdict": "오류", "corrected": "", "searches": searches}
    except Exception as e:
        logger.warning(f"[자가검증] 검증 호출 실패(해당 항목 통과 처리): {e}")
        return {"verdict": "오류", "corrected": "", "searches": 0}


# ══════════════════════════════════════════════════
#  4. DB 로그 (주간 리포트용)
# ══════════════════════════════════════════════════
def _log_to_db(stats: dict) -> None:
    """verify_log 테이블에 회차 기록. 실패해도 무시."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.info(f"[자가검증] DATABASE_URL 없음 — DB 로그 생략: {stats}")
        return
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS verify_log (
                id SERIAL PRIMARY KEY,
                run_at TIMESTAMP DEFAULT NOW(),
                briefing_type VARCHAR(30),
                items_total INT, tagged INT, verified INT,
                passed INT, fixed INT, unconfirmed INT, errors INT, searches INT
            )""")
        cur.execute("""
            INSERT INTO verify_log
              (briefing_type, items_total, tagged, verified, passed, fixed,
               unconfirmed, errors, searches)
            VALUES (%(briefing_type)s, %(items_total)s, %(tagged)s, %(verified)s,
                    %(passed)s, %(fixed)s, %(unconfirmed)s, %(errors)s, %(searches)s)
        """, stats)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[자가검증] DB 로그 실패(무시): {e}")


# ══════════════════════════════════════════════════
#  5. 메인 — 발행 직전 훅
# ══════════════════════════════════════════════════
def run_verify_pass(briefing: str, briefing_type: str = "") -> str:
    """검증 패스 실행. 어떤 오류가 나도 발행 가능한 텍스트를 반환한다."""
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key or anthropic is None:
            logger.warning("[자가검증] API 사용 불가 — 스킵")
            return briefing

        lines = briefing.split("\n")
        items = parse_items(briefing)
        if not items:
            logger.info("[자가검증] ▪ 항목 없음 — 스킵")
            return briefing

        known = _load_known_names()
        tagged = []
        for line_no, text in items:
            reasons = tag_item(text, known)
            if reasons:
                tagged.append((line_no, text, reasons))

        stats = {"briefing_type": briefing_type, "items_total": len(items),
                 "tagged": len(tagged), "verified": 0, "passed": 0,
                 "fixed": 0, "unconfirmed": 0, "errors": 0, "searches": 0}

        if not tagged:
            logger.info(f"[자가검증] 태깅 0건 (전체 {len(items)}항목) — 통과")
            _log_to_db(stats)
            return briefing

        to_verify = tagged[:MAX_VERIFY_PER_RUN]
        logger.info(f"[자가검증] 태깅 {len(tagged)}건 중 {len(to_verify)}건 검증 "
                    f"(상한 {MAX_VERIFY_PER_RUN})")

        cache = _cache_load()
        client = anthropic.Anthropic(api_key=api_key, timeout=90.0)

        for line_no, text, reasons in to_verify:
            key = _item_key(text)
            if key in cache:
                result = cache[key]
                logger.info(f"[자가검증] 캐시 적중: {text[:30]}… → {result['verdict']}")
            else:
                result = _verify_with_search(client, text)
                result["ts"] = time.time()
                cache[key] = result
                stats["searches"] += result.get("searches", 0)

            stats["verified"] += 1
            verdict = result["verdict"]
            corrected = (result.get("corrected") or "").strip().lstrip("▪").strip()

            if verdict == "일치":
                stats["passed"] += 1
            elif verdict == "불일치" and corrected:
                lines[line_no] = "▪ " + corrected
                stats["fixed"] += 1
                logger.warning(f"[자가검증] 수정: {text[:40]}… → {corrected[:40]}…")
            elif verdict == "확인불가":
                soft = corrected if corrected else text
                lines[line_no] = "▪ ⚠️ " + soft
                stats["unconfirmed"] += 1
                logger.warning(f"[자가검증] 확인불가(완곡+⚠️): {text[:40]}…")
            else:  # 오류 or 수정문 없는 불일치 → 원문 유지(발행 우선)
                stats["errors"] += 1

        _cache_save(cache)
        _log_to_db(stats)
        logger.info(f"[자가검증] 완료 — 검증 {stats['verified']} / 통과 {stats['passed']} / "
                    f"수정 {stats['fixed']} / 확인불가 {stats['unconfirmed']} / "
                    f"오류 {stats['errors']} / 검색 {stats['searches']}회")
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"[자가검증] 패스 전체 실패 — 원문 그대로 발행: {e}", exc_info=True)
        return briefing


if __name__ == "__main__":
    sample = (
        "🏛️ 정치/시사\n"
        "▪ 국회가 이진숙 의원 제명결의안을 가결했다.\n"
        "▪ 홍길동 기재부 장관이 예산안을 발표했다.\n"
        "▪ 코스피가 3,000선을 돌파했다.\n"
        "▪ 날씨가 흐리고 비가 올 것으로 전망된다.\n"
    )
    known = _load_known_names()
    for _, t in parse_items(sample):
        print(f"- {t[:35]:38s} → {tag_item(t, known) or '저위험'}")
