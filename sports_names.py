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
    for league in ("KBO", "KBL"):
        blk = teams.get(league) or {}
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
