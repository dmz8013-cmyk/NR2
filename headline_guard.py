"""headline_guard.py — 정치 브리핑 한줄 제목(2번째 줄)의 정파 프레임 어휘 귀속.

'참사·굴종·독재·방탄·폭주·종북·학살' 등(config/facts.json frame_words)이 따옴표·발화 주체 없이 쓰이면
발화 주체를 붙여 재생성("국힘 정점식 '3대 참사' 공세"). 2회 실패 시 해당 어휘를 제목에서 삭제."""
import os
import re
import json
import logging

logger = logging.getLogger("headline_guard")
_HERE = os.path.dirname(os.path.abspath(__file__))
FACTS_JSON_PATH = os.path.join(_HERE, "config", "facts.json")
DEFAULT_FRAME_WORDS = ["참사", "굴종", "독재", "방탄", "폭주", "종북", "학살", "내란", "친일", "매국", "탄압", "쿠데타", "역적"]
SPEAKER_RE = re.compile(r"(국힘|국민의힘|민주당|민주|혁신당|개혁신당|진보당|여당|야당|여권|야권|與|野|정부|청와대|대통령|"
                        r"[가-힣]{3}\s*(?:의원|대표|원내대표|대변인|장관|지사|시장))")
QUOTE_PAIRS = [("'", "'"), ("‘", "’"), ('"', '"'), ("“", "”"), ("「", "」"), ("『", "』")]


def load_frame_words() -> list[str]:
    try:
        with open(FACTS_JSON_PATH, encoding="utf-8") as f:
            words = json.load(f).get("frame_words")
        return list(words) if words else list(DEFAULT_FRAME_WORDS)
    except Exception:
        return list(DEFAULT_FRAME_WORDS)


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    for o, c in QUOTE_PAIRS:
        i = 0
        while True:
            a = text.find(o, i)
            if a == -1:
                break
            b = text.find(c, a + 1)
            if b == -1:
                break
            spans.append((a, b))
            i = b + 1
    return spans


def unattributed_frames(headline: str, frame_words: list[str] | None = None) -> list[str]:
    """따옴표 안 + 발화 주체 동반이면 귀속된 것으로 본다. 그 외 프레임 어휘 목록."""
    words = frame_words or load_frame_words()
    spans = _quoted_spans(headline)
    has_speaker = bool(SPEAKER_RE.search(headline))
    out = []
    for w in words:
        for m in re.finditer(re.escape(w), headline):
            inside = any(a < m.start() < b for a, b in spans)
            if not (inside and has_speaker):
                out.append(w)
                break
    return out


def strip_frames(headline: str, words: list[str]) -> str:
    """프레임 어휘(따옴표·뒤따르는 조사 포함) 삭제 후 구두점·공백 정리."""
    h = headline
    for w in words:
        h = re.sub(rf"\s*['‘\"“「]?{re.escape(w)}['’\"”」]?(?:에|의|을|를|은|는|이|가|로|과|와|도)?", " ", h)
    h = re.sub(r"\s*([·…,])\s*", r"\1", h)          # 구두점 앞뒤 공백 제거
    h = re.sub(r"[·…]{2,}", "…", h)
    h = re.sub(r"\s{2,}", " ", h).strip(" ·…,")
    return h


REGEN_PROMPT = """아래 정치 브리핑 한줄 제목에 정파 프레임 어휘 [{words}] 가 발화 주체 없이 쓰였다.
브리핑 본문에서 그 표현을 쓴 주체(정당·인물)를 찾아, 어휘를 작은따옴표로 묶고 주체를 앞에 붙여 다시 써라.
형식 예: 국힘 정점식 '3대 참사' 공세 … / 민주 "방탄" 역공…
본문에서 주체를 찾을 수 없으면 그 어휘를 빼고 중립적으로 다시 써라. 새 사실 추가 금지, 25자 내외 1줄.

[현재 제목] {headline}
[브리핑 본문]
{body}

제목 1줄만 출력 (설명·따옴표 외 기호 금지)."""


def fix_headline(headline: str, body: str, client=None, model: str = "claude-haiku-4-5-20251001",
                 frame_words: list[str] | None = None, max_attempts: int = 2) -> tuple[str, dict]:
    """→ (제목, {attempts, stripped, words}). client 없으면 재생성 없이 어휘 삭제."""
    words = frame_words or load_frame_words()
    bad = unattributed_frames(headline, words)
    info = {"attempts": 0, "stripped": False, "words": bad, "original": headline}
    if not bad:
        return headline, info
    cur = headline
    if client is not None:
        for attempt in range(1, max_attempts + 1):
            info["attempts"] = attempt
            try:
                resp = client.messages.create(
                    model=model, max_tokens=120,
                    messages=[{"role": "user", "content": REGEN_PROMPT.format(
                        words=", ".join(bad), headline=cur, body=body[:3000])}])
                cand = (resp.content[0].text or "").strip().split("\n")[0].strip().strip('"')
            except Exception as e:
                logger.warning(f"[제목귀속] 재생성 호출 실패({attempt}): {e}")
                continue
            if cand and not unattributed_frames(cand, words):
                logger.info(f"[제목귀속] 재생성 성공({attempt}): {headline} → {cand}")
                return cand, info
            cur = cand or cur
    stripped = strip_frames(headline, bad)
    info["stripped"] = True
    logger.warning(f"[제목귀속] 재생성 실패 → 어휘 삭제: {headline} → {stripped}")
    return stripped or headline, info


def apply_to_briefing(briefing: str, client=None) -> tuple[str, dict]:
    """🔥 고정 첫 줄 다음의 첫 비어있지 않은 줄을 한줄 제목으로 보고 귀속 처리."""
    lines = briefing.split("\n")
    idx = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("🔥"):
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j].strip():
                    idx = j
                    break
            break
    if idx is None:
        return briefing, {"attempts": 0, "stripped": False, "words": []}
    new, info = fix_headline(lines[idx].strip(), briefing, client)
    if new != lines[idx].strip():
        lines[idx] = new
    return "\n".join(lines), info


BREAK_PROMPT = """정치 브리핑 한줄 제목을 다시 써라. 아래 최상위 속보가 제목에 반영돼야 한다(사실 위주, 25자 내외 1줄, 프레임 어휘·큰따옴표 금지).
[현재 제목] {headline}
[최상위 속보 기사] {breaking}
제목 1줄만 출력."""


def ensure_breaking_in_headline(briefing: str, breaking_titles: list[str], client=None,
                                model: str = "claude-haiku-4-5-20251001") -> tuple[str, str]:
    """최상위 속보 기사 제목의 핵심 토큰(2개 이상)이 한줄 제목에 없으면 재생성. → (텍스트, 보고 줄 또는 빈 문자열)."""
    if not breaking_titles:
        return briefing, ""
    lines = briefing.split("\n")
    idx = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("🔥"):
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j].strip():
                    idx = j
                    break
            break
    if idx is None:
        return briefing, ""
    head = lines[idx].strip()
    top = breaking_titles[0]
    key = {t for t in re.findall(r"[0-9A-Za-z가-힣]{2,}", top) if t in ("북한", "미사일", "합참", "탄핵", "계엄")}
    if "北" in top or "북한" in top:
        key |= {"북한", "北"}
    if not key or any(k in head for k in key):
        return briefing, ""
    if client is None:
        return briefing, f"속보 미반영(제목 유지): {head[:30]}"
    try:
        resp = client.messages.create(model=model, max_tokens=120, messages=[{"role": "user", "content": BREAK_PROMPT.format(headline=head, breaking=top)}])
        cand = (resp.content[0].text or "").strip().split("\n")[0].strip().strip('"')
        if cand and any(k in cand for k in key) and not unattributed_frames(cand):
            lines[idx] = cand
            return "\n".join(lines), f"속보 반영 재생성: {head[:30]} → {cand[:40]}"
    except Exception as e:
        logger.warning(f"[제목속보] 재생성 실패: {e}")
    return briefing, f"속보 미반영(재생성 실패): {head[:30]}"
