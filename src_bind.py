"""src_bind.py — 항목↔기사 1:1 생성 바인딩 (2026-10-30).

기존 `source_bind` 는 **사후 토큰 겹침 매칭**이다. 항목이 어느 기사에서 나왔는지
모델에게 묻지 않고, 발행 직전에 가장 비슷한 기사를 역으로 찾아 붙인다.
그래서 ① 기사 없이 생성된 항목도 겹침 2만 넘으면 결속되고 ② 서로 다른 두 기사를
한 문장에 섞어도 한쪽에만 결속돼 통과한다 (10/29~30: 자유통일당 논평,
위성락 지뢰+우크라 혼합, 한미 SCM(10/28)+ADMM-Plus(10/29) 혼합).

이 모듈은 생성 시점에 출처를 **모델이 선언**하게 만든다:
  · 프롬프트의 각 기사에 [#id] 부여
  · 모델은 ▪ 항목 끝에 {src:#id} 를 반드시 붙임
  · src 2개 이상 → 별건 혼합이므로 분리 재생성 1회
  · src 없음 → 무출처로 삭제 + 관리자 DM
발행 전 {src:...} 는 제거한다. 실패해도 발행을 막지 않는다(태그 없으면 원문 유지).
"""
import re
import logging

logger = logging.getLogger("src_bind")

SRC_RE = re.compile(r"\{src:\s*((?:#\d+\s*[,·]?\s*)+)\}")
ID_RE = re.compile(r"#(\d+)")
NO_NEWS_HINTS = ("금일 주요 보도 없음", "주요 이슈 없음")

PROMPT_RULE = (
    "[출처 표기 — 반드시 지킬 것]\n"
    "각 기사 앞에 [#번호]가 붙어 있습니다. 모든 '▪' 항목은 **문장 끝에** 그 항목의 근거\n"
    "기사 번호를 {{src:#번호}} 형식으로 붙이세요. 예: ▪ 국회가 예산안을 의결했음. {{src:#12}}\n"
    "· 근거 기사가 없으면 그 항목을 쓰지 마세요. 번호를 지어내지 마세요.\n"
    "· **한 항목에는 기사 하나만** 씁니다. 서로 다른 사건을 한 문장에 합치지 마세요.\n"
    "  (두 기사를 합쳐야 할 것 같으면 항목을 둘로 나누세요.)\n"
)


def annotate(news_block_line: str, idx: int) -> str:
    """기사 한 줄 앞에 [#id] 부여."""
    return f"[#{idx}] {news_block_line}"


def parse(briefing: str) -> list[tuple[int, str, list[int]]]:
    """→ [(줄번호, 본문(src 제거), [기사 id…])]. ▪ 항목만."""
    out = []
    for i, ln in enumerate(briefing.split("\n")):
        s = ln.strip()
        if not s.startswith("▪") or any(h in s for h in NO_NEWS_HINTS):
            continue
        m = SRC_RE.search(s)
        ids = [int(x) for x in ID_RE.findall(m.group(1))] if m else []
        body = SRC_RE.sub("", s).strip().lstrip("▪").strip()
        out.append((i, body, ids))
    return out


def strip_tags(briefing: str) -> str:
    """발행본에서 {src:...} 제거 + 남은 공백 정리."""
    out = []
    for ln in briefing.split("\n"):
        if SRC_RE.search(ln):
            ln = re.sub(r"\s*" + SRC_RE.pattern, "", ln).rstrip()
        out.append(ln)
    return "\n".join(out)


def has_tags(briefing: str) -> bool:
    return bool(SRC_RE.search(briefing))


SPLIT_PROMPT = """다음 브리핑 항목은 서로 다른 기사 {n}건을 한 문장에 섞었다. 기사별로 항목을 나눠라.

[항목] {body}
{arts}
규칙: 기사 하나당 ▪ 한 줄. 각 줄 끝에 {{src:#번호}}. 원문에 없는 내용 추가 금지.
종결은 명사형(…음/됨/임). ▪ 줄만 출력."""


def _articles_block(pool: list[dict], ids: list[int]) -> str:
    out = []
    for i in ids:
        a = pool[i - 1] if 0 < i <= len(pool) else None
        if a:
            out.append(f"[#{i}] {a.get('title','')}\n     {(a.get('description') or '')[:160]}")
    return "\n".join(out)


def enforce(briefing: str, pool: list[dict], client=None,
            model: str = "claude-haiku-4-5-20251001") -> tuple[str, dict]:
    """src 태그 기준 정리. → (텍스트, {split, dropped, kept, untagged_run}).

    태그가 전혀 없으면(구 프롬프트·모델 미준수) 아무것도 하지 않고 통과시킨다 —
    이 가드 때문에 브리핑이 통째로 비는 일이 없어야 한다.
    """
    info = {"split": [], "dropped": [], "kept": 0, "untagged_run": False}
    if not has_tags(briefing):
        info["untagged_run"] = True
        logger.warning("[src바인딩] {src:#id} 태그 0건 — 모델이 규칙을 따르지 않았다. 통과")
        return briefing, info

    lines = briefing.split("\n")
    for ln_no, body, ids in parse(briefing):
        if not ids:
            lines[ln_no] = None
            info["dropped"].append(body[:40])
            continue
        if len(ids) == 1:
            info["kept"] += 1
            continue
        # 별건 혼합 → 분리 재생성 1회
        gen = []
        if client is not None:
            try:
                resp = client.messages.create(
                    model=model, max_tokens=600,
                    messages=[{"role": "user", "content": SPLIT_PROMPT.format(
                        n=len(ids), body=body, arts=_articles_block(pool, ids))}])
                gen = [l.strip() for l in (resp.content[0].text or "").split("\n")
                       if l.strip().startswith("▪")]
            except Exception as e:
                logger.warning(f"[src바인딩] 분리 재생성 실패: {e}")
        if gen:
            lines[ln_no] = "\n".join(gen)
            info["split"].append(f"{body[:36]}… → {len(gen)}건")
            info["kept"] += len(gen)
        else:
            lines[ln_no] = None
            info["dropped"].append(f"{body[:40]} (별건 혼합·분리 실패)")

    text = "\n".join(l for l in lines if l is not None)
    if info["dropped"] or info["split"]:
        logger.warning(f"[src바인딩] 분리 {len(info['split'])} · 무출처 삭제 {len(info['dropped'])}")
    if info["dropped"]:
        try:
            from ai_briefing import _alert_zero_collection as _dm
            _dm("무출처 제외", " / ".join(info["dropped"][:6]))
        except Exception as e:
            logger.warning(f"[src바인딩] DM 실패(무시): {e}")
    return text, info
