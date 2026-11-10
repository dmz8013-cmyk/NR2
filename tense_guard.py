"""tense_guard.py — 기사 단계 → 항목 술어 승격 차단 (2026-10-30).

기사가 '출국·개막 예정' 단계인데 항목이 '메달 획득'처럼 결과 술어로 올라가는 유형
(10/29 청소년올림픽). 결속 기사의 제목+리드에서 단계를 읽고, 항목 술어가 그보다
앞선 결과를 주장하면 같은 단계로 끌어내린다. 치환 실패 시 항목 삭제.

설정: config/tense_guard.json. 로드 실패 시 아무것도 하지 않는다(발행 우선).
"""
import os
import re
import json
import logging

logger = logging.getLogger("tense_guard")
_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_HERE, "config", "tense_guard.json")
_CACHE = None


def load_config() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                _CACHE = json.load(f)
        except Exception as e:
            logger.warning(f"[시제가드] 설정 로드 실패 — 비활성: {e}")
            _CACHE = {"stages": [], "demote": {}}
    return _CACHE


def article_is_future(src_text: str) -> str | None:
    """기사 텍스트가 '예정' 단계면 그 단계명, 아니면 None."""
    for st in load_config()["stages"]:
        if any(m in (src_text or "") for m in st["article_markers"]):
            return st["stage"]
    return None


def _demote_completion(body: str, src_text: str, cfg: dict) -> tuple[str, str | None]:
    """'개최·주최·진행·열려·의결·발의' 완료형은 기사에 과거형이 있을 때만 허용 (2026-11-10).

    기사가 '개최한다'면 banned_predicates 의 '기사에도 있으면 승격 아님' 예외에 걸려
    통과했다(이주영 토론회). 그래서 동사 원형이 아니라 **과거형**의 존재로 판정한다."""
    comp = cfg.get("completion") or {}
    src = src_text or ""
    future = "|".join(map(re.escape, comp.get("future_words", ["예정"])))
    past_forms = comp.get("past_forms") or {}
    demote_to = comp.get("demote_to") or {}
    clause_end = set(comp.get("clause_end_only") or [])
    for verb in comp.get("verbs", []):
        if verb not in body:
            continue
        if any(verb + suf in src for suf in comp.get("past_suffixes", [])) or \
           any(f in src for f in past_forms.get(verb, [])):
            continue                           # 기사에 과거형 서술 → 완료형 허용
        # 동사 뒤가 절 끝이어야 한다 — '공동주최로', '진행자', '열려 의료계…' 같은 활용·연결형은 건드리지 않는다
        end = r"(?=$|[…·,.;:!?)\]}])" if verb in clause_end else r"(?=$|[\s…·,.;:!?)\]}{])"
        pat = re.compile(re.escape(verb) + r"(?!\s*(?:" + future + r"))(?:했음|됐음|함|됨)?" + end)
        if not pat.search(body):
            continue
        rep = demote_to.get(verb, verb + " 예정")
        new = pat.sub(rep, body)
        return new, f"완료형 '{verb}' → '{rep}' (기사에 과거형 없음)"
    return body, None


def check(body: str, src_text: str) -> tuple[str, str | None]:
    """→ (교정문, 메모). 승격 없으면 (원문, None), 치환 불가면 ("", 사유)."""
    cfg = load_config()
    if not article_is_future(src_text):
        return body, None
    new, note = _demote_completion(body, src_text, cfg)
    if note:
        return new, note
    for st in cfg["stages"]:
        for bad in st["banned_predicates"]:
            if bad not in body or bad in (src_text or ""):
                continue                       # 기사에도 있으면 승격이 아니다
            rep = cfg["demote"].get(bad)
            if not rep:
                return "", f"미래시제 승격 '{bad}' — 치환어 없음, 삭제"
            new = body.replace(bad, rep)
            # '통과함' → '통과 예정함' 처럼 어미가 깨지는 것 정리
            new = re.sub(r"(예정|추진|도전|중)\s*(함|됨|했음|하였음|임|이다)\b", r"\1", new)
            new = re.sub(r"\s{2,}", " ", new).strip()
            if len(new) < 10:
                return "", f"미래시제 승격 '{bad}' — 치환 후 과소, 삭제"
            return new, f"미래시제 '{bad}' → '{rep}' (기사 단계: {st['stage']})"
    return body, None


def apply(briefing: str, bound: dict) -> tuple[str, list[str]]:
    """bound: {줄번호: 기사텍스트}. → (텍스트, 메모 목록)."""
    lines = briefing.split("\n")
    notes = []
    for i, src_text in (bound or {}).items():
        if i >= len(lines) or not lines[i] or not lines[i].strip().startswith("▪"):
            continue
        body = lines[i].strip().lstrip("▪").strip()
        new, note = check(body, src_text)
        if note is None:
            continue
        if new == "":
            lines[i] = None
            notes.append(f"삭제: {body[:40]} ({note})")
        else:
            lines[i] = "▪ " + new
            notes.append(f"{note}: {body[:34]}…")
    if notes:
        logger.warning(f"[시제가드] {len(notes)}건: {notes[:3]}")
    return "\n".join(l for l in lines if l is not None), notes
