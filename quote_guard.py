"""quote_guard.py — 인용문 실존 검사·따옴표 짝 검사 (2026-11-02).

A. 항목 안의 "…" 문구가 결속 기사 본문에 실제로 있는지 대조한다. 유사도
   partial_ratio 가 임계(기본 85) 미만이면 날조로 보고 **인용만 떼어낸다**.
   떼어낸 뒤 남는 절이 항목으로 성립하지 않으면(12자 미만·술어 없음) 항목을 지운다.
   11/2 적발: "대단히 부정적", "선거용 현금인출기", "재정 도박".

E. 큰따옴표 개수가 홀수면 문장이 잘린 것 — 그 항목은 발행에서 뺀다.
   11/2 적발: 국민의힘 항목이 '"선거용 현금인출기",' 로 끝남.

판정 근거는 결속 기사의 제목+description 이다. 아침/저녁 풀의 description 은
RSS 요약(100~200자)이라 실제 발언이 잘려 있을 수 있다 — 근거가 QUOTE_SRC_FLOOR 자
미만이면 판정을 포기하고 원문을 유지한다(무근거 삭제보다 보수적).

rapidfuzz 가 없으면 difflib 슬라이딩 윈도로 같은 판정을 한다(수 점 차이).
"""
import os
import re
import logging

logger = logging.getLogger("quote_guard")

MIN_RATIO = int(os.environ.get("QUOTE_MIN_RATIO", "85"))   # 이상이면 실존 인정
LOW_RATIO = int(os.environ.get("QUOTE_LOW_RATIO", "60"))   # 근거가 짧을 때 쓰는 느슨한 기준
UNQUOTE_RATIO = int(os.environ.get("QUOTE_UNQUOTE_RATIO", "60"))  # 이 구간은 인용부호만 해제
MIN_QUOTE_LEN = 3            # 이보다 짧은 인용은 검사 제외(단어 강조)
MIN_BODY_LEN = 12            # 인용 제거 후 항목이 성립하는 최소 길이
QUOTE_SRC_FLOOR = 40         # 근거 텍스트가 이보다 짧으면 판정 포기
QUOTE_SRC_FULL = 200         # 이 이상이면 '없으면 없는 것' 으로 보고 MIN_RATIO 적용

_QUOTE_CHARS = '"“”'
_QUOTE_RE = re.compile(r'["“]([^"“”]{1,120})["”]')
# 인용 뒤에 남는 인용 조사 — 함께 떼야 '… 이라고 비판함' 이 안 남는다
_TAIL_RE = re.compile(r'^\s*(?:이?라고|이?라며|이?라는|이?란|라면서|면서|하며|등으로|으로|로)\s*')
_PREDICATE_RE = re.compile(r"(했음|함|됨|밝힘|임|있음|없음|예정|촉구|요구|비판|반박|지적)")
# 인용을 떼면 연결어미가 홀로 남는다 ('… 만나 며 협력 촉구') — 재구성 실패로 본다
_ORPHAN_RE = re.compile(r"(^|[\s…])(며|고|라며|라고|이라|이라며|하며|면서|등)([\s…]|$)")


def partial_ratio(needle: str, hay: str) -> float:
    """needle 이 hay 안에 (근사적으로) 들어 있는가 → 0~100."""
    if not needle or not hay:
        return 0.0
    try:
        from rapidfuzz import fuzz
        return float(fuzz.partial_ratio(needle, hay))
    except Exception:
        import difflib
        n = len(needle)
        if n >= len(hay):
            return difflib.SequenceMatcher(None, needle, hay).ratio() * 100
        best = 0.0
        step = max(1, n // 4)
        for i in range(0, len(hay) - n + 1, step):
            r = difflib.SequenceMatcher(None, needle, hay[i:i + n]).ratio()
            if r > best:
                best = r
        return best * 100


def parity_broken(body: str) -> bool:
    """E — 큰따옴표 개수가 홀수인가."""
    return sum(body.count(c) for c in _QUOTE_CHARS) % 2 == 1


def quotes(body: str) -> list[str]:
    return [m.group(1).strip() for m in _QUOTE_RE.finditer(body or "")]


def _unquote(body: str, quoted: str) -> str:
    """따옴표만 떼고 내용은 남긴다 — 발언은 실재하지만 표현이 의역된 경우."""
    m = next((m for m in _QUOTE_RE.finditer(body) if m.group(1).strip() == quoted), None)
    return body if m is None else body[:m.start()] + quoted + body[m.end():]


def _strip_quote(body: str, quoted: str) -> str:
    """해당 인용(따옴표 포함)과 뒤따르는 인용 조사를 떼고 공백을 정리한다."""
    m = next((m for m in _QUOTE_RE.finditer(body) if m.group(1).strip() == quoted), None)
    if m is None:
        return body
    tail = _TAIL_RE.sub("", body[m.end():])
    out = (body[:m.start()] + " " + tail)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,·…")
    return out


def _is_clean(text: str) -> bool:
    """인용을 뗀 결과가 발행 가능한 문장인가."""
    if len(text) < MIN_BODY_LEN or not _PREDICATE_RE.search(text):
        return False
    if _ORPHAN_RE.search(text):
        return False
    # '…' 로 나뉜 절은 각각 최소 길이를 넘어야 한다 ('… 주장' 같은 빈 절 방지)
    return all(len(c.strip()) >= 8 for c in re.split(r"…+", text) if c.strip())


def threshold(src: str) -> int:
    """근거가 길수록 엄격하게 본다 — 긴 원문에 없는 인용은 실제로 없는 것이다.

    아침/저녁 풀의 description 은 RSS 요약(100~200자)이라 실제 발언이 잘려 있을 수
    있다. 짧은 근거에 MIN_RATIO 를 그대로 쓰면 정상 인용을 대량 삭제한다.
    """
    return MIN_RATIO if len((src or "").strip()) >= QUOTE_SRC_FULL else LOW_RATIO


def check(body: str, src: str) -> tuple[str, list[str]]:
    """→ (교정문, 메모). "" 를 돌려주면 항목 삭제.

    E(짝) 먼저 — 잘린 문장은 인용 대조 자체가 무의미하다.
    """
    if parity_broken(body):
        return "", [f"E 따옴표 홀수 — 항목 삭제: {body[:46]}"]
    qs = [q for q in quotes(body) if len(q) >= MIN_QUOTE_LEN]
    if not qs:
        return body, []
    if len((src or "").strip()) < QUOTE_SRC_FLOOR:
        return body, [f"A 근거 {len((src or '').strip())}자 — 인용 판정 보류: {body[:36]}"]
    out, notes = body, []
    thr = threshold(src)
    for q in qs:
        r = partial_ratio(q, src)
        if r >= thr:
            continue
        # 11/2 실측 — 85 미만이 곧 날조는 아니다. 실제 발언을 줄여 쓴 경우가 섞인다.
        #   '경쟁이 전쟁되면 안 된다' 84.6 ← 원문 '경쟁이 전쟁되면 안돼'
        #   '국채비율 48%로 재정 부채 걱정할 필요 없다' 68.0 ← 원문의 축약
        # 반면 '절대군주가 된다' 30.8, '7천 자 연설에…' 25.9 는 원문에 아예 없다.
        # 그래서 중간 구간은 **인용부호만 해제**해 내용을 살리고, 낮은 쪽만 지운다.
        if thr == MIN_RATIO and r >= UNQUOTE_RATIO:
            out = _unquote(out, q)
            notes.append(f'A 인용 "{q[:24]}" 의역(유사도 {r:.0f}) — 인용부호 해제')
            continue
        new = _strip_quote(out, q)
        if _is_clean(new):
            notes.append(f'A 인용 "{q[:24]}" 원문 없음(유사도 {r:.0f}/{thr}) — 인용 삭제')
            out = new
        else:
            return "", [f'A 인용 "{q[:24]}" 원문 없음(유사도 {r:.0f}/{thr}) — 재구성 실패, 항목 삭제']
    return out, notes
