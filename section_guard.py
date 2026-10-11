"""section_guard.py — 당적 사전 기반 섹션 배치 검증 (정치 브리핑 13/22).

각 ▪ 항목의 '첫 실명 주체'를 사전(config/facts.json 인물_직함 + fact_sheet.json key_figures)의 당적과 대조한다.
  더불어민주당 → 🟦 / 국민의힘 → 🟥 / 조국혁신당·개혁신당·진보당·기본소득당·새로운미래·무소속 → 🎸
당적 판정은 '정당 소속 정치인 직함'(의원·대표·원내대표·대변인·지사·시장·구청장 등)에만 적용하고,
정부 직책(대통령·장관·총리·수석·청장·판사·검사 등)은 건드리지 않는다. 섹션이 다르면 해당 섹션 끝으로
이동, 대상 섹션이 없으면 삭제. 실패 시 원문 반환."""
import os
import re
import json
import logging

logger = logging.getLogger("section_guard")
_HERE = os.path.dirname(os.path.abspath(__file__))
FACTS_JSON_PATH = os.path.join(_HERE, "config", "facts.json")
FACT_SHEET_PATH = os.path.join(_HERE, "fact_sheet.json")

SECTION_OF_PARTY = {"민주": "더불어민주당", "국힘": "국민의힘", "기타": "비교섭단체"}
SECTION_EMOJI = {"더불어민주당": "🟦", "국민의힘": "🟥", "비교섭단체": "🎸"}
MINOR_PARTIES = ("조국혁신당", "개혁신당", "진보당", "기본소득당", "새로운미래", "사회민주당", "무소속")
POLITICIAN_TITLES = ("의원", "대표", "원내대표", "최고위원", "대변인", "정책위의장", "사무총장", "지사", "시장", "구청장",
                     "군수", "교육감", "당대표", "비대위원장", "원내대변인", "시의원", "도의원")
GOV_TITLES = ("대통령", "총리", "장관", "차관", "수석", "비서관", "실장", "청장", "판사", "검사", "대법원장", "대법관",
              "헌법재판관", "총재", "위원장", "원장", "이사장", "직무대행", "후보자", "대사", "사령관")


def _head(title: str) -> str:
    return re.split(r"\s[—(\[]|\s/\s", title or "", maxsplit=1)[0]


def party_of_title(title: str) -> str | None:
    h = _head(title)
    if "무소속" in h:
        return "기타"
    if "더불어민주당" in h or "민주당" in h:
        return "민주"
    if "국민의힘" in h:
        return "국힘"
    if any(p in h for p in MINOR_PARTIES):
        return "기타"
    return None


def is_party_politician(title: str) -> bool:
    h = _head(title)
    if any(g in h for g in GOV_TITLES) and not any(p in h for p in POLITICIAN_TITLES if p not in ("위원장",)):
        return False
    return any(p in h for p in POLITICIAN_TITLES)


def load_party_map() -> dict[str, str]:
    """이름 → 기대 섹션명('더불어민주당'|'국민의힘'|'비교섭단체'). 사전 두 곳 합집합(facts.json 우선)."""
    out: dict[str, str] = {}
    try:
        with open(FACT_SHEET_PATH, encoding="utf-8") as f:
            for fig in json.load(f).get("key_figures", []):
                p = party_of_title(fig.get("correct_title", ""))
                if p and is_party_politician(fig.get("correct_title", "")):
                    out[fig["name"]] = SECTION_OF_PARTY[p]
    except Exception as e:
        logger.warning(f"[섹션검증] fact_sheet 로드 실패: {e}")
    try:
        with open(FACTS_JSON_PATH, encoding="utf-8") as f:
            for name, title in (json.load(f).get("인물_직함") or {}).items():
                p = party_of_title(title)
                if p and is_party_politician(title):
                    out[name] = SECTION_OF_PARTY[p]
    except Exception as e:
        logger.warning(f"[섹션검증] facts.json 로드 실패: {e}")
    return out


def first_subject(text: str, party_map: dict[str, str]) -> str | None:
    best, pos = None, 10 ** 9
    for name in party_map:
        i = text.find(name)
        if i != -1 and i < pos:
            best, pos = name, i
    return best


def _section_key(header_line: str) -> str | None:
    s = header_line.strip()
    for key in ("더불어민주당", "국민의힘", "비교섭단체", "이재명 정부", "법조"):
        if key in s:
            return key
    return None


def enforce_sections(briefing: str, party_map: dict[str, str] | None = None) -> tuple[str, list[str], list[str]]:
    """→ (텍스트, 이동 목록, 삭제 목록). 정치 브리핑 섹션(🟦/🟥/🎸)이 없으면 원문 그대로."""
    try:
        from briefing_layout import SECTION_HEADER_RE
    except Exception:
        SECTION_HEADER_RE = re.compile(r'^(🏛️|💰|🤖|🎯|📌|🇰🇷|🟦|🟥|🎸|🌐)')
    pm = party_map if party_map is not None else load_party_map()
    lines = briefing.split("\n")
    headers = {}
    cur = None
    item_sections: list[tuple[int, str, str]] = []   # (line_no, section_key, body)
    for i, ln in enumerate(lines):
        s = ln.strip()
        if SECTION_HEADER_RE.match(s):
            cur = _section_key(s)
            if cur:
                headers[cur] = i
            continue
        if s.startswith("▪") and cur:
            item_sections.append((i, cur, s.lstrip("▪").strip()))
    if not any(k in headers for k in ("더불어민주당", "국민의힘", "비교섭단체")):
        return briefing, [], []
    moved, dropped = [], []
    to_move: list[tuple[int, str, str]] = []
    for i, sec, body in item_sections:
        name = first_subject(body, pm)
        if not name:
            continue
        expected = pm[name]
        if expected == sec:
            continue
        to_move.append((i, expected, body))
    if not to_move:
        return briefing, [], []
    # 제거 후 삽입 (줄 번호 변동 방지: 먼저 None 처리)
    for i, expected, body in to_move:
        lines[i] = None
    text = "\n".join(l for l in lines if l is not None)
    from recheck_queue import insert_into_section
    for i, expected, body in to_move:
        if expected in headers:
            text = insert_into_section(text, expected, body)
            moved.append(f"{body[:50]} → {SECTION_EMOJI.get(expected, '')} {expected}")
        else:
            dropped.append(f"{body[:50]} (대상 섹션 {expected} 없음)")
    if moved or dropped:
        logger.warning(f"[섹션검증] 이동 {len(moved)} · 삭제 {len(dropped)}: {moved + dropped}")
    return text, moved, dropped
