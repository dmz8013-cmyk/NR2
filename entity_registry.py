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
    "직함": {}, "직함_토큰": [], "지방직_직함": [], "단순일정_어휘": [], "여론조사_기관": [],
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


# ──────────────────────────────────────────────
#  직함 고정 (2026-10-21 결함3 — '장동혁 의원' 유형)
# ──────────────────────────────────────────────
def title_of(name: str) -> str | None:
    """등재 인물의 정확한 직함. 화이트리스트이므로 사전에 없는 직함은 전부 오류로 본다."""
    return load_registry()["직함"].get(name)


def enforce_titles(text: str) -> tuple[str, list[str]]:
    """'<이름> <직함>' 이 사전과 다르면 교정. → (교정문, 메모).

    fact_sheet 의 wrong_titles 는 블랙리스트라 미등재 오류('장동혁 의원')를 놓친다.
    여기서는 등재 인물 뒤에 오는 직함 토큰을 전부 사전값과 대조한다.
    '전/전직/former' 접두는 건드리지 않는다(과거 직함은 정상 표기).
    """
    reg = load_registry()
    titles, tokens = reg["직함"], sorted(reg["직함_토큰"], key=len, reverse=True)
    out, notes = text, []
    for name, correct in titles.items():
        if name not in out:
            continue
        for tok in tokens:
            pat = re.compile(re.escape(name) + r"\s*" + re.escape(tok))
            for m in list(pat.finditer(out)):
                prefix = out[max(0, m.start() - 4):m.start()]
                if re.search(r"(전|전직|신임|차기)\s*$", prefix):
                    continue
                found = m.group(0)
                # 사전 직함의 '마지막 토큰'과 비교한다. endswith 로 보면
                # '국민의힘 원내대표'가 '대표'를 포함해 '정점식 대표'를 통과시킨다.
                if correct.split()[-1] == tok:
                    break                                  # 이미 올바른 직함(수식어 생략형 허용)
                fixed = f"{name} {correct}"
                tail = _fix_particle(correct, out[m.end():])
                out = out[:m.start()] + fixed + tail
                notes.append(f"{found} → {fixed}")
                break
    return out, notes


def _has_batchim(ch: str) -> bool:
    """한글 음절의 받침 유무 (조사 선택용)."""
    return bool(ch) and 0xAC00 <= ord(ch) <= 0xD7A3 and (ord(ch) - 0xAC00) % 28 != 0


_PARTICLE_PAIRS = (("이", "가"), ("은", "는"), ("을", "를"), ("과", "와"), ("으로", "로"))


def _fix_particle(new_word: str, tail: str) -> str:
    """교정된 직함 뒤의 조사를 받침에 맞게 바꾼다 ('대표이' → '대표가')."""
    if not tail or not new_word:
        return tail
    batchim = _has_batchim(new_word[-1])
    for with_b, without_b in _PARTICLE_PAIRS:
        want, other = (with_b, without_b) if batchim else (without_b, with_b)
        if tail.startswith(other) and (len(tail) == len(other) or not tail[len(other)].isalnum()):
            return want + tail[len(other):]
    return tail


# ──────────────────────────────────────────────
#  정치 브리핑 대상 기준 (2026-10-21 결함4)
# ──────────────────────────────────────────────
def is_local_routine(text: str) -> bool:
    """지방의원·기초단체장의 단순 일정 항목인가 — 중앙정치·국회·정부·법조 우선."""
    reg = load_registry()
    t = text or ""
    if not any(j in t for j in reg["지방직_직함"]):
        return False
    if not any(w in t for w in reg["단순일정_어휘"]):
        return False
    # 중앙정치 사안이 함께 걸려 있으면 남긴다
    central = ("국회", "본회의", "상임위", "국정감사", "국감", "대통령", "정부", "장관",
               "검찰", "법원", "특검", "당대표", "원내대표", "공천", "탄핵", "예산안")
    return not any(k in t for k in central)


# ──────────────────────────────────────────────
#  여론조사 조사기관 필수 (2026-10-21 결함3)
# ──────────────────────────────────────────────
POLL_RE = re.compile(r"(지지율|여론조사|지지도|선호도|긍정\s*평가|부정\s*평가|국정\s*(?:수행\s*)?평가)")
PCT_RE = re.compile(r"\d{1,2}(?:\.\d)?\s*%")


def poll_needs_agency(text: str) -> bool:
    """여론조사 수치를 담았는데 조사기관명이 없는 항목인가 → 폐기 대상."""
    t = text or ""
    if not (POLL_RE.search(t) and PCT_RE.search(t)):
        return False
    return not any(a in t for a in load_registry()["여론조사_기관"])


# ──────────────────────────────────────────────
#  항목 정책 게이트 (2026-10-21 결함3·4)
# ──────────────────────────────────────────────
NO_NEWS_BODY = "금일 주요 보도 없음"


def policy_gate(briefing: str) -> tuple[str, list[str]]:
    """사전 기반 항목 정책 일괄 적용. → (텍스트, 메모).

      · 직함 교정 — 등재 인물 뒤 직함을 사전값으로 (결함3 '장동혁 의원')
      · 지방의원 단순 일정 제외 — 중앙정치·국회·정부·법조 우선 (결함4)
      · 여론조사 수치에 조사기관 없으면 폐기 (결함3)

    LLM 생성 단계 뒤에 호출해야 생성 항목에도 적용된다.
    """
    lines = briefing.split("\n")
    notes: list[str] = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith("▪") or NO_NEWS_BODY in s:
            continue
        body = s.lstrip("▪").strip()
        if is_local_routine(body):
            lines[i] = None
            notes.append(f"지방 단순일정 제외: {body[:50]}")
            continue
        if poll_needs_agency(body):
            lines[i] = None
            notes.append(f"여론조사 조사기관 누락 폐기: {body[:50]}")
            continue
        fixed, tnotes = enforce_titles(body)
        if tnotes:
            lines[i] = "▪ " + fixed
            notes += [f"직함 교정: {n}" for n in tnotes]
    if notes:
        logger.warning(f"[정책게이트] {len(notes)}건: {notes[:5]}")
    return "\n".join(l for l in lines if l is not None), notes
