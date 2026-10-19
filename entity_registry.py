"""entity_registry.py — 주체 고정 사전 (config/entity_registry.json).

섹션 배치의 단일 기준: '기사에 나온 정당'이 아니라 '발언·행위 주체의 소속'.

  · 국회의원 당적은 레지스트리에서 고정 — facts.json 직함 문자열 추론보다 우선한다.
  · 공무원·검찰·법원 주체(공소청장·검사·판사 등)는 정당과 무관하게 법조 섹션으로 강제.
  · 국정감사 항목은 '질의한 의원'의 소속으로 분류하고, 피감기관의 답변·해명이
    주어인 항목은 법조(사법·수사기관) 또는 이재명 정부(행정부)로 보낸다.

어떤 로드 실패도 발행을 막지 않는다 — 판정 불가면 None 을 돌려 호출부가 원문을 유지한다.
"""
import os
import re
import json
import logging

logger = logging.getLogger("entity_registry")

_HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY_PATH = os.path.join(_HERE, "config", "entity_registry.json")

LEGAL_SECTION = "법조"
GOV_SECTION = "이재명 정부"
PARTY_SECTIONS = ("더불어민주당", "국민의힘", "비교섭단체")

_DEFAULTS = {
    "국회의원": {}, "법조_인물": {}, "법조_직책": [], "정부_직책": [],
    "피감기관_어휘": [], "국감_어휘": [], "외신_고유명사": {},
}
_CACHE: dict | None = None


def load_registry(refresh: bool = False) -> dict:
    global _CACHE
    if _CACHE is not None and not refresh:
        return _CACHE
    try:
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        _CACHE = {k: data.get(k, v) for k, v in _DEFAULTS.items()}
    except Exception as e:
        logger.warning(f"[주체사전] 로드 실패 — 빈 사전 사용: {e}")
        _CACHE = {k: (dict(v) if isinstance(v, dict) else list(v)) for k, v in _DEFAULTS.items()}
    return _CACHE


# ──────────────────────────────────────────────
#  주체 판정
# ──────────────────────────────────────────────
def mp_party(name: str) -> str | None:
    """국회의원 고정 당적 → 섹션명. 등재 안 된 이름은 None."""
    return load_registry()["국회의원"].get(name)


def is_legal_actor(name: str, text: str = "") -> bool:
    """법조 주체인가 — 레지스트리 등재 인물이거나, 이름 뒤에 법조 직책이 붙은 경우."""
    reg = load_registry()
    if name in reg["법조_인물"]:
        return True
    return bool(name) and _title_after(name, text, reg["법조_직책"])


def is_gov_actor(name: str, text: str = "") -> bool:
    reg = load_registry()
    return bool(name) and _title_after(name, text, reg["정부_직책"])


def _title_after(name: str, text: str, titles: list[str], window: int = 14) -> bool:
    """'<이름> … <직책>' 형태인지 — 이름 바로 뒤 window 자 안에 직책어가 있으면 참."""
    if not text or not name:
        return False
    for m in re.finditer(re.escape(name), text):
        tail = text[m.end():m.end() + window]
        if any(t in tail for t in titles):
            return True
    return False


def legal_title_in(text: str) -> str | None:
    """이름 없이 직책만 등장하는 경우(예: '공소청장이 …') 쓰는 보조 판정."""
    for t in sorted(load_registry()["법조_직책"], key=len, reverse=True):
        if t in (text or ""):
            return t
    return None


# ──────────────────────────────────────────────
#  국정감사 — 질의 의원 기준 / 피감기관 답변은 법조·정부
# ──────────────────────────────────────────────
def is_gamsa_item(text: str) -> bool:
    return any(w in (text or "") for w in load_registry()["국감_어휘"])


def is_agency_answer(text: str) -> bool:
    """피감기관 답변·해명이 주어인 항목인지 — 국감 항목에서만 의미가 있다."""
    return any(w in (text or "") for w in load_registry()["피감기관_어휘"])


def names_in(text: str) -> list[str]:
    """레지스트리에 등재된 이름을 등장 순서대로. (국회의원 + 법조 인물)"""
    reg = load_registry()
    known = list(reg["국회의원"]) + list(reg["법조_인물"])
    found = [(text.find(n), n) for n in known if text.find(n) != -1]
    return [n for _, n in sorted(found)]


def section_for_item(text: str) -> tuple[str | None, str]:
    """항목 1줄 → (기대 섹션, 판정 근거). 판정 불가면 (None, 사유).

    우선순위
      1) 국감 항목 — 질의 의원이 있으면 그 의원 소속, 없고 피감기관 답변이면 법조/정부
      2) 법조 주체(등재 인물·직책) → 법조
      3) 국회의원 고정 당적 → 해당 정당 섹션
      4) 정부 직책 주체 → 이재명 정부
    """
    text = text or ""
    names = names_in(text)
    reg = load_registry()

    if is_gamsa_item(text):
        for n in names:                                   # 질의 의원 우선
            p = mp_party(n)
            if p:
                return p, f"국감 질의 의원 {n}({p})"
        if is_agency_answer(text) or legal_title_in(text):
            for n in names:
                if is_legal_actor(n, text):
                    return LEGAL_SECTION, f"국감 피감기관 답변 — 법조 주체 {n}"
            if legal_title_in(text):
                return LEGAL_SECTION, f"국감 피감기관 답변 — 법조 직책 {legal_title_in(text)}"
            return GOV_SECTION, "국감 피감기관 답변 — 행정부"

    for n in names:
        if is_legal_actor(n, text):
            return LEGAL_SECTION, f"법조 주체 {n}"
    if not names:
        t = legal_title_in(text)
        if t:
            return LEGAL_SECTION, f"법조 직책 {t}"

    for n in names:
        p = mp_party(n)
        if p:
            return p, f"국회의원 {n}({p})"

    for n in names:
        if is_gov_actor(n, text):
            return GOV_SECTION, f"정부 직책 주체 {n}"

    return None, "판정 불가 — 원문 유지"


def foreign_names() -> dict[str, str]:
    """외신 고유명사 → 직함(원문 표기 유지용)."""
    return dict(load_registry()["외신_고유명사"])
