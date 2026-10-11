"""briefing_guards.py — 발송 전 결정론 가드 3종 (일반 브리핑, 2026-10-12).

C. 코인 상한: 섹션과 무관하게 비트코인·이더리움·암호화폐·청산·ETF 키워드 항목은 전체 1건, 💰 경제/산업으로 고정
D. 예측시장 문구: 확률·계약·폴리마켓·칼시 항목은 계약 방향(도달/하락…)이 소스 제목에 그대로 있어야 유지, 아니면 삭제
E. 스포츠 주체 충돌: sports_names.check_subject_conflicts 로 위임 (득점 선수 소속 = '무너진' 팀이면 재작성/삭제)
실패 시 원문 반환 — 어떤 가드도 발송을 막지 않는다."""
import re
import logging

logger = logging.getLogger("briefing_guards")

COIN_RE = re.compile(r"(비트코인|이더리움|암호화폐|가상자산|가상화폐|코인|스테이블코인|XRP|리플|솔라나|도지|알트코인|"
                     r"현물\s*ETF|레버리지\s*포지션|포지션\s*청산|청산이\s*발생)")
PREDICTION_RE = re.compile(r"(확률|계약|폴리마켓|Polymarket|칼시|Kalshi|예측시장|베팅)")
DIRECTION_RE = re.compile(r"(도달|돌파|상회|넘[어을]|이상|회복|상승|하락|하회|밑|이하|떨어|급락|급등)")
# 계약 방향: 금액·% 뒤 또는 '계약/확률/가능성' 앞의 방향어만 (부가 서술의 '상승' 등은 제외)
CONTRACT_DIR_RE = re.compile(r"(?:달러|원|%|선)\s*(도달|돌파|상회|이상|하락|하회|이하|밑|붕괴|회복)|(도달|하락|상승|돌파|회복|붕괴)\s*(?:계약|확률|가능성|베팅)")


def contract_directions(text: str) -> set[str]:
    dirs = {a or b for a, b in CONTRACT_DIR_RE.findall(text or "")}
    return dirs or set(DIRECTION_RE.findall(text or ""))


def _items(lines):
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("▪"):
            yield i, s.lstrip("▪").strip()


def _section_at(lines, idx):
    try:
        from briefing_layout import SECTION_HEADER_RE
    except Exception:
        SECTION_HEADER_RE = re.compile(r'^(🏛️|💰|🤖|🎯|📌|🇰🇷|🟦|🟥|🎸|🌐)')
    for j in range(idx, -1, -1):
        if SECTION_HEADER_RE.match(lines[j].strip()):
            return lines[j].strip()
    return ""


def enforce_coin_cap(briefing: str) -> tuple[str, list[str], list[str]]:
    """→ (텍스트, 삭제 목록, 이동 목록). 시세 줄(📈)은 대상 아님."""
    lines = briefing.split("\n")
    coin = [(i, b) for i, b in _items(lines) if COIN_RE.search(b)]
    if len(coin) == 0:
        return briefing, [], []
    econ = [(i, b) for i, b in coin if "💰" in _section_at(lines, i)]
    keep_i, keep_b = (econ[0] if econ else coin[0])
    dropped, moved = [], []
    for i, b in coin:
        if i != keep_i:
            lines[i] = None
            dropped.append(b[:60])
    if "💰" not in _section_at(lines, keep_i):
        lines[keep_i] = None
        text = "\n".join(l for l in lines if l is not None)
        from recheck_queue import insert_into_section
        text = insert_into_section(text, "경제/산업", keep_b)
        moved.append(keep_b[:60])
    else:
        text = "\n".join(l for l in lines if l is not None)
    if dropped or moved:
        logger.warning(f"[코인상한] 삭제 {len(dropped)} · 💰 이동 {len(moved)}")
    return text, dropped, moved


def _toks(t: str) -> set[str]:
    return {x for x in re.findall(r"[0-9A-Za-z가-힣]{2,}", t or "")}


def enforce_prediction_market(briefing: str, source_titles: list[str]) -> tuple[str, list[str]]:
    """예측시장 항목: 소스 제목(겹침 토큰 ≥2)에 항목의 방향어가 그대로 없으면 삭제. → (텍스트, 삭제 목록)."""
    lines = briefing.split("\n")
    dropped = []
    for i, b in list(_items(lines)):
        if not PREDICTION_RE.search(b):
            continue
        dirs = contract_directions(b)
        bt = _toks(b)
        best, best_n = None, 0
        for t in source_titles or []:
            n = len(bt & _toks(t))
            if n > best_n:
                best, best_n = t, n
        ok = bool(best) and best_n >= 2 and (not dirs or any(d in best for d in dirs)) \
             and not (dirs and contract_directions(best) and not (dirs & contract_directions(best)))
        if not ok:
            lines[i] = None
            dropped.append(f"{b[:60]} (소스 제목 방향 불일치: {best[:40] if best else '매칭 없음'})")
    if dropped:
        logger.warning(f"[예측시장] 삭제 {len(dropped)}: {dropped}")
    return "\n".join(l for l in lines if l is not None), dropped
