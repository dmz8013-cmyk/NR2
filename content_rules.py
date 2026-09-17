"""content_rules.py — 카드 문구 렌더 전 콘텐츠 규칙 검증.

여론조사·지지율 수치를 다루는 카드는 조사기관·조사방식·조사기간을 병기해야 한다
(선거여론조사 공표 기준). 하나라도 빠지면 '발행 보류' 플래그 — /card_ok 거부, force 로만 강행.
카드 한 장의 전체 텍스트(제목+부제+요점+설명/캡션)를 합쳐 판정한다.
"""
import re

POLL_TRIGGER_RE = re.compile(r"(지지율|여론조사|지지도|선호도|긍정\s*평가|부정\s*평가|국정\s*(?:수행\s*)?평가)")
PERCENT_RE = re.compile(r"\d{1,2}(?:\.\d)?\s*%")
AGENCY_RE = re.compile(
    r"(리얼미터|한국갤럽|갤럽|NBS|전국지표조사|KSOI|한국사회여론연구소|조원씨앤아이|에이스리서치|"
    r"한길리서치|미디어토마토|여론조사\s*꽃|여론조사꽃|메타보이스|엠브레인|입소스|케이스탯|코리아리서치|"
    r"한국리서치|피플네트웍스|알앤써치|리서치뷰|리서치앤리서치|모노리서치|폴리컴|글로벌리서치|퓨리서치|"
    r"[가-힣A-Za-z]+(?:리서치|여론연구소|조사연구소)|[가-힣A-Za-z]{2,}\s*(?:조사|의뢰)\s*(?:결과|에서|,))")
METHOD_RE = re.compile(r"(ARS|자동응답|전화\s*면접|전화면접|면접조사|무선\s*전화|유무선|무선\s*\d|온라인\s*조사|웹\s*조사|"
                       r"패널\s*조사|응답률|표본오차|신뢰수준|\d{3,5}\s*명\s*(?:대상|응답|조사))")
PERIOD_RE = re.compile(r"(\d{1,2}\s*[~∼～-]\s*\d{1,2}\s*일|\d{1,2}\s*월\s*\d{1,2}\s*일|\d{1,2}일\s*(?:간|부터|하루)|"
                       r"(?:지난|이번)\s*주|주간|\d{1,2}일\s*조사|사흘|이틀|양일)")


def check_poll_disclosure(text: str) -> list[dict]:
    """여론조사 수치 카드 → 기관·방식·기간 병기 여부. 위반 시 [{id, fact, found, snippet}]."""
    text = text or ""
    if not (POLL_TRIGGER_RE.search(text) and PERCENT_RE.search(text)):
        return []
    missing = []
    if not AGENCY_RE.search(text):
        missing.append("조사기관")
    if not METHOD_RE.search(text):
        missing.append("조사방식")
    if not PERIOD_RE.search(text):
        missing.append("조사기간")
    if not missing:
        return []
    m = POLL_TRIGGER_RE.search(text)
    snip = text[max(0, m.start() - 20):m.end() + 40].replace("\n", " ")
    return [{"id": "여론조사_병기", "fact": "지지율·여론조사 수치 카드는 조사기관·조사방식·조사기간 병기 필수",
             "found": "누락: " + "·".join(missing), "snippet": snip}]


def check_issue(issue: dict) -> list[dict]:
    """카드 1장(구조 필드) → 콘텐츠 규칙 위반 목록."""
    text = "\n".join([issue.get("title") or "", issue.get("subtitle") or "",
                      *[b for b in (issue.get("bullets") or [])], issue.get("desc") or ""])
    return check_poll_disclosure(text)
