"""style_fix.py — 정치 브리핑 문체 후처리 (2026-10-12).

'~다/했다/밝혔다'로 끝나는 항목 → 명사형 종결로 재작성(LLM, 없으면 결정론 치환).
'전해짐/알려짐/전해져/알려져/것으로 보' 추정형 절은 삭제. 실패 시 원문 유지."""
import re
import logging

logger = logging.getLogger("style_fix")
BAD_END_RE = re.compile(r"(했다|밝혔다|말했다|전했다|이다|있다|된다|한다|됐다|였다|겠다|[가-힣]다)[.。]?\s*$")
RUMOR_RE = re.compile(r"[^.。…\n]*(전해짐|알려짐|전해져|알려져|전해졌|알려졌|것으로 보[임인]|로 보인다|는 관측|추정됨|추정된다)[^.。…\n]*[.。…]?")
_DETERMINISTIC = [(r"했다[.。]?\s*$", "했음."), (r"밝혔다[.。]?\s*$", "밝힘."), (r"말했다[.。]?\s*$", "말함."), (r"전했다[.。]?\s*$", "전함."),
                  (r"됐다[.。]?\s*$", "됨."), (r"였다[.。]?\s*$", "였음."), (r"이다[.。]?\s*$", "임."), (r"있다[.。]?\s*$", "있음."),
                  (r"된다[.。]?\s*$", "됨."), (r"한다[.。]?\s*$", "함."), (r"([가-힣])다[.。]?\s*$", r"\1음.")]

REWRITE_PROMPT = """다음 정치 브리핑 항목을 통신사 데스크 톤의 명사형(…음/됨/임) 또는 사실 서술 술어 종결로 다시 써라.
'~다/했다/밝혔다' 종결 금지, 전언·추정 표현('전해짐/알려짐/것으로 보임') 삭제, 새 사실 추가 금지, 1줄 유지, 큰따옴표 금지.
[항목] {item}
수정문 1줄만 출력."""


def _rewrite(item: str, client, model: str) -> str | None:
    if client is None:
        return None
    try:
        resp = client.messages.create(model=model, max_tokens=200, messages=[{"role": "user", "content": REWRITE_PROMPT.format(item=item)}])
        cand = (resp.content[0].text or "").strip().split("\n")[0].lstrip("▪").strip()
        if cand and not BAD_END_RE.search(cand) and not RUMOR_RE.search(cand):
            return cand
    except Exception as e:
        logger.warning(f"[문체] 재작성 실패: {e}")
    return None


def _deterministic(item: str) -> str:
    t = RUMOR_RE.sub("", item).strip()
    t = re.sub(r"\s{2,}", " ", t).strip(" ,…·")
    if len(t) < 10:
        return ""                                   # 추정형 절뿐인 항목 → 삭제
    for pat, rep in _DETERMINISTIC:
        if re.search(pat, t):
            t = re.sub(pat, rep, t)
            break
    return t


def fix_style(briefing: str, client=None, model: str = "claude-haiku-4-5-20251001") -> tuple[str, list[str]]:
    lines = briefing.split("\n")
    notes = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("▪") or "금일 주요 보도 없음" in s:
            continue
        body = s.lstrip("▪").strip()
        if not (BAD_END_RE.search(body) or RUMOR_RE.search(body)):
            continue
        new = _rewrite(body, client, model)
        if new is None:
            new = _deterministic(body)
        if new == "":
            lines[i] = None
            notes.append(f"{body[:24]}… → 삭제(추정형 전용)")
        elif new != body:
            lines[i] = "▪ " + new
            notes.append(f"{body[-18:]} → {new[-18:]}")
    if notes:
        logger.info(f"[문체] 교정 {len(notes)}건")
    return "\n".join(l for l in lines if l is not None), notes
