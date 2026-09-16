"""fixed_facts.py — 카드뉴스 고정값 사전 대조 (config/fixed_facts.json).

카드 텍스트(제목·부제·요점·설명)를 고정값 사전과 대조해 위반 목록을 돌려준다.
위반이 있으면 카드뉴스 초안은 '발행 보류' — /card_ok 가 거부하고 /card_ok force 로만
강행할 수 있다. 같은 사전은 카드 생성 프롬프트에도 주입해 생성 단계에서 먼저 막는다.

규칙 2종:
  forbidden : 정규식 목록 — 하나라도 매치하면 위반 (틀린 소속·직함 표기)
  numeric   : patterns 의 캡처 그룹 값이 expect 와 다르면 위반 (교섭단체 석수, 금리)
설정 로드 실패 시 빈 규칙(검사 통과) — 어떤 실패도 파이프라인을 멈추지 않는다.
"""
import os
import re
import json
import logging

logger = logging.getLogger(__name__)

_HERE = os.path.dirname(os.path.abspath(__file__))
FIXED_FACTS_PATH = os.path.join(_HERE, "config", "fixed_facts.json")


def load_fixed_facts() -> list[dict]:
    try:
        with open(FIXED_FACTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return [r for r in data.get("facts", []) if r.get("id")]
    except Exception as e:
        logger.warning(f"[고정값] fixed_facts.json 로드 실패 — 검사 생략: {e}")
        return []


def _norm_num(s: str) -> str:
    try:
        return f"{float(s.replace(',', '')):.2f}"
    except ValueError:
        return s.strip()


def _snippet(text: str, start: int, end: int, pad: int = 18) -> str:
    return text[max(0, start - pad):min(len(text), end + pad)].replace("\n", " ")


def check_text(text: str, facts: list[dict] | None = None) -> list[dict]:
    """텍스트 → 위반 목록 [{id, fact, found, snippet}]. 위반 없으면 []."""
    text = text or ""
    out: list[dict] = []
    for rule in (facts if facts is not None else load_fixed_facts()):
        try:
            for pat in rule.get("forbidden") or []:
                m = re.search(pat, text)
                if m:
                    out.append({"id": rule["id"], "fact": rule.get("fact", ""),
                                "found": m.group(0), "snippet": _snippet(text, m.start(), m.end())})
                    break
            num = rule.get("numeric") or {}
            expect = [_norm_num(x) for x in num.get("expect", [])]
            for pat in num.get("patterns") or []:
                hit = None
                for m in re.finditer(pat, text):
                    got = [_norm_num(g) for g in m.groups() if g is not None]
                    if got and got != expect[:len(got)]:
                        hit = m
                        break
                if hit:
                    out.append({"id": rule["id"], "fact": rule.get("fact", ""),
                                "found": hit.group(0), "snippet": _snippet(text, hit.start(), hit.end())})
                    break
        except re.error as re_err:
            logger.warning(f"[고정값] 규칙 {rule.get('id')} 정규식 오류 — 건너뜀: {re_err}")
    return out


def fixed_facts_context() -> str:
    """프롬프트 주입용 '[고정값 사전]' 블록. 규칙 없으면 빈 문자열."""
    facts = load_fixed_facts()
    if not facts:
        return ""
    lines = [f"- {r['fact']}" for r in facts if r.get("fact")]
    return ("[고정값 사전 — 아래와 충돌하는 수치·직함·소속은 절대 쓰지 말 것. "
            "브리핑 원문이 달라도 이 사전이 우선]\n" + "\n".join(lines))


def format_violations(violations: list[dict]) -> str:
    if not violations:
        return "✅ 고정값 사전 대조 통과"
    lines = [f"🚫 고정값 불일치 {len(violations)}건 — 발행 보류"]
    for v in violations:
        lines.append(f"• [{v['id']}] '{v['found']}' ← {v['fact']}")
        lines.append(f"  문맥: …{v['snippet']}…")
    return "\n".join(lines)
