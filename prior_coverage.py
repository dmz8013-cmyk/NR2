"""prior_coverage.py — 전판 기보도 제거.

직전 24시간 내 어느 모듈(ai_morning/ai_evening/political_*)이든 발행한 사건과 같은 항목은
'새 전개'(이전 항목에 없던 전개 표지어·상태 동사·새 수치)가 없으면 제외한다.
유사도: rapidfuzz token_set_ratio(없으면 difflib) ≥ SIM_THRESHOLD. 실패 시 아무것도 제외하지 않는다."""
import os
import re
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("prior_coverage")
SIM_THRESHOLD = 45.0
HOURS = 24
# 새 전개 = 새 발언(따옴표 인용) · 새 결정(결정 동사) · 새 수치. '출범·결과·추가' 같은 범용어는 표지어가 아님 (2026-10-12)
DECISION_RE = re.compile(r"(결정|의결|가결|부결|확정|선고|판결|지명|임명|철회|취소|승인|사퇴|해임|구속|기소|무죄|유죄|항소|상고|타결|결렬|체결|해산|탄핵|제명)")
QUOTE_RE = re.compile(r"[\"“'‘]([^\"”'’]{4,60})[\"”'’]")
NUM_RE = re.compile(r"\d[\d,.]*")


def _norm(t: str) -> str:
    t = re.sub(r"[^0-9A-Za-z가-힣]", "", t or "")
    return t


def _bigrams(t: str) -> set[str]:
    return {t[i:i + 2] for i in range(len(t) - 1)}


_PARTICLE_RE = re.compile(r"(으로써|에서는|에서|으로|에게|까지|부터|이라고|라고|이며|하며|이|가|은|는|을|를|의|에|과|와|도|로)$")
_MIN_SHARED_TOKENS = 4


def _tokens(t: str) -> list[str]:
    out = []
    for tok in re.findall(r"[0-9A-Za-z가-힣]{2,}", t or ""):
        base = _PARTICLE_RE.sub("", tok) if len(tok) >= 3 else tok
        if len(base) >= 2:
            out.append(base)
    return out


def _token_sim(a_raw: str, b_raw: str) -> float:
    """어절 토큰(조사 제거) 겹침 — 한쪽 토큰이 다른 쪽 토큰의 접두(성공/성공해)면 공유로 본다."""
    A, B = _tokens(a_raw), _tokens(b_raw)
    if not A or not B:
        return 0.0
    shared = 0
    used = set()
    for x in A:
        for j, y in enumerate(B):
            if j in used:
                continue
            if x == y or (len(x) >= 2 and len(y) >= 2 and (x.startswith(y) or y.startswith(x))):
                shared += 1; used.add(j); break
    if shared < _MIN_SHARED_TOKENS:
        return 0.0
    return shared / min(len(A), len(B)) * 100


def _sim(a: str, b: str, a_raw: str = "", b_raw: str = "") -> float:
    """max(문자 2-gram 겹침 계수, 토큰 겹침) ×100 — 조사·어미 변화에 강하고, 새 항목이
    이전 항목의 일부(같은 사건의 축약)일 때도 높게 나온다."""
    A, B = _bigrams(a), _bigrams(b)
    bi = len(A & B) / min(len(A), len(B)) * 100 if A and B else 0.0
    return max(bi, _token_sim(a_raw or a, b_raw or b))


def parse_items(text: str) -> list[str]:
    return [ln.strip().lstrip("▪").strip() for ln in (text or "").split("\n") if ln.strip().startswith("▪")]


def load_recent_items(hours: int = HOURS, exclude_type: str | None = None, now: datetime | None = None) -> list[dict]:
    """briefings 테이블에서 최근 hours 시간 발행본의 ▪ 항목 → [{type, created_at, text}]."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return []
    try:
        import psycopg2
        conn = psycopg2.connect(url); cur = conn.cursor()
        since = (now or datetime.now()).replace(tzinfo=None) - timedelta(hours=hours)
        cur.execute("""(SELECT briefing_type, created_at, content FROM briefings WHERE created_at >= %s)
                       UNION
                       (SELECT briefing_type, created_at, content FROM briefings ORDER BY created_at DESC LIMIT 3)
                       ORDER BY created_at""", (since,))
        out = []
        for btype, created, content in cur.fetchall():
            if exclude_type and btype == exclude_type and created >= since + timedelta(hours=hours) - timedelta(minutes=30):
                continue
            for it in parse_items(content):
                out.append({"type": btype, "created_at": created, "text": it})
        conn.close()
        return out
    except Exception as e:
        logger.warning(f"[기보도] 최근 발행본 조회 실패(제거 생략): {e}")
        return []


def _quote_overlap(a: str, b: str) -> float:
    A, B = _bigrams(_norm(a)), _bigrams(_norm(b))
    return len(A & B) / min(len(A), len(B)) if A and B else 0.0


def is_new_development(new_text: str, prior_text: str) -> bool:
    """새 발언(이전에 없던 인용문) / 새 결정(이전에 없던 결정 동사) / 새 수치(이전에 없던 숫자 2개 이상)."""
    prior_q = [q.strip() for q in QUOTE_RE.findall(prior_text)]
    new_q = [q.strip() for q in QUOTE_RE.findall(new_text)]
    shared = any(q in pq or pq in q or _quote_overlap(q, pq) >= 0.6 for q in new_q for pq in prior_q)
    if new_q and not prior_q and not shared:
        return True                      # 이전에 인용이 전혀 없던 사건에 새 발언이 붙음
    if shared:
        pass                             # 같은 발언 건 — 추가 인용 조각은 새 전개가 아님
    if set(DECISION_RE.findall(new_text)) - set(DECISION_RE.findall(prior_text)):
        return True
    new_nums = set(NUM_RE.findall(new_text)) - set(NUM_RE.findall(prior_text))
    return len(new_nums) >= 2


_SUBJECT_NAMES: list[str] | None = None


def _subject_names() -> list[str]:
    global _SUBJECT_NAMES
    if _SUBJECT_NAMES is None:
        try:
            import json
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "facts.json"), encoding="utf-8") as f:
                _SUBJECT_NAMES = list((json.load(f).get("인물_직함") or {}).keys())
        except Exception:
            _SUBJECT_NAMES = []
    return _SUBJECT_NAMES


def same_person_event(new_text: str, prior_text: str) -> bool:
    """같은 사전 인물 + 사건 키워드(조사 제거 토큰) 2개 이상 겹치면 같은 사건."""
    names = [n for n in _subject_names() if n in new_text and n in prior_text]
    if not names:
        return False
    a = set(_tokens(new_text)) - set(names)
    b = set(_tokens(prior_text)) - set(names)
    shared = {x for x in a if any(x == y or x.startswith(y) or y.startswith(x) for y in b) and len(x) >= 2}
    return len(shared) >= 2


def shares_quote(a: str, b: str) -> bool:
    qa = [q.strip() for q in QUOTE_RE.findall(a)]; qb = [q.strip() for q in QUOTE_RE.findall(b)]
    return any(x in y or y in x or _quote_overlap(x, y) >= 0.6 for x in qa for y in qb)


def match_prior(text: str, prior: list[dict], threshold: float = SIM_THRESHOLD) -> tuple[dict | None, float]:
    best, score = None, 0.0
    n = _norm(text)
    for p in prior:
        s = _sim(n, _norm(p["text"]), text, p["text"])
        if same_person_event(text, p["text"]) or shares_quote(text, p["text"]):
            s = max(s, threshold)          # 같은 인물 + 사건 키워드 2개, 또는 같은 인용문 → 기보도로 간주
        if s > score:
            best, score = p, s
    return (best, score) if score >= threshold else (None, score)


def filter_prior_coverage(briefing: str, prior: list[dict], threshold: float = SIM_THRESHOLD) -> tuple[str, list[str], list[str]]:
    """→ (텍스트, 제외 제목 목록, 새 전개로 유지한 제목 목록)."""
    if not prior:
        return briefing, [], []
    lines = briefing.split("\n")
    excluded, kept = [], []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("▪"):
            continue
        body = s.lstrip("▪").strip()
        hit, score = match_prior(body, prior, threshold)
        if not hit:
            continue
        if is_new_development(body, hit["text"]):
            kept.append(f"{body[:60]} (유사 {score:.0f}, {hit['type']} 기보도·새 전개)")
            continue
        excluded.append(f"{body[:60]} (유사 {score:.0f}, {hit['type']} {hit['created_at']:%m/%d %H:%M})")
        lines[i] = None
    if excluded:
        logger.warning(f"[기보도] 제외 {len(excluded)}건: {excluded}")
    return "\n".join(l for l in lines if l is not None), excluded, kept
