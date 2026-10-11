"""sports_names.py — 스포츠 구단 정식 명칭 교정 (config/facts.json 스포츠_구단명).

생성 프롬프트에는 사전이 그대로 주입되지만(ai_briefing._facts_block), 모델이 약칭·오기('KCC 크루저',
'가스공사')를 쓰는 경우를 발송 전에 결정론적으로 정식 명칭으로 치환한다. 치환은 사전의 alias 목록만.
바로 쓰는 약칭(KCC·가스공사 등)은 같은 항목에 농구 맥락(프로농구·KBL·다른 구단명)이 있을 때만 치환."""
import os
import re
import json
import logging

logger = logging.getLogger("sports_names")
_HERE = os.path.dirname(os.path.abspath(__file__))
FACTS_JSON_PATH = os.path.join(_HERE, "config", "facts.json")


def load_teams() -> dict:
    try:
        with open(FACTS_JSON_PATH, encoding="utf-8") as f:
            return json.load(f).get("스포츠_구단명") or {}
    except Exception as e:
        logger.warning(f"[구단명] facts.json 로드 실패: {e}")
        return {}


def _apply(item: str, aliases: dict, bare: dict, context_words: list[str]) -> tuple[str, list[str]]:
    fixes = []
    for wrong, canon in sorted(aliases.items(), key=lambda kv: -len(kv[0])):
        if wrong in item and canon not in item:
            item = item.replace(wrong, canon)
            fixes.append(f"{wrong}→{canon}")
    ctx = any(w in item for w in context_words)
    if ctx:
        for wrong, canon in sorted(bare.items(), key=lambda kv: -len(kv[0])):
            # 정식 명칭의 일부로 이미 들어간 경우는 건너뜀
            pat = re.compile(rf"(?<![가-힣A-Za-z]){re.escape(wrong)}(?![A-Za-z])")   # 조사(가스공사를)는 허용
            if pat.search(item) and canon not in item:
                item = pat.sub(canon, item, count=1)
                # 같은 항목 내 반복은 짧은 표기 유지(가독성) — 첫 등장만 정식 명칭
                fixes.append(f"{wrong}→{canon}")
    return item, fixes


def fix_team_names(briefing: str) -> tuple[str, list[str]]:
    """▪ 항목 단위로 정식 명칭 치환. → (텍스트, ['항목 앞 20자: KCC 크루저→부산 KCC 이지스', ...])"""
    teams = load_teams()
    if not teams:
        return briefing, []
    aliases, bare, ctx = {}, {}, []
    for league, blk in teams.items():
        if not isinstance(blk, dict):
            continue
        aliases.update(blk.get("aliases") or {})
        bare.update(blk.get("bare_aliases") or {})
        ctx += blk.get("context_words") or []
        ctx += list((blk.get("teams") or {}).values())
    out, fixes = [], []
    for line in briefing.split("\n"):
        s = line.strip()
        if s.startswith("▪"):
            body = s.lstrip("▪").strip()
            new_body, fx = _apply(body, aliases, bare, ctx)
            if fx:
                fixes.append(f"{body[:20]}…: " + ", ".join(fx))
                line = line.replace(body, new_body)
        out.append(line)
    if fixes:
        logger.info(f"[구단명] 교정 {len(fixes)}항목: {fixes}")
    return "\n".join(out), fixes


# ── 스포츠 주체 충돌 (득점 선수 소속 = '무너진' 팀) ──
LOSE_RE = re.compile(r"(무너지|무너졌|패배|완패|역전패|졌|패했|고개를 숙)")
SCORE_RE = re.compile(r"([가-힣]{2,4})의\s*(만루포|만루 홈런|홈런|결승타|끝내기|결승골|골|안타|득점|3점포|투런)")


def load_players() -> dict[str, str]:
    """선수 → 정식 구단명 (facts.json 스포츠_구단명.*.players)."""
    out = {}
    for league, blk in (load_teams() or {}).items():
        if isinstance(blk, dict):
            out.update(blk.get("players") or {})
    return out


def _team_aliases() -> dict[str, str]:
    """구단 표기(정식·약칭·alias) → 정식명."""
    out = {}
    for league, blk in (load_teams() or {}).items():
        if not isinstance(blk, dict):
            continue
        for short, canon in (blk.get("teams") or {}).items():
            out[canon] = canon
            out[short] = canon
        for a, canon in (blk.get("aliases") or {}).items():
            out[a] = canon
    return out


def check_subject_conflicts(briefing: str, players: dict[str, str] | None = None) -> list[dict]:
    """'A가 … C의 홈런으로 무너지' 에서 C 소속이 A 면 충돌. → [{line_no, body, player, team}]."""
    players = players if players is not None else load_players()
    if not players:
        return []
    aliases = _team_aliases()
    out = []
    for i, ln in enumerate(briefing.split("\n")):
        s = ln.strip()
        if not s.startswith("▪"):
            continue
        body = s.lstrip("▪").strip()
        if not LOSE_RE.search(body):
            continue
        m = SCORE_RE.search(body)
        if not m or m.group(1) not in players:
            continue
        scorer_team = players[m.group(1)]
        # 문장 앞쪽(득점 선수 언급 이전)에 주어로 등장한 팀
        head = body[:m.start()]
        subj = None
        for alias, canon in sorted(aliases.items(), key=lambda kv: -len(kv[0])):
            mm = re.search(rf"{re.escape(alias)}(?:가|이|는|은)\s", head)
            if mm and (subj is None or mm.start() < subj[0]):
                subj = (mm.start(), canon)
        if subj and subj[1] == scorer_team:
            out.append({"line_no": i, "body": body, "player": m.group(1), "team": scorer_team})
    return out


REWRITE_SUBJECT_PROMPT = """다음 스포츠 항목은 주어 오류다: {player} 선수는 {team} 소속인데, 문장은 {team}이 {player}의 득점으로 '무너진' 것처럼 썼다.
사실관계(득점 선수 소속팀이 이긴 쪽)에 맞게 주어와 목적어를 바로잡아 1~2문장으로 다시 써라. 새 사실·수치 추가 금지, 통신사 톤 명사형 종결.
[항목] {body}
수정문 1개만 출력."""


def fix_subject_conflicts(briefing: str, client=None, model: str = "claude-haiku-4-5-20251001") -> tuple[str, list[str]]:
    """충돌 항목 재작성(haiku) — 재작성 후에도 충돌이거나 client 없으면 삭제. → (텍스트, 보고 줄)."""
    conflicts = check_subject_conflicts(briefing)
    if not conflicts:
        return briefing, []
    lines = briefing.split("\n")
    notes = []
    for c in conflicts:
        new = None
        if client is not None:
            try:
                resp = client.messages.create(model=model, max_tokens=300, messages=[{"role": "user", "content":
                    REWRITE_SUBJECT_PROMPT.format(player=c["player"], team=c["team"], body=c["body"])}])
                cand = (resp.content[0].text or "").strip().lstrip("▪").strip()
                if cand and not check_subject_conflicts("▪ " + cand):
                    new = cand
            except Exception as e:
                logger.warning(f"[스포츠주체] 재작성 실패: {e}")
        if new:
            lines[c["line_no"]] = "▪ " + new
            notes.append(f"{c['body'][:40]}… → 재작성({c['player']}={c['team']})")
        else:
            lines[c["line_no"]] = None
            notes.append(f"{c['body'][:40]}… → 삭제({c['player']}={c['team']}, 재작성 실패)")
    logger.warning(f"[스포츠주체] {notes}")
    return "\n".join(l for l in lines if l is not None), notes
