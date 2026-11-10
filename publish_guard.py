"""publish_guard.py — 브리핑 4슬롯 공통 발행 직전 관문 (2026-11-10).

06:00·18:00(ai_briefing.send_briefing) 과 13:00·22:00(political_briefing.send_political_briefing)
두 생성기가 **레이아웃 직전**, 즉 게이트 뒤의 LLM 문체 재작성·헤드라인 재생성까지 끝난
최종 문장에 이 모듈을 반드시 통과시킨다. 게이트(gate.enforce)는 문체 재작성 **앞**에서
돌기 때문에, 거기서 고친 시제가 style_fix 의 LLM 재작성으로 되돌아갈 수 있었다.

규칙은 두 곳에 있다.
  · PROMPT_RULES — 생성 프롬프트에 넣는 공통 규칙 문안(두 생성기가 같은 문자열을 쓴다)
  · final_pass   — 결정론 검사. 항목마다 수집 풀에서 근거 기사를 다시 찾아 대조한다.
      1) 24시간 발행일 — 근거 기사가 24h 초과면 삭제
      2) [날짜미상] — 근거 기사 발행시각이 없으면 삭제 + 날짜미상 큐 적재
      3) 시제 — tense_guard (완료형은 기사에 과거형이 있을 때만)
      4) 방송 프로그램명 — 시청률·예능 항목에 프로그램명이 없으면 기사에서 찾아 명시, 없으면 삭제
      5) 주가 종목명 — '주가' 주체가 상장 종목이 아니면 기사 속 종목명으로 교체, 없으면 삭제
      6) 발언 주체 — 비판·의혹 항목 주어가 기사 발언자가 아니라 대상이면 삭제(재작성은 프롬프트 규칙 몫)
    헤드라인 재생성(1번 항목 기반)보다 **앞**에서 돈다 — 뒤에서 돌면 지운 항목이 제목에 남는다.

어떤 실패도 발행을 막지 않는다. 다만 모듈 자체가 실패하면 호출부가 관리자에게 알린다.
"""
import os
import re
import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger("publish_guard")
KST = ZoneInfo("Asia/Seoul")
_HERE = os.path.dirname(os.path.abspath(__file__))
STOCK_CONFIG = os.path.join(_HERE, "config", "stock_names.json")
MAX_AGE_HOURS = int(os.environ.get("TIMELINESS_MAX_AGE_HOURS", "24"))
NO_NEWS = "금일 주요 보도 없음"


def prompt_rules(today_label: str) -> str:
    """두 생성기의 프롬프트에 그대로 들어가는 공통 규칙 문안."""
    return (
        "[공통 발행 규칙 — 06·13·18·22시 공통]\n"
        f"- [날짜 표현] 기사 본문의 날짜가 오늘({today_label} KST)이 아니면 그 기사로 쓰는 항목에 "
        "'오늘'·'금일'·'확정' 표현 금지.\n"
        "- [주어 검증] 비판·의혹·고발 기사는 요약 전에 [발언 주체 / 대상자 / 발언 내용]을 먼저 추출하고"
        "(출력하지 말 것), 요약문 주어는 반드시 '발언 주체'로 쓸 것.\n"
        "    대상자가 주어로 오면 재작성. 예: 'A 최고위원, B 대표의 의혹 제기를 비판' → 주어는 A. "
        "'B 대표, 의혹 제기'로 쓰면 오류.\n"
        "- [시제 검증] 기사 본문에 '예정·앞두고·개최한다·전망'이 있으면 요약문도 미래형('~ 예정')으로 쓸 것.\n"
        "    '개최·주최·진행·열려·의결·발의' 완료형은 기사 본문에 과거형 서술(개최했다·열렸다 등)이 있을 때만 허용.\n"
        "- [방송 프로그램명] 시청률·예능·방송 내용 항목은 프로그램명을 반드시 명시할 것"
        "(예: 'MBC 예능 '신인감독 김연경2'에서 원더독스가 흥국생명에 역전승'). 방송 속 경기를 실제 리그 경기처럼 쓰지 말 것.\n"
        "- [주가 종목명] 주가·주식 항목의 주어는 기사에 나온 상장 종목명으로 쓸 것"
        "(예: 구단 '삼성 라이온즈'가 아니라 '삼성전자 주가'). 종목명이 기사에 없으면 주가 서술을 쓰지 말 것.\n"
    )


# ── 방송 프로그램명 ──────────────────────────────────────────────
BROADCAST_RE = re.compile(r"시청률|예능|방송분|본방송")
_QUOTED_RE = re.compile(r"[‘'\"“《<「『]([^‘’'\"“”《》<>「」『』]{2,24})[’'\"”》>」』]")
_PROG_RE = re.compile(r"(?:예능|드라마|방송)(?:\s*프로그램)?\s+([가-힣A-Za-z0-9][가-힣A-Za-z0-9 ]{1,22}?)\s*\d+\s*회")


def program_names(src: str) -> list[str]:
    """기사 텍스트에서 방송 프로그램명 후보. 따옴표 안 이름 우선, 그다음 '예능 X 5회' 형태."""
    out = []
    for m in _QUOTED_RE.finditer(src or ""):
        name = m.group(1).strip()
        if re.search(r"\d+(?:\.\d+)?\s*%", name):
            continue
        if any(k in src[m.end():m.end() + 30] for k in ("회", "시청률", "방송", "예능")) or \
           any(k in src[max(0, m.start() - 12):m.start()] for k in ("예능", "MBC", "KBS", "SBS", "JTBC", "tvN", "채널A", "TV조선", "MBN")):
            out.append(name)
    for m in _PROG_RE.finditer(src or ""):
        out.append(m.group(1).strip())
    seen, uniq = set(), []
    for n in out:
        if n not in seen:
            seen.add(n); uniq.append(n)
    return uniq


def check_program(body: str, src: str) -> tuple[str, str | None]:
    if not BROADCAST_RE.search(body):
        return body, None
    names = program_names(src)
    if any(n in body for n in names):
        return body, None
    if not names and program_names(body):
        return body, None                       # 근거 대조는 못 하지만 항목에 프로그램명이 있다
    if not names:
        return "", "방송 프로그램명 확인 불가 — 삭제"
    prog = names[0]
    return f"'{prog}' 방송에서 {body}", f"프로그램명 명시 '{prog}'"


# ── 주가 종목명 ────────────────────────────────────────────────
_STOCK_CACHE = None


def stock_config() -> dict:
    global _STOCK_CACHE
    if _STOCK_CACHE is None:
        try:
            with open(STOCK_CONFIG, encoding="utf-8") as f:
                _STOCK_CACHE = json.load(f)
        except Exception as e:
            logger.warning(f"[종목명] 설정 로드 실패 — 비활성: {e}")
            _STOCK_CACHE = {"listed": {}, "non_listed_markers": []}
    return _STOCK_CACHE


STOCK_RE = re.compile(r"주가|주식|시가총액")
_SUBJ_RE = re.compile(r"([가-힣A-Za-z0-9&]+(?:\s[가-힣A-Za-z0-9&]+)?)(의)?\s*(주가|주식|시가총액)")


def stock_names_in(text: str) -> list[str]:
    """텍스트에 나온 상장 종목명(정식명). 약칭('삼전')은 정식명으로 바꿔 돌려준다."""
    found = []
    for name, aliases in stock_config().get("listed", {}).items():
        for a in [name] + list(aliases):
            if re.search(r"(?<![가-힣A-Za-z])" + re.escape(a), text or ""):
                if name not in found:
                    found.append(name)
                break
    for m in re.finditer(r"([가-힣A-Za-z0-9&]{2,12})\s*\(\s*\d{6}\s*\)", text or ""):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


def check_stock(body: str, src: str) -> tuple[str, str | None]:
    m = _SUBJ_RE.search(body)
    if not m:
        return body, None
    subj = m.group(1)
    src_stocks = stock_names_in(src)
    subj_stocks = stock_names_in(subj)
    if subj_stocks and set(subj_stocks) & set(src_stocks):
        return body, None
    markers = stock_config().get("non_listed_markers", [])
    if subj_stocks and not any(k in subj for k in markers):
        return body, None                       # 상장 종목을 썼고 기사만 표기가 다른 경우는 둔다
    if len(src_stocks) == 1:
        # 주체를 지우지 않고 종목을 붙인다 — '우승팀인 삼성전자 주가'처럼 수식어가 종목에 붙는 오독 방지
        name = re.sub(r"의$", "", subj)
        new = body[:m.start(1)] + f"{name} 관련 {src_stocks[0]}" + body[m.end(1):]
        return new, f"주가 주체 '{subj}' → 종목명 '{src_stocks[0]}'"
    if len(src_stocks) > 1:
        return "", f"주가 주체 '{subj}' — 기사 종목 {len(src_stocks)}개 중 특정 불가, 삭제"
    return "", f"주가 주체 '{subj}' — 기사에 상장 종목명 없음, 삭제"


# ── 발언 주체 주어 ─────────────────────────────────────────────
ACCUSE_RE = re.compile(r"의혹|비판|고발|규탄|폭로|저격|맹공|질타|공세")
_TITLE_WORDS = r"(?:최고위원|대표|원내대표|의원|위원장|장관|대변인|총리|대통령|지사|시장|후보|비대위원장)"
_SRC_SPEAKER_RE = re.compile(r"^[\W]*([가-힣]{2,4})(?:\s+[가-힣A-Za-z]{1,10}){0,2}?\s*" + _TITLE_WORDS + r"?\s*[,，]")
_ITEM_SUBJ_RE = re.compile(r"^[\W]*([가-힣]{2,4})(?:\s+[가-힣]{1,8})?\s*(?:[,，]|이\s|가\s|은\s|는\s)")


def check_subject(body: str, src_title: str, src: str) -> tuple[str, str | None]:
    """비판·의혹·고발 항목의 주어가 근거 기사 발언자와 다르고, 그 주어가 기사에서는 대상으로만
    나오면 주어 역전으로 보고 삭제한다(11/10 '김민석 대표, 신천지 의혹 제기' ← 이성윤 비판 기사).
    재작성은 LLM 없이 안전하게 못 하므로 삭제만 한다. 판정 근거가 없으면 통과."""
    if not ACCUSE_RE.search(body):
        return body, None
    sm, im = _SRC_SPEAKER_RE.search(src_title or ""), _ITEM_SUBJ_RE.search(body)
    if not sm or not im:
        return body, None
    speaker, subj = sm.group(1), im.group(1)
    if speaker == subj or speaker not in (src or "") or subj not in (src or ""):
        return body, None
    if speaker in body.split(subj, 1)[0]:
        return body, None
    return "", f"주어 역전 의심 — 기사 발언자 '{speaker}', 항목 주어 '{subj}'(기사 속 대상), 삭제"


# ── 최종 관문 ──────────────────────────────────────────────────
def _family(briefing_type: str) -> str:
    return "politics" if (briefing_type or "").startswith("political") else "general"


def final_pass(briefing: str, pool: list[dict], briefing_type: str,
               now: datetime | None = None, report=None) -> tuple[str, list[str]]:
    """→ (텍스트, 메모). 항목마다 근거 기사를 다시 찾아 1~5 를 적용한다."""
    import source_bind
    import timeliness
    import tense_guard
    now = now or datetime.now(KST)
    lines = briefing.split("\n")
    notes: list[str] = []
    undated: list[dict] = []
    for i, ln in enumerate(lines):
        s = (ln or "").strip()
        if not s.startswith("▪") or NO_NEWS in s:
            continue
        body = s.lstrip("▪").strip()
        art, ov = source_bind.best_match(body, pool or [])
        src = ""
        if art is not None and ov >= source_bind.MIN_OVERLAP:
            src = f"{art.get('title', '')} {art.get('description') or ''}"
            dt = source_bind._pub(art)
            if dt is None:
                lines[i] = None
                notes.append(f"[날짜미상] 근거 기사 발행시각 없음 — 삭제·큐: {body[:40]}")
                undated.append({"title": f"{timeliness.UNDATED_TAG} {art.get('title', '')}", "undated": True,
                                "link": art.get("link") or art.get("url") or "",
                                "source": art.get("source") or ""})
                continue
            age = (now - dt).total_seconds() / 3600
            if age > MAX_AGE_HOURS:
                lines[i] = None
                notes.append(f"24h 초과 근거({age:.0f}h) — 삭제: {body[:40]}")
                continue
        else:
            notes.append(f"근거 재매칭 실패(겹침 {ov}) — 원문 대조 생략: {body[:40]}")

        title = (art or {}).get("title", "") if src else ""
        checks = (("주어", lambda b, s: check_subject(b, title, s)), ("시제", tense_guard.check),
                  ("방송", check_program), ("종목", check_stock))
        for label, fn in checks:
            if label in ("주어", "시제") and not src:
                continue
            new, note = fn(body, src)
            if note is None:
                continue
            notes.append(f"{label}: {note} | {body[:40]}")
            if new == "":
                lines[i] = None
                break
            body = new
        if lines[i] is not None:
            lines[i] = "▪ " + body
    if undated:
        timeliness.queue_undated(undated, _family(briefing_type))
    out = "\n".join(l for l in lines if l is not None)
    logger.warning(f"[발행관문] {briefing_type}: {len(notes)}건 {notes[:6]}")
    if report is not None:
        report.content_notes = list(getattr(report, "content_notes", []) or []) + [f"발행관문 {n}" for n in notes]
    return out, notes
