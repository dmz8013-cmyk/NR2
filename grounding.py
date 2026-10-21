"""grounding.py — 항목 ↔ 원문 대조 가드 (2026-10-19 13:00판 결함 반영).

LLM이 원문에 없는 강도를 얹거나 수치를 지어내는 두 패턴을 발행 전에 끊는다.

  (1) 동사 과장 — '적발·폭로·전격·선언' 등 강도 높은 동사가 매칭된 원문에 없으면
      원문이 실제로 쓴 동사로 대체하고, 못 찾으면 중립 동사로 낮춘다.
      예) 확정손실 '집계' → '적발'로 과장 / 원문에 없는 '졸속 심사 의혹'
  (2) 원문에 없는 수치 — 항목의 숫자 토큰이 매칭 원문 문자열에 그대로 없으면
      해당 수치 절을 삭제하고, 절만으로 이뤄진 항목은 통째로 삭제한다.
      예) '건조대금 10%' — 원문에 없음

매칭 원문은 수집 풀(LAST_ARTICLES)의 제목+본문 요약 전문이며, 프롬프트에 넘긴
150자 절단본이 아니다. 어떤 실패도 발행을 막지 않는다 — 판정 불가면 원문 유지.
"""
import re
import logging

logger = logging.getLogger("grounding")

# (1) 과장 동사 → 원문에서 못 찾았을 때 내려 쓸 중립 표현
OVERSTATED = {
    "적발": "확인",
    "폭로": "주장",
    "선언": "발표",
    "강행": "추진",
    "파문": "논란",
    "경질": "교체",
    "실토": "인정",
    "덜미": "적발 확인",
}
# 과장 수식어 — 원문에 없으면 동사 대체가 아니라 삭제 (2026-10-19 '졸속 심사 의혹')
MODIFIERS = ("졸속", "무더기", "노골적", "전격")
# 원문이 실제로 쓴 동사 후보 — 과장 동사 자리에 우선 끼워 넣는다
SOURCE_VERBS = ("집계", "확인", "발표", "공개", "지적", "주장", "제기", "보고", "통보",
                "밝힘", "설명", "요구", "의결", "발의", "접수", "신고", "제출", "검토")

# 입장·태도 동사 — 방향을 뒤집으면 전혀 다른 사실이 된다(2026-10-21: 대통령이 '반박'한
# 발언을 '적법한 과정이라 비판'으로 출력). 원문에 같은 동사가 없으면 중립 동사로 내린다.
STANCE_VERBS = {
    "비판": "언급", "반박": "언급", "규탄": "언급", "옹호": "언급", "지지": "언급",
    "질타": "언급", "성토": "언급", "찬성": "언급", "반대": "언급", "환영": "언급",
}
# 진행 단계 동사 — '검토'를 '추진'으로 올리는 유형(결함5 헤드라인)
STAGE_VERBS = {"추진": "검토", "확정": "검토", "결정": "검토", "시행": "검토"}

# (2) 수치 토큰 — 단위를 동반한 숫자만 검사 (연도·날짜·조문 번호는 제외)
NUM_RE = re.compile(r"\d[\d,.]*\s*(?:%|퍼센트|조|억|만|천|원|달러|명|건|석|표|배|포인트|%p|p|km|㎞|t|톤)")
EXEMPT_RE = re.compile(r"(\d{4}\s*년|\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}/\d{1,2}|제\s*\d+\s*조|\d+\s*기|\d+\s*대\s*국회)")
_CLAUSE_SPLIT = re.compile(r"[,·、]|(?<=[음됨임함])\s+|\s+(?=[가-힣]{2,}은\s)")

_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_STOP = {"있음", "없음", "했음", "밝힘", "대한", "관련", "이번", "지난", "오늘", "전날"}


def _toks(t: str) -> set[str]:
    """source_bind 의 토큰+어간 구현을 공유 — 조사 때문에 정상 항목이 미매칭되던 문제.
    (2026-10-21: '장외집회를' vs '장외집회', '과정이라' vs '과정이라는')"""
    try:
        from source_bind import tokens
        return tokens(t)
    except Exception:
        return {w for w in _TOKEN_RE.findall(t or "") if w not in _STOP}


def source_text(a: dict) -> str:
    return f"{a.get('title', '')} {a.get('description', '')}"


def best_source(body: str, articles: list[dict], min_overlap: int = 2) -> str | None:
    """항목과 토큰이 가장 많이 겹치는 기사 전문. 겹침이 min_overlap 미만이면 None."""
    bt = _toks(body)
    best, score = None, 0
    for a in articles or []:
        txt = source_text(a)
        n = len(bt & _toks(txt))
        if n > score:
            best, score = txt, n
    return best if score >= min_overlap else None


def _norm_num(s: str) -> str:
    return re.sub(r"[,\s]", "", s)


def missing_numbers(body: str, src: str) -> list[str]:
    """항목의 수치 중 원문 문자열에 그대로 없는 것들."""
    exempt = {_norm_num(m.group(0)) for m in EXEMPT_RE.finditer(body)}
    src_n = _norm_num(src)
    out = []
    for m in NUM_RE.finditer(body):
        tok = m.group(0)
        n = _norm_num(tok)
        if n in exempt or any(n in e for e in exempt):
            continue
        if n not in src_n:
            out.append(tok)
    return out


def _strip_clause(body: str, token: str) -> str:
    """수치 토큰이 들어간 절을 삭제. 남은 문장이 너무 짧으면 빈 문자열."""
    parts = [p for p in _CLAUSE_SPLIT.split(body) if p and p.strip()]
    if len(parts) > 1:
        kept = [p for p in parts if token not in p]
        if kept and len("".join(kept).strip()) >= 15:
            return re.sub(r"\s{2,}", " ", ", ".join(x.strip() for x in kept)).strip(" ,·")
    return ""


def fix_verbs(body: str, src: str) -> tuple[str, list[str]]:
    """원문에 없는 과장 표현 교정 — 동사는 원문 동사(없으면 중립)로 대체, 수식어는 삭제."""
    notes = []
    out = body
    for word in MODIFIERS:                       # 수식어: 항상 삭제
        if word in out and word not in src:
            new = re.sub(r"\s{2,}", " ", out.replace(word, "")).strip(" ,·")
            if len(new) >= 10:
                notes.append(f"{word} → (삭제)")
                out = new
    for verb, neutral in OVERSTATED.items():     # 동사: 원문 동사 우선
        if verb not in out or verb in src:
            continue
        repl = next((v for v in SOURCE_VERBS if v in src), None) or neutral
        new = re.sub(r"\s{2,}", " ", out.replace(verb, repl)).strip(" ,·")
        if new != out and len(new) >= 10:
            notes.append(f"{verb} → {repl or '(삭제)'}")
            out = new
    for verb, neutral in STANCE_VERBS.items():   # 입장 동사: 원문에 없으면 중립화
        if verb in out and verb not in src:
            new = out.replace(verb, neutral)
            if len(new) >= 10:
                notes.append(f"입장 동사 {verb} → {neutral}(원문 없음)")
                out = new
    for verb, down in STAGE_VERBS.items():       # 단계 동사: 원문이 아래 단계면 내림
        if verb in out and verb not in src and down in src:
            new = out.replace(verb, down)
            if len(new) >= 10:
                notes.append(f"단계 동사 {verb} → {down}(원문 기준)")
                out = new
    return out, notes


# ── 헤드라인(2번째 줄) 전용 — style_fix 는 ▪ 줄만, headline_guard 는 프레임 어휘만
#    검사해 헤드라인의 사실 오류·오타가 그대로 나갔다 (2026-10-21 결함5)
BAD_HEADLINE_TAIL = re.compile(r"(가다|오다|하다|되다|보다|짓다|말다)\s*$")


def check_headline(headline: str, articles: list[dict]) -> tuple[str, list[str]]:
    """헤드라인을 수집 풀 제목 전체와 대조 — 과장·입장·단계 동사 교정 + 종결 오타 정리."""
    notes: list[str] = []
    src = " ".join(f"{a.get('title', '')} {(a.get('description') or '')[:120]}" for a in articles or [])
    if not src.strip():
        return headline, notes
    out, vnotes = fix_verbs(headline, src)
    notes += [f"헤드라인 {n}" for n in vnotes]
    m = BAD_HEADLINE_TAIL.search(out)
    if m:
        trimmed = out[:m.start()].rstrip(" ,·…")
        if len(trimmed) >= 8:
            notes.append(f"헤드라인 종결 '{m.group(1)}' 삭제")
            out = trimmed
    return out, notes


def apply(briefing: str, articles: list[dict]) -> tuple[str, list[str]]:
    """브리핑 전문 → (교정본, 변경 메모). 매칭 원문을 못 찾은 항목은 건드리지 않는다."""
    lines = briefing.split("\n")
    notes: list[str] = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("▪") or "금일 주요 보도 없음" in s:
            continue
        body = s.lstrip("▪").strip()
        src = best_source(body, articles)
        if not src:
            continue

        body2, vnotes = fix_verbs(body, src)
        for n in vnotes:
            notes.append(f"동사 과장: {n} ({body[:28]}…)")

        for tok in missing_numbers(body2, src):
            stripped = _strip_clause(body2, tok)
            if stripped:
                notes.append(f"원문 밖 수치 '{tok}' 절 삭제 ({body2[:28]}…)")
                body2 = stripped
            else:
                notes.append(f"원문 밖 수치 '{tok}' — 항목 삭제 ({body2[:40]}…)")
                body2 = ""
                break

        if body2 == "":
            lines[i] = None
        elif body2 != body:
            lines[i] = "▪ " + body2
    if notes:
        logger.warning(f"[원문대조] 교정 {len(notes)}건: {notes[:6]}")
    return "\n".join(l for l in lines if l is not None), notes
