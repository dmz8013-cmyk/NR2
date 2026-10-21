"""section_fill.py — 정치 브리핑 섹션 가드 (2026-10-12 13:00판 빈 섹션 사고 반영).

· fill_empty_sections : 후처리(검증·기보도·섹션 이동) 뒤 비거나 1개뿐인 섹션을 수집 기사 풀에서 키워드로 재탐색해
                        LLM 으로 재생성(최대 5개). 후보가 없을 때만 '▪ 금일 주요 보도 없음' 1줄. 헤더만 있는 빈 섹션 발행 금지.
· enforce_breaking    : 북한·미사일·합참·속보·단독·탄핵·계엄 키워드 기사는 해당 섹션 상위 1~2번에 강제 배치(없으면 생성).
· enforce_rebuttal    : 한 정당 섹션에 실린 쟁점의 상대 당 반박 기사가 풀에 있으면 함께 넣는다.
· source_match_guard  : 수집 기사 풀(제목 토큰 2개 이상 겹침)과 매칭되지 않는 항목은 삭제(출처 불명).
· cap_sections        : 섹션 최대 5개.
실패 시 원문 반환 — 어떤 가드도 발송을 막지 않는다."""
import re
import logging

logger = logging.getLogger("section_fill")

SECTIONS = ["이재명 정부", "더불어민주당", "국민의힘", "비교섭단체", "법조"]
SECTION_KEYWORDS = {
    "이재명 정부": ["이재명", "대통령", "청와대", "정부", "국무회의", "총리", "장관", "탄핵", "계엄"],
    "더불어민주당": ["더불어민주당", "민주당", "김민석", "한병도", "여당"],
    "국민의힘": ["국민의힘", "국힘", "장동혁", "정점식", "야당"],
    "비교섭단체": ["조국혁신당", "혁신당", "개혁신당", "진보당", "정의당", "기본소득당", "무소속", "한동훈", "이준석", "조국", "천하람"],
    "법조": ["대법원", "검찰", "경찰", "법원", "재판", "수사", "중수청", "공소청", "국감", "북한", "미사일", "합참", "트럼프",
           "미국", "중국", "일본", "러시아", "우크라이나", "外交", "외교", "美", "中", "日", "러", "우"],
}
BREAKING_RE = re.compile(r"(북한|미사일|합참|속보|단독|탄핵|계엄)")
HARD_RE = re.compile(r"(북한|미사일|합참|탄핵|계엄)")          # 제목 반영·섹션 강제 대상 (속보/단독 라벨은 우선순위만)
BREAKING_SECTION = {"북한": "법조", "미사일": "법조", "합참": "법조", "탄핵": "이재명 정부", "계엄": "이재명 정부"}
PARTY_WORDS = {"더불어민주당": ("민주당", "더불어민주당", "與", "여당"), "국민의힘": ("국민의힘", "국힘", "野", "야당")}
NO_NEWS = "▪ 금일 주요 보도 없음"
MIN_ITEMS, MAX_ITEMS = 2, 5

GEN_PROMPT = """당신은 한국 정치 뉴스 브리핑 AI다. 아래 기사만 근거로 '{section}' 섹션 항목을 {n}개 작성하라.
규칙: 각 항목은 '▪'로 시작하는 1줄(60~110자), 통신사 데스크 톤, 명사형(…음/됨/임) 또는 사실 서술 술어로 종결.
전언·풍문 술어('전해졌다/알려졌다/~로 보인다') 금지, 기사에 없는 사실·수치·감정 추측 금지, 큰따옴표 금지(필요 시 작은따옴표).
사전에 없는 인물의 직함은 기사 표기 그대로. 기사가 섹션과 무관하면 그 기사는 쓰지 말 것. 쓸 기사가 하나도 없으면 'NONE' 만 출력.

[기사]
{articles}

항목만 출력."""


def _header_re():
    try:
        from briefing_layout import SECTION_HEADER_RE
        return SECTION_HEADER_RE
    except Exception:
        return re.compile(r'^(🏛️|💰|🤖|🎯|📌|🇰🇷|🟦|🟥|🎸|🌐)')


def _section_key(line: str) -> str | None:
    for k in SECTIONS:
        if k in line:
            return k
    return None


def parse_sections(briefing: str) -> dict[str, dict]:
    """→ {section: {header_idx, items: [(line_idx, body)], end_idx}} (end = 다음 헤더/구분선 직전)."""
    lines = briefing.split("\n")
    hre = _header_re()
    out, cur = {}, None
    for i, ln in enumerate(lines):
        s = ln.strip()
        if hre.match(s):
            cur = _section_key(s)
            if cur:
                out[cur] = {"header_idx": i, "items": [], "end_idx": i}
            continue
        if cur and cur in out:
            if s.startswith("▪"):
                out[cur]["items"].append((i, s.lstrip("▪").strip()))
                out[cur]["end_idx"] = i
            elif s.startswith("⸻") or s.startswith("━"):
                cur = None
    return out


def _toks(t: str) -> set[str]:
    """조사 제거 토큰 (prior_coverage._tokens 재사용)."""
    try:
        from prior_coverage import _tokens
        return set(_tokens(t))
    except Exception:
        return {x for x in re.findall(r"[0-9A-Za-z가-힣]{2,}", t or "") if len(x) >= 2}


def _overlap(a: str, b: str) -> int:
    """접두 일치(공세/공세에, 골프/골프장)도 공유로 계산."""
    A, B = _toks(a), _toks(b)
    n = 0
    used = set()
    for x in A:
        for y in B:
            if y in used:
                continue
            if x == y or (len(x) >= 2 and len(y) >= 2 and (x.startswith(y) or y.startswith(x))):
                n += 1; used.add(y); break
    return n


def _used_titles(briefing: str, prior_items: list[str] | None) -> list[str]:
    from prior_coverage import parse_items
    return parse_items(briefing) + list(prior_items or [])


def candidates_for(section: str, articles: list[dict], used: list[str], limit: int = 8) -> list[dict]:
    """섹션 키워드가 제목/요약에 있고, 이미 실린 항목·직전 판과 토큰 3개 이상 겹치지 않는 기사."""
    kws = SECTION_KEYWORDS.get(section, [])
    out = []
    for a in articles:
        text = f"{a.get('title', '')} {a.get('description', '')}"
        if not any(k in text for k in kws):
            continue
        if any(_overlap(a.get("title", ""), u) >= 3 for u in used):
            continue
        out.append(a)
    out.sort(key=lambda a: (not bool(BREAKING_RE.search(a.get("title", ""))), ))
    return out[:limit]


def _gen_items(section: str, cands: list[dict], n: int, client, model: str) -> list[str]:
    if not cands or client is None:
        return []
    block = "\n".join(f"{i}. [{a.get('title', '')}] {(a.get('description') or '')[:140]}" for i, a in enumerate(cands, 1))
    try:
        resp = client.messages.create(model=model, max_tokens=600,
                                      messages=[{"role": "user", "content": GEN_PROMPT.format(section=section, n=n, articles=block)}])
        txt = (resp.content[0].text or "").strip()
    except Exception as e:
        logger.warning(f"[섹션채움] 생성 실패({section}): {e}")
        return []
    if txt.upper().startswith("NONE"):
        return []
    items = [ln.strip().lstrip("▪").strip() for ln in txt.split("\n") if ln.strip().startswith("▪")]
    items = [x for x in items if 20 <= len(x) <= 160 and not re.search(r"(전해졌|알려졌|로 보인다|는 관측)", x)]
    return items[:n]


def _insert(lines: list, sec: dict, bodies: list[str], top: bool = False) -> None:
    at = sec["header_idx"] + 1 if top else sec["end_idx"] + 1
    if top and at < len(lines) and not lines[at].strip():
        at += 1                       # 헤더 다음 빈 줄 뒤
    for b in (bodies if not top else reversed(bodies)):
        lines.insert(at, "▪ " + b)
        if not top:
            at += 1


def fill_empty_sections(briefing: str, articles: list[dict], client=None, prior_items: list[str] | None = None,
                        model: str = "claude-haiku-4-5-20251001") -> tuple[str, list[str]]:
    """빈 섹션 → 재탐색·재생성(최대 MAX_ITEMS), 후보 없으면 NO_NEWS. 1개뿐인 섹션은 MIN_ITEMS 까지 보충. → (텍스트, 보고)."""
    notes = []
    for _ in range(len(SECTIONS) + 1):                   # 삽입으로 인덱스가 변하므로 섹션별로 재파싱
        secs = parse_sections(briefing)
        if not secs:
            return briefing, notes
        target = next((k for k in SECTIONS if k in secs and len([b for _, b in secs[k]["items"] if b != NO_NEWS.lstrip("▪ ").strip()]) < MIN_ITEMS
                       and not any(f"채움:{k}" in n or f"보도없음:{k}" in n or f"유지:{k}" in n for n in notes)), None)
        if target is None:
            break
        lines = briefing.split("\n")
        sec = secs[target]
        have = [b for _, b in sec["items"]]
        need = MIN_ITEMS - len(have)
        cands = candidates_for(target, articles, _used_titles(briefing, prior_items))
        gen = _gen_items(target, cands, need, client, model) if cands else []
        if gen:
            _insert(lines, sec, gen)
            notes.append(f"채움:{target} {len(gen)}건(후보 {len(cands)})")
        elif not have:
            lines.insert(sec["header_idx"] + 2 if sec["header_idx"] + 1 < len(lines) and not lines[sec["header_idx"] + 1].strip() else sec["header_idx"] + 1, NO_NEWS)
            notes.append(f"보도없음:{target}(후보 {len(cands)})")
        else:
            notes.append(f"유지:{target} 1건(후보 {len(cands)}, 생성 0)")
        briefing = "\n".join(lines)
    # 루프 2회로 못 채운 나머지 섹션도 점검
    secs = parse_sections(briefing)
    for k in SECTIONS:
        if k in secs and not secs[k]["items"]:
            lines = briefing.split("\n")
            lines.insert(secs[k]["header_idx"] + 1, NO_NEWS)
            briefing = "\n".join(lines)
            notes.append(f"보도없음:{k}")
            secs = parse_sections(briefing)
    if notes:
        logger.warning(f"[섹션채움] {notes}")
    return briefing, notes


def enforce_breaking(briefing: str, articles: list[dict], client=None, model: str = "claude-haiku-4-5-20251001",
                     top_n: int = 2) -> tuple[str, list[str]]:
    """속보 키워드 기사(최신순 top_n)가 브리핑에 없으면 생성해 해당 섹션 최상단에, 있으면 최상단으로 이동."""
    notes = []
    breaking = [a for a in articles if BREAKING_RE.search(a.get("title", ""))]
    breaking.sort(key=lambda a: (not bool(HARD_RE.search(a.get("title", ""))), -len(str(a.get("pub_date") or a.get("published") or "")) and 0,
                                 str(a.get("pub_date") or a.get("published") or "")), reverse=False)
    hard = [a for a in breaking if HARD_RE.search(a.get("title", ""))]
    soft = [a for a in breaking if not HARD_RE.search(a.get("title", ""))]
    hard.sort(key=lambda a: str(a.get("pub_date") or a.get("published") or ""), reverse=True)
    soft.sort(key=lambda a: str(a.get("pub_date") or a.get("published") or ""), reverse=True)
    breaking = hard + soft
    for a in breaking[:top_n]:
        title = a.get("title", "")
        m = BREAKING_RE.search(title)
        hm = HARD_RE.search(title)
        section = BREAKING_SECTION.get(hm.group(1)) if hm else None
        secs = parse_sections(briefing)
        # 이미 반영됐는지: 어느 섹션이든 제목 토큰 3개 이상 겹치는 항목
        hit = None
        for k, sec in secs.items():
            for idx, body in sec["items"]:
                if _overlap(title, body) >= 3:
                    hit = (k, idx, body)
                    break
            if hit:
                break
        lines = briefing.split("\n")
        if hit:
            k, idx, body = hit
            if section and k == section and sec_first(secs[k]) != idx or (not section and False):
                lines.pop(idx)
                _insert(lines, parse_sections("\n".join(lines))[k], [body], top=True)
                notes.append(f"속보 상단 이동: {body[:40]}")
                briefing = "\n".join(lines)
            continue
        if not section or section not in secs:
            continue
        gen = _gen_items(section, [a], 1, client, model)
        if gen:
            _insert(lines, secs[section], gen, top=True)
            notes.append(f"속보 생성·상단 배치({section}): {gen[0][:40]}")
            briefing = "\n".join(lines)
        else:
            notes.append(f"속보 미반영(생성 실패): {title[:40]}")
    if notes:
        logger.warning(f"[속보] {notes}")
    return briefing, notes


def sec_first(sec: dict) -> int | None:
    return sec["items"][0][0] if sec["items"] else None


def enforce_rebuttal(briefing: str, articles: list[dict], client=None, model: str = "claude-haiku-4-5-20251001") -> tuple[str, list[str]]:
    """🟦/🟥 한쪽에만 실린 쟁점의 상대 당 반박 기사가 풀에 있으면 상대 섹션에 1건 추가."""
    notes = []
    secs = parse_sections(briefing)
    pair = {"더불어민주당": "국민의힘", "국민의힘": "더불어민주당"}
    for party, other in pair.items():
        if party not in secs or other not in secs:
            continue
        other_bodies = [b for _, b in secs[other]["items"]]
        for _, body in secs[party]["items"]:
            topic_text = " ".join(t for t in _toks(body) if t not in PARTY_WORDS[party])
            if any(_overlap(topic_text, ob) >= 2 for ob in other_bodies):
                continue                                          # 상대 섹션에 같은 쟁점 이미 있음
            cands = [a for a in articles
                     if _overlap(topic_text, a.get("title", "")) >= 2
                     and any(w in f"{a.get('title', '')} {a.get('description', '')}" for w in PARTY_WORDS[other])
                     and re.search(r"(반박|반발|맞서|역공|비판|공세|규탄|해명|입장)", f"{a.get('title', '')} {a.get('description', '')}")]
            if not cands:
                continue
            gen = _gen_items(other, cands[:3], 1, client, model)
            if gen:
                lines = briefing.split("\n")
                _insert(lines, parse_sections(briefing)[other], gen)
                briefing = "\n".join(lines)
                notes.append(f"반박 보강({other}): {gen[0][:40]} ← 쟁점 '{body[:25]}'")
                secs = parse_sections(briefing)
                break
    if notes:
        logger.warning(f"[균형] {notes}")
    return briefing, notes


def source_match_guard(briefing: str, articles: list[dict], min_overlap: int = 2) -> tuple[str, list[str]]:
    """수집 기사 풀과 제목 토큰 min_overlap 이상 겹치지 않는 ▪ 항목 삭제 (출처 불명)."""
    lines = briefing.split("\n")
    dropped = []
    titles = [f"{a.get('title', '')} {(a.get('description') or '')[:80]}" for a in articles]
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("▪") or s == NO_NEWS:
            continue
        body = s.lstrip("▪").strip()
        if not any(_overlap(body, t) >= min_overlap for t in titles):
            lines[i] = None
            dropped.append(body[:60])
    if dropped:
        logger.warning(f"[출처매칭] 삭제 {len(dropped)}: {dropped}")
    return "\n".join(l for l in lines if l is not None), dropped


def cap_sections(briefing: str, max_items: int = MAX_ITEMS) -> tuple[str, list[str]]:
    secs = parse_sections(briefing)
    lines = briefing.split("\n")
    notes = []
    for k, sec in secs.items():
        extra = sec["items"][max_items:]
        for idx, body in extra:
            lines[idx] = None
            notes.append(f"{k} 초과 삭제: {body[:40]}")
    return "\n".join(l for l in lines if l is not None), notes


def section_counts(briefing: str) -> dict[str, int]:
    return {k: len([b for _, b in v["items"] if b != NO_NEWS.lstrip("▪ ").strip()]) for k, v in parse_sections(briefing).items()}


def mark_empty_sections(briefing: str) -> tuple[str, list[str]]:
    """항목이 0건인 섹션에 '금일 주요 보도 없음' 삽입 (LLM 호출 없음).

    출처 결속 게이트가 항목을 떨어뜨린 뒤 헤더만 남는 것을 막는다.
    근거 없는 항목을 채워 넣는 것보다 빈 섹션 표기가 낫다 (2026-10-21).
    """
    notes = []
    for _ in range(len(SECTIONS) + 1):
        secs = parse_sections(briefing)
        target = next((k for k in SECTIONS if k in secs and not secs[k]["items"]), None)
        if target is None:
            break
        lines = briefing.split("\n")
        lines.insert(secs[target]["header_idx"] + 1, NO_NEWS)
        briefing = "\n".join(lines)
        notes.append(f"보도없음:{target}(결속 후 0건)")
    if notes:
        logger.warning(f"[빈섹션] {notes}")
    return briefing, notes
