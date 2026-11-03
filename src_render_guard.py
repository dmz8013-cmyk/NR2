"""src_render_guard.py — 빈 출처 표기 잔여물 차단 (2026-11-03 F).

증상(11/2 18:00~11/3 13:00 전 회차): 모든 ▪ 항목 끝에 `{}` 가 붙어 발행됐다.

원인은 바인딩 실패가 아니다 — source_bind_log 상 11/3 13:00 은 12건 전부
`bound`(겹침 2~16)였다. `src_bind.PROMPT_RULE` 이 **f-string 의 값으로** 꽂히는
문자열인데 중괄호를 두 겹(`{{src:#번호}}`)으로 적어 두어, 모델이 예시를 그대로
베껴 `{{src:#12}}` 를 달았다. strip_tags 의 정규식은 한 겹만 떼어내므로 바깥
중괄호 두 짝이 `{}` 로 남았다. 근본 수정은 src_bind 쪽(단일 중괄호 + 두 겹 허용)
이고, 이 모듈은 **렌더 직전 마지막 그물**이다.

  · 빈 dict/빈 리스트 표기(`{}` `[]` `{{}}` `[[]]`)는 문자열로 출력하지 않는다
  · 항목 끝 잔여물만 제거한다 — 본문 중간의 괄호는 손대지 않는다
  · 제거 건수를 돌려주고, 전체 항목의 EMPTY_WARN_RATE 를 넘으면 경보 대상
"""
import os
import re
import logging

logger = logging.getLogger("src_render_guard")

# 항목 끝에 연속으로 붙은 빈 괄호만. 중간의 '(주: {})' 같은 표기는 건드리지 않는다.
EMPTY_TAIL_RE = re.compile(r"(?:\s*(?:\{\s*\}|\[\s*\]|\(\s*\)))+\s*$")
# None 이 문자열로 찍힌 경우도 같은 자리에 온다
NONE_TAIL_RE = re.compile(r"\s*(?:None|null|undefined)\s*$")
ITEM_PREFIX = "▪"
EMPTY_WARN_RATE = float(os.environ.get("SRC_EMPTY_WARN_RATE", "0.5"))


def render_src(src) -> str:
    """항목에 덧붙일 출처 표기. 빈 dict/리스트/None 이면 **아무것도 붙이지 않는다**."""
    if not src:
        return ""
    if isinstance(src, dict):
        url = src.get("url") or src.get("link") or ""
        return f" {url}".rstrip() if url else ""
    if isinstance(src, (list, tuple, set)):
        parts = [render_src(x).strip() for x in src]
        return (" " + " ".join(p for p in parts if p)).rstrip()
    return f" {src}".rstrip()


def clean_item(body: str) -> str:
    """항목 한 줄 끝의 빈 괄호·None 잔여물 제거."""
    out = NONE_TAIL_RE.sub("", body or "")
    out = EMPTY_TAIL_RE.sub("", out)
    return out.rstrip()


def clean(text: str) -> tuple[str, int, int]:
    """→ (텍스트, 제거 건수, 전체 항목 수). ▪ 항목 줄만 본다."""
    lines = (text or "").split("\n")
    removed = total = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith(ITEM_PREFIX):
            continue
        total += 1
        new = clean_item(ln.rstrip())
        if new != ln.rstrip():
            lines[i] = new
            removed += 1
    if removed:
        logger.warning(f"[내용검사] src_empty: {removed}/{total} — 빈 출처 표기 제거")
    return "\n".join(lines), removed, total


def over_rate(removed: int, total: int) -> bool:
    """잔여물이 전체 항목의 절반을 넘으면 출처 결속 자체를 의심해야 한다."""
    return bool(total) and (removed / total) > EMPTY_WARN_RATE
