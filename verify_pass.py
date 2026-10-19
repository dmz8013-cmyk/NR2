"""
verify_pass.py — 브리핑 발행 전 자가 검증 패스 (2차 팩트체크 패치)

발행 직전, 고위험 항목만 웹 검색으로 교차 검증한다.

흐름:
  1) 브리핑을 ▪ 불릿 항목 단위로 파싱
  2) 위험 태깅:
     (a) config/facts.json 에 없는 인명+직함 조합
     (b) 상태변화 동사(가결/부결/구형/선고/사망/지명/출범/체결/확정/돌파) 포함
     (c) 구체 수치 + 단정 종결(완곡 표현 없음)
     (d) 외화 금액(천/만/억/조 + 달러·엔 등) — 단위 자릿수 대조
     (e) 실명 발언·행위: 인명 + 발언/행위 술어 → 무조건 검색 (2026-10-07)
  3) 태깅 항목만 Claude(haiku-4-5 + web_search)로 검증 — 회당 상한 8건(정치 브리핑 14건)
     우선순위: 사전 밖 인명·직함 > 실명 인용 > 수치 단정 > 상태변화
     실명 발언 판정: 48h 내 결과에 (인명) AND (핵심어 2개 이상) → 일치.
     최신 보도가 48h 이전이면 stale(제외), 사전 밖 인명+직함이 검색 0건이면 존재 불명(제외).
     실명 발언 '확인불가'는 완곡 처리 없이 제외 + recheck_queue 적재(다음 회차 재검색).
     · 일치     → 통과
     · 불일치   → 수정문으로 교체
     · 확인불가 → 브리핑: 항목 자체를 제외 + 관리자 DM "미확인 제외: 제목"
                  (루머 유통 방지 — 완곡 발행 금지, 2026-09-15)
                  leader_watch: 기존대로 완곡화("~로 전해짐" 체) 유지
  4) 결과 24시간 캐시(/tmp) — 아침·저녁 동일 항목 재검증 방지
  5) 회차별 건수를 DB(verify_log)에 기록 (주간 리포트용)

실패 안전: 이 모듈의 어떤 오류도 발행을 중단시키지 않는다 —
run_verify_pass()는 예외를 삼키고 원문(또는 부분 수정본)을 반환한다.

비용(모델 선정 근거): haiku-4-5 기준 항목당 ~$0.03(토큰+검색 2회),
회당 최대 8건×2회/일 ≈ 월 $9~15. sonnet이면 월 $24+(3만원 초과)라 haiku 채택.
"""

import os
import re
import json
import time
import hashlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import anthropic
except ImportError:
    anthropic = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("verify_pass")

KST = ZoneInfo("Asia/Seoul")
_HERE = os.path.dirname(os.path.abspath(__file__))
FACTS_JSON_PATH = os.path.join(_HERE, "config", "facts.json")

VERIFY_MODEL = "claude-haiku-4-5-20251001"
MAX_VERIFY_PER_RUN = 14         # 06/18 일반 브리핑 기본 상한 (8→14, 2026-10-08; 환경변수 VERIFY_MAX_GENERAL)
MAX_VERIFY_POLITICS = 14        # 13/22 정치 브리핑 — 거의 전 항목이 실명 발언 (2026-10-07; VERIFY_MAX_POLITICS)

# 기록·최상급 주장 — 상한과 무관하게 무조건 검색, 미확인이면 삭제(큐 미적재) (2026-10-08, '최원준 204안타' 유형)
RECORD_RE = re.compile(r"(최다|최초|신기록|사상\s*(?:최고|최대|최저|처음)|역대\s*(?:최고|최대|최다|최장)|\d+\s*연승|\d+\s*연패|"
                       r"\d+\s*승\s*(?:달성|고지)|\d+\s*안타|\d+\s*홈런\s*달성|대기록|새\s*역사|이정표|통산\s*\d+|최장|최단|최연소|최고령)")
LAUNCH_RE = re.compile(r"(신규\s*출시|정식\s*출시|첫\s*출시|출시됐음|출시했음|서비스\s*개시|상장됐음)")
# 수치 출처 병기 — 유출입·보유액·등락 수치는 기관명이 없으면 출처 확인 후 병기, 확인 불가·방향 불일치면 삭제
FLOW_RE = re.compile(r"(순?유입|순?유출|외환보유액|보유액|순매수|순매도|거래대금|등락|상승\s*마감|하락\s*마감|급등|급락|증가|감소|집계|기록했)")
SOURCE_RE = re.compile(r"(SoSoValue|소소밸류|SAFE|국가외환관리국|인민은행|한국은행|한은|금융감독원|금감원|금융위|한국거래소|KRX|거래소|"
                       r"업비트|빗썸|바이낸스|코인베이스|CoinGecko|코인게코|CoinMarketCap|코인마켓캡|Farside|파사이드|블룸버그|로이터|"
                       r"통계청|관세청|무역협회|산업부|기재부|기획예산처|연준|Fed|BIS|IMF|OECD|S&P|무디스|피치|나스닥|뉴욕증권거래소|"
                       r"에 따르면|기준\)|집계 기준|발표 기준|조사 결과|자료에 따르면)")
MAX_SEARCHES_PER_ITEM = 2
STALE_HOURS = 48                # 검색 결과 최신 기사가 이보다 오래되면 'stale'

# 실명 발언·행위 술어 — 인명과 결합하면 무조건 검색 대상 (허용 종결 술어 목록과 합집합)
SPEECH_PREDICATES = ["밝혔", "밝힘", "지적", "촉구", "규정", "요구", "질타", "반박", "발언", "주장",
                     "비판", "강조", "언급", "경고", "추궁", "반발", "제기", "요청", "직격", "거론",
                     "제시", "공약", "동의", "선언", "약속", "촉구", "제안", "표명", "시사", "공개"]
# 따옴표 앞 주어 휴리스틱에서 제외할 일반 명사 (인명 오인 방지)
NAME_STOPWORDS = {"대통령", "총리", "장관", "의원", "대표", "정부", "국회", "검찰", "경찰", "법원", "여당", "야당",
                  "민주당", "국민의힘", "청와대", "여야", "당국", "시장", "지사", "위원장", "원내대표", "대변인",
                  "관계자", "측근", "전문가", "시민", "누리꾼", "업계", "당내", "일각", "외신", "국방부", "외교부"}
# 여는 따옴표 바로 앞 주어 — 닫는 따옴표(뒤에 공백·문장부호)는 제외
QUOTE_SUBJECT_RE = re.compile(r"([가-힣]{2,4}?)(?:이|가|은|는|의)?\s*,?\s*[\"'“‘](?=[가-힣A-Za-z0-9])")
CACHE_PATH = "/tmp/verify_pass_cache.json"
CACHE_TTL_SEC = 24 * 3600

# (b) 상태변화 동사 — 활용형 포함 매칭을 위해 어간만
STATE_VERBS = ["가결", "부결", "구형", "선고", "사망", "지명", "출범", "체결", "확정", "돌파"]

# (a) 인명+직함 패턴 (이름 2~4자 + 직함어). 휴리스틱 — 미탐은 허용, 오탐은 검증에서 걸러짐
TITLE_WORDS = (
    "대통령|국무총리|총리|부총리|장관|차관|대표|원내대표|정책위의장|최고위원|사무총장|위원장|의원|"
    "대법원장|대법관|헌법재판관|총재|부총재|의장|지사|시장|부시장|부지사|군수|교육감|검찰총장|경찰청장|"
    "감독|회장|사장|구청장|특검|수석|비서관|대변인|부대변인|부속실장|실장|국장|부국장|차장|본부장|"
    "중수청장|공소청장|청장|직무대행|후보자|대사|사령관|부사령관|부장판사|부장검사|판사|검사|변호사|교수|원장|이사장|행정관|보좌관"
)
# 직함 뒤는 조사/문장부호/공백/끝만 허용 — '대표팀'·'의원장'·'감독관' 같은 확장어 오매칭 방지
# 인명과 직함 사이 소속어 1개 허용 ('김지용 검찰 부국장', '김정관 산업통상부 장관')
NAME_TITLE_RE = re.compile(
    rf"([가-힣]{{2,4}})\s+(?:[가-힣]{{2,8}}\s+)?(?:전\s+)?({TITLE_WORDS})(?=[이가은는을를과와도의로에,.·;)\s]|$)")
# 인명 자리에 올 수 없는 기관·단체어 (직함 앞 소속어가 인명으로 잡히는 오탐 방지)
ORG_STOPWORDS = {"국회", "정부", "검찰", "경찰", "법원", "대법원", "헌재", "선관위", "청와대", "여당", "야당", "여야",
                 "민주당", "국민의힘", "혁신당", "개혁신당", "진보당", "새로운미래", "조국혁신당", "더불어민주당",
                 "법사위", "행안위", "문체위", "외통위", "국방위", "정무위", "기재위", "과방위", "복지위", "환노위",
                 "국토위", "산자위", "여가위", "예결위", "운영위", "정보위", "국방부", "외교부", "통일부", "법무부",
                 "복지부", "문체부", "행안부", "기재부", "산업부", "환경부", "교육부", "국토부", "공정위", "금감원",
                 "금융위", "감사원", "공소청", "중수청", "한국당", "서울시", "경기도", "국정원", "합참", "육군",
                 "해군", "공군", "주한미군", "연합사", "대통령실", "비서실", "총리실", "국무회의"}


AMBIGUOUS_TITLES = {"시장", "감독", "대표", "회장", "사장", "의장", "원장", "국장", "교수", "대사"}   # 일반명사로도 쓰이는 직함


def _looks_like_person(name: str, title: str = "", known: set | None = None) -> bool:
    """기관어·조사 결합 토큰('비판에 의원' 의 '비판에', '감소폭이 시장', '암호화폐 시장')은 인명으로 보지 않는다."""
    if not name or name in ORG_STOPWORDS:
        return False
    if name.endswith(("당", "부", "청", "실", "위", "처", "에", "의", "을", "를", "은", "는", "과", "와", "로",
                      "한", "된", "할", "될", "던", "인")):          # 관형형·조사 결합
        return False
    if len(name) == 4 and name.endswith(("이", "가")):            # '감소폭이' 류 3자 명사+조사
        return False
    if title in AMBIGUOUS_TITLES and not (known and name in known) and len(name) != 3:
        return False                                              # '암호화폐 시장'·'리그 감독' — 3자 인명만 허용
    return True

# (c) 구체 수치 + 단정 종결
NUMBER_RE = re.compile(r"[0-9][0-9,.]*\s*(?:%|퍼센트|조|억|만|천|달러|원|명|건|배|년|개월|일|포인트|p|도|㎜|mm|km|㎞)")
SOFTENERS = ["전해", "알려", "보인다", "보이", "전망", "예정", "추정", "관측", "가능성", "예상", "계획", "논의", "검토"]

# (d) 외화 금액 — 천/만 단위 자릿수 오역이 잦아 완곡 여부와 무관하게 검증 대상
CURRENCY_RE = re.compile(r"[0-9][0-9,.]*\s*(?:조|억|만|천)\s*[0-9,.]*\s*(?:달러|엔|유로|위안|파운드)")

VERIFY_PROMPT = """다음 문장이 최근 보도와 일치하는지 검색해 판정하라.
일치/불일치(수정문 제시)/확인불가 중 하나로만 응답.
문장에 외화 금액이 있으면 통화 단위와 자릿수(천/만/억/조)가 원보도와 일치하는지
최우선으로 대조하라 — 천/만 단위 환산 오류(예: 8,890억↔8조8,900억)가 잦다.

오늘 날짜: {today}
검증 대상 문장: "{sentence}"

반드시 아래 JSON 형식으로만 최종 응답할 것 (설명 금지):
{{"verdict": "일치" 또는 "불일치" 또는 "확인불가",
 "corrected": "불일치면 보도에 부합하는 수정문 1문장, 확인불가면 원문을 '~로 전해졌다' 체로 완곡화한 1문장, 일치면 빈 문자열",
 "newest_pub_date": "확인한 보도 중 가장 최신 발행일 YYYY-MM-DD, 없으면 빈 문자열",
 "event_date": "문장이 서술하는 사건(공개·발표·출시·게시·결정 등)이 실제로 일어난 날짜 YYYY-MM-DD, 모르면 빈 문자열"}}"""


NAMED_PROMPT = """다음 '실명 발언·행위' 문장이 최근 48시간 내 보도와 일치하는지 웹 검색으로 판정하라.
검색 결과 1건 이상에 (인명) 과 (핵심어 2개 이상)이 함께 담겨 있어야만 '일치'다.
인명+직함 조합이 어떤 보도에도 없으면 person_exists 를 false 로 보고하라.

오늘 날짜: {today}
인명: {names}
핵심어 후보: {keywords}
검증 대상 문장: "{sentence}"

반드시 아래 JSON 으로만 최종 응답 (설명 금지):
{{"verdict": "일치" 또는 "불일치" 또는 "확인불가",
 "corrected": "불일치면 보도에 부합하는 수정문 1문장, 아니면 빈 문자열",
 "matched_name": true/false,
 "matched_keywords": ["문장 핵심어 중 보도에서 확인된 것"],
 "newest_pub_date": "확인한 보도 중 가장 최신 발행일 YYYY-MM-DD, 없으면 빈 문자열",
 "person_exists": true/false/null,
 "event_date": "문장이 서술하는 사건이 실제로 일어난 날짜 YYYY-MM-DD, 모르면 빈 문자열"}}"""

SOURCE_PROMPT = """다음 수치 문장이 최근 보도와 일치하는지 웹 검색으로 판정하고, 수치의 '출처 기관'을 찾아라.
방향(유입/유출, 증가/감소, 상승/하락)이 보도와 다르면 반드시 direction_ok=false.

오늘 날짜: {today}
검증 대상 문장: "{sentence}"

반드시 아래 JSON 으로만 최종 응답 (설명 금지):
{{"verdict": "일치" 또는 "불일치" 또는 "확인불가",
 "direction_ok": true/false,
 "source_org": "수치를 집계·발표한 기관명(예: SoSoValue, 국가외환관리국 SAFE, 한국거래소). 모르면 빈 문자열",
 "corrected": "원문 문장에 출처 기관을 자연스럽게 병기한 1문장(수치·방향은 보도대로). 확인불가면 빈 문자열",
 "event_date": "수치가 집계·발표된 날짜 YYYY-MM-DD, 모르면 빈 문자열"}}"""

_STOP_TOKENS = {"대해", "관련", "위해", "통해", "대한", "이번", "오늘", "지난", "현재", "것으로", "것을", "등을",
                "등이", "에서", "으로", "에게", "까지", "부터", "하며", "하고", "했다", "했음", "했음.", "했다.", "이라고"}


# ══════════════════════════════════════════════════
#  1. 파싱 & 위험 태깅
# ══════════════════════════════════════════════════
def _speech_predicates() -> list[str]:
    preds = list(SPEECH_PREDICATES)
    try:
        from briefing_layout import allowed_endings
        preds += list(allowed_endings())
    except Exception:
        pass
    return preds


def person_names(text: str, known_names: set) -> list[str]:
    """항목에서 인명 후보: 사전 등재 인명 ∪ 인명+직함 매치 ∪ 따옴표 앞 주어(불용어 제외)."""
    names = []
    for n in known_names:
        if n and n in text and n not in names:
            names.append(n)
    for m in NAME_TITLE_RE.finditer(text):
        if m.group(1) not in names and _looks_like_person(m.group(1), m.group(2), known_names):
            names.append(m.group(1))
    title_set = set(TITLE_WORDS.split("|"))
    for m in QUOTE_SUBJECT_RE.finditer(text):
        cand = m.group(1)
        if cand in NAME_STOPWORDS or cand in title_set or not _looks_like_person(cand) or any(cand in n for n in names):
            continue
        if len(cand) == 3 and cand not in names:   # 한국 인명은 3자 기본 — 2·4자는 사전/직함 경로로만
            names.append(cand)
    names.sort(key=lambda n: text.find(n))         # 원문 등장 순 (집합 순서 비결정성 제거)
    return names


def keywords_of(text: str, names: list[str], limit: int = 6) -> list[str]:
    """핵심어 후보 — 2자 이상 한글/숫자 토큰, 조사·불용어·인명 제외, 긴 토큰 우선."""
    toks = re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
    out = []
    for t in toks:
        t2 = re.sub(r"(으로|에서|에게|까지|부터|이라고|라고|하며|했음|했다|이다|에는|에도|들이|들을|으로써)$", "", t)
        if len(t2) >= 3:
            t2 = re.sub(r"[이가은는을를의과와도에]$", "", t2)
        if len(t2) < 2 or t2 in _STOP_TOKENS or any(t2 in n or n in t2 for n in names):
            continue
        if t2 not in out:
            out.append(t2)
    out.sort(key=lambda x: -len(x))
    return out[:limit]

def _load_known_names() -> set:
    """config/facts.json 인물_직함의 등재 인명 집합."""
    try:
        with open(FACTS_JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return set((data.get("인물_직함") or {}).keys())
    except Exception as e:
        logger.warning(f"[자가검증] facts.json 로드 실패(인명 태깅 완화): {e}")
        return set()


def parse_items(briefing: str) -> list[tuple[int, str]]:
    """▪ 불릿 항목 (줄번호, 본문) 목록. ▪ 없으면 빈 목록(검증 스킵)."""
    items = []
    for i, line in enumerate(briefing.split("\n")):
        s = line.strip()
        if s.startswith("▪"):
            items.append((i, s.lstrip("▪").strip()))
    return items


def tag_item(text: str, known_names: set) -> list[str]:
    """위험 사유 태깅. 빈 리스트 = 저위험(검증 생략)."""
    reasons = []
    # (a) 사전에 없는 인명+직함 (기관어·단체어는 인명으로 보지 않음)
    for m in NAME_TITLE_RE.finditer(text):
        name = m.group(1)
        if name not in known_names and _looks_like_person(name, m.group(2), known_names):
            reasons.append(f"미등재 인명+직함: {name} {m.group(2)}")
            break
    # (b) 상태변화 동사
    hit = next((v for v in STATE_VERBS if v in text), None)
    if hit:
        reasons.append(f"상태변화 동사: {hit}")
    # (c) 구체 수치 + 단정 종결 — '다.'체와 명사형·음슴체('~음/됨/임.') 모두 대응
    if (NUMBER_RE.search(text)
            and text.endswith(("다.", "음.", "됨.", "임.", "함."))
            and not any(s in text for s in SOFTENERS)):
        reasons.append("수치+단정 종결")
    # (d) 외화 금액 — 단위 자릿수 대조
    m = CURRENCY_RE.search(text)
    if m:
        reasons.append(f"외화 금액 단위: {m.group(0)}")
    # (e) 실명 발언·행위 — 인명 + 발언/행위 술어 결합 시 무조건 검색 대상
    names = person_names(text, known_names)
    if names and any(p in text for p in _speech_predicates()):
        reasons.append("실명 발언: " + "·".join(names[:3]))
    # (f) 기록·최상급 주장 — 필수 검색, 미확인 삭제
    m = RECORD_RE.search(text)
    if m:
        reasons.append(f"기록 주장: {m.group(0)}")
    # (h) 신규 출시·개시 주장 — 상한 내 검색(수치 그룹 우선순위)
    m = LAUNCH_RE.search(text)
    if m:
        reasons.append(f"출시 주장: {m.group(0)}")
    # (g) 수치 출처 병기 — 유출입·보유액·등락 수치에 기관명 부재
    if NUMBER_RE.search(text) and FLOW_RE.search(text) and not SOURCE_RE.search(text):
        reasons.append("수치 출처 필요")
    return reasons


# 사건 시점 검사 — 공개·발표·출시·게시류 서술의 '사건 발생일'이 오늘·전일이 아니면 제외 (기사 발행일이 최근이어도)
EVENT_VERB_RE = re.compile(r"(공개|발표|출시|게시|발간|공표|선보|배포|개봉|상장)")


def stale_event(text: str, event_date: str) -> bool:
    if not event_date or not EVENT_VERB_RE.search(text or ""):
        return False
    try:
        from timeliness import allowed_dates, within_max_age
        d = datetime.strptime(event_date[:10], "%Y-%m-%d").date()
        if d not in allowed_dates():
            return True
        # 24h 하드 필터 — 시각까지 있는 값만 적용 (날짜만 있으면 자정으로 해석돼
        # '전일'이 항상 24h 초과가 되므로 날짜 의미를 유지한다). 2026-10-19
        if len(event_date) > 10 and not within_max_age(event_date):
            return True
        return False
    except Exception:
        return False


def is_mandatory(reasons: list[str]) -> bool:
    """상한과 무관하게 검색: 기록 주장·수치 출처 필요."""
    return any(r.startswith("기록 주장") or r == "수치 출처 필요" for r in reasons)


def priority_of(reasons: list[str], briefing_type: str = "") -> int:
    """검색 우선순위.
    정치: 사전 밖 인명·직함(0) > 실명 인용(1) > 수치·기록 단정(2) > 상태변화(3)
    일반: 사전 밖 인명·직함(0) > 수치·기록 단정(1) > 실명 인용(2) > 상태변화(3)"""
    joined = " ".join(reasons)
    politics = (briefing_type or "").startswith("political")
    if "미등재 인명+직함" in joined:
        return 0
    numeric = ("수치+단정" in joined or "외화 금액" in joined or "기록 주장" in joined or "수치 출처" in joined
               or "출시 주장" in joined)
    named = "실명 발언" in joined
    if politics:
        if named:
            return 1
        if numeric:
            return 2
    else:
        if numeric:
            return 1
        if named:
            return 2
    if "잔여 검색" in joined:
        return 4
    return 3


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def max_verify_for(briefing_type: str) -> int:
    """상한 — 정치 VERIFY_MAX_POLITICS(기본 14, 10/14 이후 10 예정) / 일반 VERIFY_MAX_GENERAL(기본 14)."""
    if (briefing_type or "").startswith("political"):
        return _env_int("VERIFY_MAX_POLITICS", MAX_VERIFY_POLITICS)
    return _env_int("VERIFY_MAX_GENERAL", MAX_VERIFY_PER_RUN)


def _section_of(lines: list[str], line_no: int) -> str:
    """항목 줄 위로 올라가며 섹션 헤더(이모지 줄) 텍스트 반환."""
    try:
        from briefing_layout import SECTION_HEADER_RE
    except Exception:
        SECTION_HEADER_RE = re.compile(r'^(🏛️|💰|🤖|🎯|📌|🇰🇷|🟦|🟥|🎸|🌐)')
    for i in range(line_no, -1, -1):
        if lines[i] is None:            # 제외 처리된 줄(None) 건너뜀 — 10/12 06:00 큐 적재 실패 원인
            continue
        st = lines[i].strip()
        if SECTION_HEADER_RE.match(st):
            return re.sub(r"[^\w가-힣/ ·]", "", st).strip()[:40]
    return ""


# ══════════════════════════════════════════════════
#  2. 24시간 캐시
# ══════════════════════════════════════════════════
def _item_key(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _cache_load() -> dict:
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        now = time.time()
        return {k: v for k, v in cache.items() if now - v.get("ts", 0) < CACHE_TTL_SEC}
    except Exception:
        return {}


def _cache_save(cache: dict) -> None:
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[자가검증] 캐시 저장 실패(무시): {e}")


# ══════════════════════════════════════════════════
#  3. 웹 검색 검증
# ══════════════════════════════════════════════════
def _verify_with_search(client, text: str) -> dict:
    """항목 1건 검증. 반환: {verdict, corrected, searches}. 오류 시 verdict='오류'."""
    try:
        resp = client.messages.create(
            model=VERIFY_MODEL,
            max_tokens=500,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": MAX_SEARCHES_PER_ITEM,
            }],
            messages=[{
                "role": "user",
                "content": VERIFY_PROMPT.format(
                    today=datetime.now(KST).strftime("%Y년 %m월 %d일"),
                    sentence=text,
                ),
            }],
        )
        # 최종 텍스트 블록에서 JSON 추출
        final_text = ""
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                final_text = block.text
        searches = 0
        try:
            searches = resp.usage.server_tool_use.web_search_requests
        except Exception:
            pass

        start, end = final_text.find("{"), final_text.rfind("}")
        if start != -1 and end > start:
            data = json.loads(final_text[start:end + 1])
            verdict = (data.get("verdict") or "").strip()
            if verdict in ("일치", "불일치", "확인불가"):
                newest = (data.get("newest_pub_date") or "").strip()
                out = {"verdict": verdict, "corrected": (data.get("corrected") or "").strip(),
                       "newest_pub_date": newest, "searches": searches,
                       "event_date": (data.get("event_date") or "").strip()}
                if verdict == "일치" and newest:
                    try:
                        nd = datetime.strptime(newest, "%Y-%m-%d").replace(tzinfo=KST)
                        if (datetime.now(KST) - nd).total_seconds() > STALE_HOURS * 3600:
                            out["verdict"] = "stale"
                    except Exception:
                        pass
                return out
        # JSON 파싱 실패 → 키워드 폴백
        for v in ("불일치", "확인불가", "일치"):
            if v in final_text:
                return {"verdict": v, "corrected": "", "searches": searches}
        return {"verdict": "오류", "corrected": "", "searches": searches}
    except Exception as e:
        logger.warning(f"[자가검증] 검증 호출 실패(해당 항목 통과 처리): {e}")
        return {"verdict": "오류", "corrected": "", "searches": 0}


def _parse_json_block(final_text: str) -> dict | None:
    start, end = final_text.find("{"), final_text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(final_text[start:end + 1])
        except Exception:
            return None
    return None


def verify_named_statement(client, text: str, names: list[str], keywords: list[str],
                           unregistered: bool = False) -> dict:
    """실명 발언 항목 1건 검증.

    반환 verdict ∈ {일치, 불일치, 확인불가, stale, unknown_person, 오류} + corrected,
    matched_keywords, newest_pub_date, searches.
      · 일치   = 48h 내 결과에 (인명) AND (핵심어 ≥2)
      · stale  = 내용은 맞지만 최신 보도가 48h 이전 (더 새로운 결과 없음)
      · unknown_person = 사전 밖 인명+직함 조합이 검색 결과 0건
    """
    try:
        resp = client.messages.create(
            model=VERIFY_MODEL, max_tokens=600,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES_PER_ITEM}],
            messages=[{"role": "user", "content": NAMED_PROMPT.format(
                today=datetime.now(KST).strftime("%Y년 %m월 %d일"), names=", ".join(names) or "-",
                keywords=", ".join(keywords) or "-", sentence=text)}],
        )
        final_text = ""
        queries: list[str] = []
        for block in resp.content:
            btype = getattr(block, "type", "")
            if btype == "text":
                final_text = block.text
            elif btype == "server_tool_use":
                try:
                    q = (getattr(block, "input", None) or {}).get("query")
                    if q:
                        queries.append(str(q))
                except Exception:
                    pass
        searches = 0
        try:
            searches = resp.usage.server_tool_use.web_search_requests
        except Exception:
            pass
        data = _parse_json_block(final_text) or {}
        verdict = (data.get("verdict") or "").strip()
        if verdict not in ("일치", "불일치", "확인불가"):
            verdict = next((v for v in ("불일치", "확인불가", "일치") if v in final_text), "오류")
        matched_kw = [k for k in (data.get("matched_keywords") or []) if isinstance(k, str)]
        newest = (data.get("newest_pub_date") or "").strip()
        exists = data.get("person_exists")
        out = {"verdict": verdict, "corrected": (data.get("corrected") or "").strip(),
               "matched_name": bool(data.get("matched_name")), "matched_keywords": matched_kw,
               "newest_pub_date": newest, "person_exists": exists, "searches": searches,
               "queries": queries, "event_date": (data.get("event_date") or "").strip()}
        # 사전 밖 인명+직함: 검색에서 그 조합이 0건(person_exists=false) 이거나,
        # 확인불가인데 인명조차 보도에서 안 잡히면 '존재 불명 인물' — 큐에 넣지 않고 즉시 제외
        if unregistered and (exists is False or (verdict == "확인불가" and not out["matched_name"])):
            out["verdict"] = "unknown_person"
            return out
        if verdict == "일치":
            if not (out["matched_name"] and len(matched_kw) >= 2):
                out["verdict"] = "확인불가"
                return out
            try:
                nd = datetime.strptime(newest, "%Y-%m-%d").replace(tzinfo=KST)
                if (datetime.now(KST) - nd).total_seconds() > STALE_HOURS * 3600:
                    out["verdict"] = "stale"
            except Exception:
                pass
        return out
    except Exception as e:
        logger.warning(f"[자가검증] 실명 발언 검증 호출 실패(통과 처리): {e}")
        return {"verdict": "오류", "corrected": "", "searches": 0}


_RUMOR_RE = re.compile(r"(전해졌|전해진다|전해짐|전해져|알려졌|알려진다|알려짐|알려져|로 보인다|로 보임|는 관측|것으로 전해)")


def _sane_correction(original: str, corrected: str, known: set) -> bool:
    """수정문 적합성 — 전언 술어 없음 + 원문 인명 유지 + 원문 핵심어 1개 이상 + 길이 0.5~1.6배."""
    if _RUMOR_RE.search(corrected):
        return False
    names = person_names(original, known)
    if names and not any(n in corrected for n in names):
        return False
    kws = keywords_of(original, names)
    if kws and not any(k in corrected for k in kws):
        return False
    ratio = len(corrected) / max(1, len(original))
    return 0.5 <= ratio <= 1.6


def verify_numeric_source(client, text: str) -> dict:
    """수치 출처 병기 검증 → {verdict, direction_ok, source_org, corrected, searches}."""
    try:
        resp = client.messages.create(
            model=VERIFY_MODEL, max_tokens=500,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES_PER_ITEM}],
            messages=[{"role": "user", "content": SOURCE_PROMPT.format(
                today=datetime.now(KST).strftime("%Y년 %m월 %d일"), sentence=text)}],
        )
        final_text = ""
        for block in resp.content:
            if getattr(block, "type", "") == "text":
                final_text = block.text
        searches = 0
        try:
            searches = resp.usage.server_tool_use.web_search_requests
        except Exception:
            pass
        data = _parse_json_block(final_text) or {}
        verdict = (data.get("verdict") or "").strip()
        if verdict not in ("일치", "불일치", "확인불가"):
            verdict = next((v for v in ("불일치", "확인불가", "일치") if v in final_text), "오류")
        return {"verdict": verdict, "direction_ok": data.get("direction_ok", True) is not False,
                "source_org": (data.get("source_org") or "").strip(),
                "corrected": (data.get("corrected") or "").strip(), "searches": searches,
                "event_date": (data.get("event_date") or "").strip()}
    except Exception as e:
        logger.warning(f"[자가검증] 수치 출처 검증 호출 실패(통과 처리): {e}")
        return {"verdict": "오류", "direction_ok": True, "source_org": "", "corrected": "", "searches": 0}


def _with_source(original: str, corrected: str, source_org: str) -> str:
    """출처 병기 문장 — 모델 수정문이 수치·기관을 담으면 사용, 아니면 원문 끝에 '(기관 집계)' 부가."""
    nums = NUMBER_RE.findall(original)
    if corrected and source_org and source_org in corrected and all(n.strip() in corrected for n in nums[:2]):
        return corrected
    body = original.rstrip()
    end = ""
    while body and body[-1] in ".。":
        end = body[-1] + end
        body = body[:-1]
    return f"{body} ({source_org} 집계){end}" if source_org else original


def make_verifier():
    """재검색 큐용 검증 콜러블 — API 사용 불가면 None."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or anthropic is None:
        return None
    client = anthropic.Anthropic(api_key=api_key, timeout=90.0)
    known = _load_known_names()

    def _fn(text: str) -> dict:
        names = person_names(text, known)
        return verify_named_statement(client, text, names, keywords_of(text, names))
    return _fn


# ══════════════════════════════════════════════════
#  4. DB 로그 (주간 리포트용)
# ══════════════════════════════════════════════════
def _log_to_db(stats: dict) -> None:
    """verify_log 테이블에 회차 기록. 실패해도 무시."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.info(f"[자가검증] DATABASE_URL 없음 — DB 로그 생략: {stats}")
        return
    try:
        import psycopg2
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS verify_log (
                id SERIAL PRIMARY KEY,
                run_at TIMESTAMP DEFAULT NOW(),
                briefing_type VARCHAR(30),
                items_total INT, tagged INT, verified INT,
                passed INT, fixed INT, unconfirmed INT, errors INT, searches INT
            )""")
        cols = ("calls", "stale", "unknown_person", "queued", "mandatory", "record_dropped",
                "source_added", "source_dropped")
        for col in cols:
            cur.execute(f"ALTER TABLE verify_log ADD COLUMN IF NOT EXISTS {col} INT DEFAULT 0")
        keys = ("items_total", "tagged", "verified", "passed", "fixed", "unconfirmed", "errors", "searches") + cols
        row = {k: stats.get(k, 0) for k in keys}
        row["briefing_type"] = stats.get("briefing_type", "")
        cur.execute(f"""
            INSERT INTO verify_log (briefing_type, {", ".join(keys)})
            VALUES (%(briefing_type)s, {", ".join(f"%({k})s" for k in keys)})
        """, row)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"[자가검증] DB 로그 실패(무시): {e}")


def _notify_admin_excluded(titles: list, briefing_type: str) -> None:
    """확인불가로 제외한 항목을 관리자 DM으로 보고. 실패는 로그만."""
    try:
        import requests
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "5132309076")
        if not token:
            return
        body = "\n".join(f"미확인 제외: {t}" for t in titles)
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat,
                            "text": f"🚫 자가검증 미확인 항목 제외 ({briefing_type}, {len(titles)}건)\n{body}"},
                      timeout=10)
    except Exception as e:
        logger.warning(f"[자가검증] 제외 보고 DM 실패(무시): {e}")


# ══════════════════════════════════════════════════
#  5. 메인 — 발행 직전 훅
# ══════════════════════════════════════════════════
def run_verify_pass_ex(briefing: str, briefing_type: str = "", enqueue: bool = True,
                      notify: bool = False) -> tuple[str, dict, dict]:
    """검증 패스 실행. → (발행 가능 텍스트, stats, details).

    details = {excluded, stale, unknown, queued, fixed} — 각 항목 제목 목록(관리자 보고용).
    실명 발언 항목이 '확인불가'면 완곡 처리 없이 제외하고 recheck_queue 에 적재(enqueue=True).
    notify=True 면 구 포맷 DM('미확인 제외')도 보낸다(기본은 호출부 회차 요약이 담당)."""
    details = {"excluded": [], "stale": [], "unknown": [], "queued": [], "fixed": [],
               "record_dropped": [], "source_added": [], "source_dropped": []}
    stats = {"briefing_type": briefing_type, "items_total": 0, "tagged": 0, "verified": 0,
             "passed": 0, "fixed": 0, "unconfirmed": 0, "errors": 0, "searches": 0,
             "calls": 0, "stale": 0, "unknown_person": 0, "queued": 0,
             "mandatory": 0, "record_dropped": 0, "source_added": 0, "source_dropped": 0}
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key or anthropic is None:
            logger.warning("[자가검증] API 사용 불가 — 스킵")
            return briefing, stats, details

        lines = briefing.split("\n")
        items = parse_items(briefing)
        stats["items_total"] = len(items)
        if not items:
            logger.info("[자가검증] ▪ 항목 없음 — 스킵")
            return briefing, stats, details

        known = _load_known_names()
        tagged, untagged = [], []
        for line_no, text in items:
            reasons = tag_item(text, known)
            if reasons:
                tagged.append((line_no, text, reasons))
            elif briefing_type != "leader_watch":
                untagged.append((line_no, text, ["잔여 검색"]))   # 상한 여유분으로 검색 (미검색 발행 최소화)
        stats["tagged"] = len(tagged)
        if not tagged and not untagged:
            logger.info(f"[자가검증] 태깅 0건 (전체 {len(items)}항목) — 통과")
            _log_to_db(stats)
            return briefing, stats, details

        cap = max_verify_for(briefing_type)
        mandatory = [t for t in tagged if is_mandatory(t[2])]
        optional = [t for t in tagged if not is_mandatory(t[2])]
        optional.sort(key=lambda t: priority_of(t[2], briefing_type))   # 안정 정렬 — 같은 우선순위는 원문 순
        to_verify = mandatory + (optional + untagged)[:cap]
        to_verify.sort(key=lambda t: t[0])
        stats["mandatory"] = len(mandatory)
        logger.info(f"[자가검증] 태깅 {len(tagged)}건 중 {len(to_verify)}건 검증 "
                    f"(필수 {len(mandatory)} + 상한 {cap}, {briefing_type})")

        cache = _cache_load()
        client = anthropic.Anthropic(api_key=api_key, timeout=90.0)
        family = "politics" if briefing_type.startswith("political") else "general"
        run_label = f"{briefing_type} {datetime.now(KST):%Y-%m-%d %H:%M}"

        for line_no, text, reasons in to_verify:
            named = any(r.startswith("실명 발언") for r in reasons)
            unregistered = any(r.startswith("미등재 인명+직함") for r in reasons)
            record = any(r.startswith("기록 주장") for r in reasons)
            source_needed = "수치 출처 필요" in reasons
            mode = "S:" if (source_needed and not named) else ("N:" + ("U:" if unregistered else "") if named else "G:")
            key = _item_key("v2:" + mode + text)
            if key in cache:
                result = cache[key]
                logger.info(f"[자가검증] 캐시 적중: {text[:30]}… → {result['verdict']}")
            else:
                if named:
                    names = person_names(text, known)
                    result = verify_named_statement(client, text, names, keywords_of(text, names),
                                                    unregistered=unregistered)
                elif source_needed:
                    result = verify_numeric_source(client, text)
                else:
                    result = _verify_with_search(client, text)
                result["ts"] = time.time()
                cache[key] = result
                stats["searches"] += result.get("searches", 0)
                stats["calls"] += 1

            stats["verified"] += 1
            verdict = result["verdict"]
            corrected = (result.get("corrected") or "").strip().lstrip("▪").strip()
            title = text[:80]

            # 사건 시점: 발표·공개·출시류인데 사건 발생일이 오늘·전일 밖 → 시의성 미달 제외
            if verdict != "오류" and stale_event(text, result.get("event_date", "")):
                stats["stale"] += 1
                lines[line_no] = None
                details["stale"].append(f"{title} (사건일 {result.get('event_date')})")
                logger.warning(f"[자가검증] 사건 시점 미달 제외({result.get('event_date')}): {text[:40]}…")
                continue

            # (g) 수치 출처: 방향 불일치 → 즉시 삭제 / 일치+기관 → 병기 / 확인불가 → 삭제 (큐 미적재)
            if source_needed and not named and verdict != "오류":
                if not result.get("direction_ok", True):
                    lines[line_no] = None
                    stats["source_dropped"] += 1
                    details["source_dropped"].append(f"{title} (방향 불일치)")
                    logger.warning(f"[자가검증] 수치 방향 불일치 삭제: {text[:40]}…")
                    continue
                if verdict in ("일치", "불일치") and result.get("source_org"):
                    base = corrected if (verdict == "불일치" and corrected) else text
                    lines[line_no] = "▪ " + _with_source(base, result.get("corrected", ""), result["source_org"])
                    stats["source_added"] += 1
                    details["source_added"].append(f"{title} ← {result['source_org']}")
                    if verdict == "불일치":
                        stats["fixed"] += 1
                    else:
                        stats["passed"] += 1
                    continue
                lines[line_no] = None
                stats["source_dropped"] += 1
                details["source_dropped"].append(f"{title} ({'출처 미확인' if verdict == '일치' else verdict})")
                logger.warning(f"[자가검증] 수치 출처 미확인 삭제: {text[:40]}…")
                continue

            # (f) 기록·최상급: 일치만 통과, 적합한 수정문은 반영, 그 외 삭제 (큐 미적재)
            if record and verdict not in ("일치", "오류"):
                if verdict == "불일치" and corrected and _sane_correction(text, corrected, known):
                    lines[line_no] = "▪ " + corrected
                    stats["fixed"] += 1
                    details["fixed"].append(title)
                    logger.warning(f"[자가검증] 기록 주장 수정: {text[:40]}… → {corrected[:40]}…")
                else:
                    lines[line_no] = None
                    stats["record_dropped"] += 1
                    details["record_dropped"].append(f"{title} ({verdict})")
                    logger.warning(f"[자가검증] 기록 주장 미확인 삭제: {text[:40]}…")
                continue

            if verdict == "일치":
                stats["passed"] += 1
            elif verdict == "불일치" and corrected and _sane_correction(text, corrected, known):
                lines[line_no] = "▪ " + corrected
                stats["fixed"] += 1
                details["fixed"].append(title)
                logger.warning(f"[자가검증] 수정: {text[:40]}… → {corrected[:40]}…")
            elif verdict == "불일치" and named:
                # 실명 발언의 수정문이 인명·핵심어를 잃었거나 길이가 비정상 → 확인불가로 강등(제외+큐)
                verdict = "확인불가"
                stats["unconfirmed"] += 1
                lines[line_no] = None
                if enqueue:
                    try:
                        from recheck_queue import enqueue as _enq
                        rid = _enq(family, _section_of(lines, line_no) or "", text, person_names(text, known), run_label)
                        if rid:
                            stats["queued"] += 1
                            details["queued"].append(title)
                            logger.warning(f"[자가검증] 불일치(수정문 부적합) → 재검색 큐 #{rid}: {text[:40]}…")
                            continue
                    except Exception as qe:
                        logger.warning(f"[자가검증] 큐 적재 실패(제외 처리): {qe}")
                details["excluded"].append(title)
            elif verdict == "stale":
                stats["stale"] += 1
                lines[line_no] = None
                details["stale"].append(f"{title} (최신 보도 {result.get('newest_pub_date', '?')})")
                logger.warning(f"[자가검증] 시의성 미달 제외: {text[:40]}…")
            elif verdict == "unknown_person":
                stats["unknown_person"] += 1
                lines[line_no] = None
                ent = next((r.split(":", 1)[1].strip() for r in reasons if r.startswith("미등재 인명+직함")), title)
                qs = " | ".join(result.get("queries") or []) or "(쿼리 기록 없음)"
                details["unknown"].append(f"{ent} · 검색 쿼리: {qs}")
                logger.warning(f"[자가검증] 존재 불명 인물 제외: {ent} (검색: {qs})")
            elif verdict == "확인불가":
                stats["unconfirmed"] += 1
                if briefing_type == "leader_watch":
                    soft = corrected if corrected else text
                    lines[line_no] = "▪ ⚠️ " + soft
                    logger.warning(f"[자가검증] 확인불가(완곡+⚠️): {text[:40]}…")
                else:
                    lines[line_no] = None
                    if named and enqueue:
                        try:
                            from recheck_queue import enqueue as _enq
                            names = person_names(text, known)
                            rid = _enq(family, _section_of(lines, line_no) or "", text, names, run_label)
                            if rid:
                                stats["queued"] += 1
                                details["queued"].append(title)
                                logger.warning(f"[자가검증] 확인불가(실명) → 재검색 큐 #{rid}: {text[:40]}…")
                                continue
                        except Exception as qe:
                            logger.warning(f"[자가검증] 큐 적재 실패(제외 처리): {qe}")
                    details["excluded"].append(title)
                    logger.warning(f"[자가검증] 확인불가(항목 제외): {text[:40]}…")
            elif verdict == "불일치":
                # 수정문이 없거나 부적합(전언 술어·인명/핵심어 유실) → 항목 제외 (루머 유통 방지, 큐 미적재)
                stats["unconfirmed"] += 1
                lines[line_no] = None
                details["excluded"].append(f"{title} (불일치·수정문 부적합)")
                logger.warning(f"[자가검증] 불일치(수정문 부적합) 제외: {text[:40]}…")
            else:  # 오류 → 원문 유지(발행 우선)
                stats["errors"] += 1

        _cache_save(cache)
        _log_to_db(stats)
        if notify and details["excluded"]:
            _notify_admin_excluded(details["excluded"], briefing_type)
        logger.info(f"[자가검증] 완료 — 검증 {stats['verified']} / 통과 {stats['passed']} / "
                    f"수정 {stats['fixed']} / 확인불가 {stats['unconfirmed']} / stale {stats['stale']} / "
                    f"존재불명 {stats['unknown_person']} / 큐 {stats['queued']} / 기록삭제 {stats['record_dropped']} / "
                    f"출처병기 {stats['source_added']} / 출처삭제 {stats['source_dropped']} / 오류 {stats['errors']} / "
                    f"호출 {stats['calls']} / 검색 {stats['searches']}회")
        return "\n".join(ln for ln in lines if ln is not None), stats, details

    except Exception as e:
        logger.error(f"[자가검증] 패스 전체 실패 — 원문 그대로 발행: {e}", exc_info=True)
        return briefing, stats, details


def run_verify_pass(briefing: str, briefing_type: str = "") -> str:
    """구 API — 텍스트만 반환. 제외 항목 DM 은 기존 포맷으로 직접 보낸다(leader_watch 등)."""
    text, _stats, _details = run_verify_pass_ex(briefing, briefing_type, enqueue=True, notify=True)
    return text


if __name__ == "__main__":
    sample = (
        "🏛️ 정치/시사\n"
        "▪ 국회가 이진숙 의원 제명결의안을 가결했다.\n"
        "▪ 홍길동 기재부 장관이 예산안을 발표했다.\n"
        "▪ 코스피가 3,000선을 돌파했다.\n"
        "▪ 날씨가 흐리고 비가 올 것으로 전망된다.\n"
    )
    known = _load_known_names()
    for _, t in parse_items(sample):
        print(f"- {t[:35]:38s} → {tag_item(t, known) or '저위험'}")
