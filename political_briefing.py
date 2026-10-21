"""
정치 브리핑 봇 - 네이버 뉴스 검색 API + Claude 요약 + 텔레그램 발송
오후 1시: 당일 09시~13시 정치 기사 요약
오후 10시: 당일 13시~22시 정치 기사 요약 (실시간 랭킹 상위 위주)
"""

import os
import json
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
import pytz

logger = logging.getLogger(__name__)

# ─── 환경변수 ───
NAVER_CLIENT_ID = os.environ.get('NAVER_CLIENT_ID', '')
NAVER_CLIENT_SECRET = os.environ.get('NAVER_CLIENT_SECRET', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
TELEGRAM_BOT_TOKEN = os.environ.get('NUREONGI_NEWS_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

KST = pytz.timezone('Asia/Seoul')

# ─── 검색 키워드 ───
SEARCH_QUERIES = [
    "이재명 대통령",
    "더불어민주당",
    "이재명 정부",
    "국민의힘",
    "보수 야당",
    "국회 법안",
    "한미 외교",
    "검찰 수사",
    "정치 속보",
    "여야 대치",
]


def search_naver_news(query, display=10, sort='date'):
    """네이버 뉴스 검색 API 호출"""
    try:
        params = urllib.parse.urlencode({'query': query, 'display': display, 'sort': sort})
        url = f"https://openapi.naver.com/v1/search/news.json?{params}"

        req = urllib.request.Request(url)
        req.add_header("X-Naver-Client-Id", NAVER_CLIENT_ID)
        req.add_header("X-Naver-Client-Secret", NAVER_CLIENT_SECRET)

        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('items', [])
    except Exception as e:
        logger.error(f"네이버 검색 실패 [{query}]: {e}")
        return []


import re as _re
BREAKING_RE = _re.compile(r"(북한|미사일|합참|속보|단독|탄핵|계엄)")
LAST_ARTICLES: list = []          # 직전 수집 기사 풀 (섹션 채움·출처 매칭·반박 보강용)
LAST_TIMELINESS_EXCLUDED: list = []
LAST_TIMELINESS_LENIENT: list = []
LAST_AGE_DROPPED: list = []       # 24h 하드 필터로 제거된 기사 (회차 DM 표기용)


def collect_political_news(is_afternoon=True):
    """
    정치 뉴스 수집
    is_afternoon=True: 오후 1시 브리핑 (09시~13시 기사)
    is_afternoon=False: 오후 10시 브리핑 (13시~22시 기사)
    """
    now = datetime.now(KST)

    all_articles = []
    seen_titles = set()

    for query in SEARCH_QUERIES:
        items = search_naver_news(query, display=40, sort='date')   # 창 확대(전판 마감 이후 전체)에 맞춰 40건

        for item in items:
            title = item.get('title', '').replace('<b>', '').replace('</b>', '').replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            description = item.get('description', '').replace('<b>', '').replace('</b>', '').replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            link = item.get('originallink', '') or item.get('link', '')
            pub_date_str = item.get('pubDate', '')

            title_key = title[:30]
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            try:
                pub_date = datetime.strptime(pub_date_str, '%a, %d %b %Y %H:%M:%S %z')
                pub_date_kst = pub_date.astimezone(KST)
            except Exception:
                continue

            # 수집 창 = 직전 판 마감 이후 전체 (2026-10-12): 13:00판 = 전날 22:00 ~ 지금, 22:00판 = 13:00 ~ 지금.
            # 이전 판에 이미 실린 기사는 prior_coverage 가 제외한다.
            if is_afternoon:
                start_time = (now - timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)
            else:
                start_time = now.replace(hour=13, minute=0, second=0, microsecond=0)
            end_time = now

            if start_time <= pub_date_kst <= end_time:
                all_articles.append({
                    'title': title,
                    'description': description,
                    'link': link,
                    'pub_date': pub_date_kst,
                    'query': query,
                    'breaking': bool(BREAKING_RE.search(title)),
                })

    # 속보(북한·미사일·합참·속보·단독·탄핵·계엄) 우선 → 최신순. 상위 60건
    all_articles.sort(key=lambda x: (not x.get('breaking', False), -x['pub_date'].timestamp()))
    all_articles = all_articles[:60]

    # 시의성 필터 (공통): 발행일 ∈ {오늘, 전일} 만 통과 — 네이버 pubDate 가 재색인 시각일 때
    # 옛 기사가 '오늘' 로 들어오는 경우는 기사 HTML 메타(회당 ≤30건) 로 재확인
    global LAST_TIMELINESS_EXCLUDED, LAST_TIMELINESS_LENIENT
    LAST_TIMELINESS_EXCLUDED = []
    LAST_TIMELINESS_LENIENT = []
    try:
        import timeliness as _tl
        all_articles, LAST_TIMELINESS_EXCLUDED = _tl.filter_timely(all_articles, cross_check=True)
        LAST_TIMELINESS_LENIENT = list(_tl.LAST_LENIENT)
    except Exception as te:
        logger.error(f"[시의성] 필터 실패 — 윈도우 필터만 적용: {te}")

    # 타임라인 필터 2차 검증 (절대 상한 체크)
    try:
        from timeline_filter import filter_naver_articles
        btype = 'political_afternoon' if is_afternoon else 'political_evening'
        before_count = len(all_articles)
        all_articles = filter_naver_articles(
            all_articles, start_time, end_time, briefing_type=btype
        )
        if len(all_articles) < before_count:
            logger.warning(
                f"[타임라인 필터] {before_count}건 → {len(all_articles)}건 "
                f"(구식 {before_count - len(all_articles)}건 제거)"
            )
    except Exception as tf_err:
        logger.error(f"[타임라인 필터] 실행 실패: {tf_err}")

    # 24h 하드 필터 (최종 방어선, 2026-10-19): 위 필터를 어떤 경로로 통과했든
    # 발행 24h 초과 기사는 여기서 무조건 제거한다. 시각 미상은 완화 모드에서만 통과.
    global LAST_AGE_DROPPED
    LAST_AGE_DROPPED = []
    try:
        import timeliness as _tl2
        kept = []
        for a in all_articles:
            pd = a.get("pub_date_kst") or a.get("pub_date_resolved") or a.get("pub_date")
            if pd is None and a.get("timeliness_lenient"):
                kept.append(a)
                continue
            if _tl2.within_max_age(pd, now):
                kept.append(a)
            else:
                hrs = _tl2.age_hours(pd, now)
                LAST_AGE_DROPPED.append({"title": a.get("title", ""),
                                         "age_hours": round(hrs, 1) if hrs is not None else None})
        if len(kept) < len(all_articles):
            logger.warning(f"[24h 하드] {len(all_articles)}건 → {len(kept)}건 "
                           f"(24h 초과 {len(all_articles) - len(kept)}건 제거: "
                           f"{[d['title'][:26] for d in LAST_AGE_DROPPED[:3]]})")
        all_articles = kept
    except Exception as he:
        logger.error(f"[24h 하드] 적용 실패: {he}")

    global LAST_ARTICLES
    LAST_ARTICLES = list(all_articles)
    logger.info(f"수집된 정치 기사: {len(all_articles)}개 ({'오후' if is_afternoon else '저녁'}, "
                f"속보 {sum(1 for a in all_articles if a.get('breaking'))}건, 창 {start_time:%m/%d %H:%M}~{end_time:%H:%M})")
    return all_articles


def generate_political_briefing(articles, is_afternoon=True):
    """Claude API로 정치 브리핑 생성"""
    if not articles:
        logger.warning("수집된 기사가 없어 브리핑 생성 불가")
        return None

    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY 없음")
        return None

    now = datetime.now(KST)
    today_str = now.strftime('%y%m%d')
    time_label = "13:00" if is_afternoon else "22:00"
    time_range = "전날 22시~13시" if is_afternoon else "13시~22시"

    news_block = ""
    for i, article in enumerate(articles, 1):
        label = article.get('pub_label') or (article['pub_date'].strftime('%m/%d %H:%M') if article.get('pub_date') else '')
        flag = "【속보·우선】 " if article.get('breaking') else ""
        news_block += f"{i}. {flag}[{article['title']}] (발행 {label})\n   {article['description'][:150]}\n\n"

    # 팩트 컨텍스트 자동 주입
    try:
        from fact_checker import get_fact_context
        fact_context = get_fact_context()
    except Exception:
        fact_context = ""

    # 항목 종결 허용 술어 — config/briefing_layout.json 한 곳에서 관리 (두 봇 공유)
    try:
        from briefing_layout import allowed_endings
        allowed_endings_str = ', '.join(allowed_endings())
    except Exception:
        allowed_endings_str = '확정, 체결, 비판, 기각'

    prompt = f"""{fact_context}당신은 한국 정치 전문 뉴스 브리핑 AI입니다.
아래 {len(articles)}개의 정치 뉴스 기사를 분석하여 텔레그램용 정치 브리핑을 작성하세요.

[포맷 - 반드시 정확히 따르세요. 한 글자도 빠짐없이 이 구조를 지키세요]

🔥【한방에 정리하는 정치권 이슈 - 반박시니말이맞음({today_str} {time_label})】🔥
[여기에 기사 내용을 종합한 자극적이고 핵심을 찌르는 한줄 제목을 작성 - 반드시 위 🔥 줄과 별도의 두번째 줄에 작성할 것]

⸻⸻⸻⸻

🇰🇷 이재명 정부 🇰🇷
(이재명 대통령/정부 관련 주요 이슈 3~5개를 각각 '▪'로 시작하여 한줄 요약)

⸻⸻⸻⸻

🟦 더불어민주당 🟦
(당 내부 이슈, 의원 동향 등 3~5개를 '▪'로 요약)

⸻⸻⸻⸻

🟥 국민의힘 🟥
(국민의힘 관련 이슈 3~5개를 '▪'로 요약)

⸻⸻⸻⸻

🎸 비교섭단체 및 기타 정치 🪕
(조국혁신당, 개혁신당, 새로운미래, 기타 정치 이슈 2~4개를 '▪'로 요약)

⸻⸻⸻⸻

🌐 법조 및 국제 🌐
(검찰 수사, 법원 판결, 외교, 국제 이슈 중 정치 관련 2~4개를 '▪'로 요약)

[작성 규칙]
1. 각 항목은 '▪'로 시작하는 1줄 요약 (핵심만). 섹션 헤더 아래 구분선(─────) 금지
2. 말투는 단정하고 날카롭게 (예: "~로 파장", "~논란 점화", "~세 과시").
   전언·풍문 술어 절대 금지: '전해졌다/전해짐/전해진다', '알려졌다/알려짐',
   '~로 보인다', '~는 관측' — 확인된 사실만. 항목 종결은 명사형(…음/됨/임)
   또는 사실 서술 술어로 통일 (허용 예: {allowed_endings_str})
2-1. 출처·참고 링크 블록은 시스템이 발송 시 자동 삽입 — 본문에 '출처:'·URL 줄 금지
3. 마침표 세 개(...) 대신 반드시 유니코드 말줄임표(…)를 사용
4. 제공된 기사 제목과 요약을 최대한 활용하여 브리핑을 작성하세요. 기사에 없는 내용을 지어내지는 말되, 제목에서 충분히 유추 가능한 내용은 자연스럽게 서술하세요.
5. 각 섹션에 해당 기사가 부족하면 1개까지 줄여도 됨. 해당 섹션에 기사가 전혀 없으면 "금일 주요 보도 없음"으로 짧게 처리
6. 총 분량: 텔레그램 한 메시지에 맞게 (3500자 이내)
7. 제목은 반드시 자극적이고 흥미를 유발하는 문구로
8. 첫 줄 🔥【한방에 정리하는 정치권 이슈 - 반박시니말이맞음(...)】🔥는 절대 수정하지 말것. 이 줄은 고정 텍스트이며 자극적 제목은 반드시 그 다음 줄에 별도로 작성
9. "정보가 부족합니다", "브리핑을 작성할 수 없습니다" 같은 거부 메시지는 절대 출력하지 마세요. 기사가 적더라도 반드시 위 포맷대로 브리핑을 완성하세요.
10. [팩트 정확도] 기사 제목과 요약에 명시된 내용만 사용하세요. 기사에 없는 감정("심기불편", "분노"), 반응, 발언을 지어내지 마세요. 사실 기반 서술만 허용됩니다.
11. [시의성] 각 기사 제목 뒤 (발행 MM/DD HH:MM)은 발행 시각입니다. 오늘({now.strftime('%m/%d')})·전일 발행 기사만 쓰고,
    전일 이전 기사는 사용 금지. 기억 속 과거 사건·발언을 오늘 일처럼 쓰지 마세요. "최근", "지난달" 등 모호한 시점 대신 구체적 시점으로.
11-1. [속보 우선] 【속보·우선】 표시 기사(북한·미사일·합참·속보·단독·탄핵·계엄)는 반드시 반영하고 해당 섹션의 1~2번째 항목으로 배치.
     최상위 속보는 두 번째 줄 한줄 제목에도 반영할 것.
11-2. [섹션 분량] 섹션마다 기사가 있으면 최소 2개, 최대 5개. 한 정당 섹션의 쟁점에 상대 당 반박 기사가 있으면 함께 실을 것.
11-3. [문체] 항목 종결은 '~다/했다/밝혔다' 금지 — 명사형(…음/됨/임) 또는 사실 서술 술어만.
12. [인명 규칙] 기사에 없는 인물·직책을 만들지 마세요. 발언 주체가 기사에 명시되지 않으면 이름을 빼고 직명·기관명만 쓰세요.
    사전에 없는 인물의 직함은 기사 원문 표기 그대로만 쓰고, 추측으로 채우지 마세요.
13. [섹션 귀속] 항목을 넣을 섹션은 '기사에 등장한 정당'이 아니라 '발언·행위 주체의 소속'으로 정하세요.
    · 국회의원 발언 → 그 의원의 소속 정당 섹션. 겨냥된 상대 당 섹션이 아닙니다.
    · 공무원·검찰·법원(공소청장·검사·판사·대법원장 등) 주체 → 🌐 법조 및 국제 섹션. 정당 섹션 금지.
    · 국정감사 항목은 질의한 의원의 소속으로 분류하고, 피감기관의 답변·해명이 주어인 항목은 법조 또는 이재명 정부로.
14. [동사 과장 금지] 원문에 없는 동사로 강도를 올리지 마세요. '적발·폭로·전격·선언·강행·졸속'은
    기사 원문에 그 단어가 있을 때만 사용하고, 없으면 원문이 쓴 동사(집계·확인·발표·지적·제기 등)를 그대로 쓰세요.
    예: 원문이 '확정손실 집계'면 '적발'로 바꾸지 말 것. 원문에 없는 의혹 프레임('졸속 심사 의혹')을 덧붙이지 말 것.
15. [수치 규칙] 숫자는 기사 원문 문자열에 그대로 있는 것만 쓰세요. 비율·금액·건수를 추정·환산·반올림해 새로
    만들지 마세요. 원문에 없는 수치(예: '건조대금 10%')는 수치를 빼고 서술하거나 그 항목을 쓰지 마세요.
16. [외신 고유명사] 외신·국제 항목의 인물명과 직함은 기사 원문 표기를 그대로 유지하세요. 직함을 한국어로
    의역하지 마세요. 예: '가지야마 자민당 총무회장'을 '관리인'으로 바꾸면 오역입니다. 원 표기가 불확실하면 이름만 쓰세요.
17. [입장·단계 동사] 누가 무엇에 대해 어떤 입장이었는지 기사와 그대로 맞추세요.
    · 반박/비판/옹호/지지/규탄은 기사에 그 동사가 있을 때만. 반박한 발언을 '비판'으로 바꾸지 말 것.
    · '검토'를 '추진·확정·결정'으로 올리지 말 것. 기사가 쓴 단계 그대로.
18. [대상 기준] 중앙정치·국회·정부·법조가 우선입니다. 지방의원·기초단체장의 단순 일정(현장 점검, 개소식,
    간담회 참석, 위문, 축사 등)은 쓰지 마세요. 중앙 사안과 직접 얽힌 경우만 예외입니다.
19. [여론조사] 지지율·여론조사 수치를 쓸 때는 조사기관명을 반드시 함께 쓰세요(예: '리얼미터 조사에서 42%').
    조사기관을 알 수 없으면 그 수치를 쓰지 말고 항목 자체를 빼세요.
20. [헤드라인] 두 번째 줄 한줄 제목도 기사에 있는 사실만 씁니다. 기사에 없는 동사로 강도·단계를 올리지 말고,
    '~가다/~하다' 같은 어색한 종결로 끝내지 마세요.

[오늘 {time_range} 정치 뉴스]
{news_block}"""

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=3000,
            messages=[{"role": "user", "content": prompt}]
        )

        briefing = response.content[0].text
        logger.info(f"정치 브리핑 생성 완료: {len(briefing)}자")
        return briefing

    except Exception as e:
        logger.error(f"Claude API 오류: {e}")
        return None


def _split_text(text, limit=4096):
    """텍스트를 limit 이하 청크로 분할. 줄바꿈 기준으로 자른다."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return chunks


def send_telegram_message(text):
    """텔레그램으로 메시지 전송. 4096자 초과 시 분할 전송."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("텔레그램 설정 없음")
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        chunks = _split_text(text)

        for i, chunk in enumerate(chunks, 1):
            data = json.dumps({
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "disable_web_page_preview": True,
            }).encode('utf-8')

            req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})

            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                if result.get('ok'):
                    logger.info(f"텔레그램 전송 성공 ({i}/{len(chunks)})")
                else:
                    logger.error(f"텔레그램 전송 실패: {result}")
                    return False

        return True

    except Exception as e:
        logger.error(f"텔레그램 전송 오류: {e}")
        return False


def send_political_briefing(is_afternoon=True):
    """정치 브리핑 메인 함수"""
    period = "오후 1시" if is_afternoon else "오후 10시"
    logger.info(f"=== 정치 브리핑 시작 ({period}) ===")

    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.error("네이버 API 키 없음")
        return
        
    # 중복 체크 로직 추가
    try:
        from app import create_app
        from app.models.briefing import Briefing as BriefingModel
        _app = create_app()
        with _app.app_context():
            btype = 'political_afternoon' if is_afternoon else 'political_evening'
            today_start = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
            if not is_afternoon:
                today_start = today_start.replace(hour=12) # 저녁 브리핑은 12시 이후
                
            existing = BriefingModel.query.filter(BriefingModel.briefing_type == btype, BriefingModel.created_at >= today_start).first()
            if existing:
                logger.warning(f"이미 오늘 {period} 브리핑이 존재합니다. 중복 생성 방지.")
                return
    except Exception as e:
        logger.error(f"중복 체크 실패: {e}")

    btype = 'political_afternoon' if is_afternoon else 'political_evening'
    from run_report import RunReport
    report = RunReport(btype)

    articles = collect_political_news(is_afternoon=is_afternoon)
    report.timeliness_excluded = list(LAST_TIMELINESS_EXCLUDED)
    report.timeliness_lenient = list(LAST_TIMELINESS_LENIENT)
    report.age_dropped = list(LAST_AGE_DROPPED)

    if not articles:
        logger.warning(f"수집된 기사 없음 - {period} 브리핑 건너뜀")
        report.extra.append("수집 기사 0건 — 브리핑 생략")
        report.send()
        return

    # 재검색 큐(politics) — 이전 회차 미확인 실명 발언 재검색 (생성 전)
    restored_items = []
    try:
        from recheck_queue import process_queue
        from verify_pass import make_verifier
        vf = make_verifier()
        if vf:
            restored_items, discarded, qdetails = process_queue("politics", vf)
            report.restored = [t[:80] for _, t in restored_items]
            report.discarded = [t[:80] for t in discarded]
            report.searches += sum(d.get("searches", 0) for d in qdetails)
            report.calls += len(qdetails)
    except Exception as qe:
        logger.warning(f"[재검색큐] 처리 실패(무시): {qe}")

    briefing = generate_political_briefing(articles, is_afternoon=is_afternoon)

    if not briefing:
        logger.error("브리핑 생성 실패")
        return

    # 헤드라인 프레임 귀속 — 2번째 줄 정파 프레임 어휘에 발화 주체 부착(2회 실패 시 어휘 삭제)
    try:
        from headline_guard import apply_to_briefing as _fix_headline
        _hl_client = None
        try:
            import anthropic as _an
            _hl_client = _an.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
        except Exception:
            pass
        briefing, hl_info = _fix_headline(briefing, _hl_client)
        if hl_info.get("words"):
            report.headline_fixed = [f"{hl_info['original'][:40]} → {'어휘 삭제' if hl_info.get('stripped') else '귀속 재생성'} "
                                     f"({'·'.join(hl_info['words'])}, 시도 {hl_info.get('attempts', 0)})"]
    except Exception as hl_err:
        logger.warning(f"[제목귀속] 실패(무시): {hl_err}")

    # 팩트체크 — 발송 전 인물·직책 오류 자동 감지·수정
    try:
        from fact_checker import run_fact_check, auto_fix
        fc_result = run_fact_check(briefing)
        if not fc_result["passed"]:
            logger.warning(f"[팩트체크 오류] {fc_result['errors']}")
            briefing = auto_fix(briefing)

            # 관리자에게 수정 내역 별도 알림
            admin_msg = "⚠️ <b>정치 브리핑 팩트 자동수정</b>\n\n"
            for err in fc_result["errors"]:
                admin_msg += f"• '{err['found']}' → '{err['should_be']}'\n"
                admin_msg += f"  문맥: {err.get('context', '')}\n"
            try:
                from app.utils.telegram_notify import send_to_admin
                send_to_admin(admin_msg)
            except Exception:
                pass
        else:
            logger.info("[팩트체크] 오류 없음 — 통과")
    except Exception as fc_err:
        logger.error(f"[팩트체크] 실행 실패 (브리핑은 그대로 발송): {fc_err}")

    # 전판 기보도 제거 (검증 전 — 검색 비용 지출 전에 제거)
    prior = []
    try:
        from prior_coverage import load_recent_items, filter_prior_coverage
        prior = load_recent_items(exclude_type=btype)
        briefing, pex, pkeep = filter_prior_coverage(briefing, prior)
        report.prior_excluded, report.prior_kept = pex, pkeep
    except Exception as pc_err:
        logger.warning(f"[기보도] 제거 실패(무시): {pc_err}")

    # 발행 전 자가 검증 패스 — 실명 발언·사전 밖 인명 직함·수치 (회당 상한 14, 2026-10-07 추가)
    #   확인불가 실명 발언은 제외 + recheck_queue(politics) 적재, stale/존재 불명은 제외
    vdetails = {}
    try:
        from verify_pass import run_verify_pass_ex
        briefing, vstats, vdetails = run_verify_pass_ex(briefing, briefing_type=btype)
        report.queued = vdetails.get("queued", [])
        report.stale = vdetails.get("stale", [])
        report.unknown = vdetails.get("unknown", [])
        report.unconfirmed_dropped = vdetails.get("excluded", [])
        report.calls += vstats.get("calls", 0)
        report.searches += vstats.get("searches", 0)
    except Exception as vp_err:
        logger.error(f"[자가검증] 패스 실행 실패 — 스킵하고 발행: {vp_err}")

    report.record_dropped = vdetails.get("record_dropped", [])
    report.source_added = vdetails.get("source_added", [])
    report.source_dropped = vdetails.get("source_dropped", [])

    # 당적 사전 기반 섹션 배치 검증 — 첫 실명 주체의 당적과 섹션 불일치면 이동, 대상 섹션 없으면 삭제
    try:
        from section_guard import enforce_sections
        briefing, report.section_moved, report.section_dropped = enforce_sections(briefing)
    except Exception as sg_err:
        logger.warning(f"[섹션검증] 실패(무시): {sg_err}")

    # 큐 복귀 항목 삽입 (검증 직후·레이아웃 전)
    for sec, txt in restored_items:
        try:
            from recheck_queue import insert_into_section
            briefing = insert_into_section(briefing, sec, txt)
        except Exception as ie:
            logger.warning(f"[재검색큐] 복귀 삽입 실패: {ie}")

    # 섹션 가드 (2026-10-12 13:00판 빈 섹션 사고): 출처 매칭 → 속보 강제 → 빈/부족 섹션 채움 → 반박 보강 → 상한 → 문체
    try:
        import section_fill as sf, style_fix
        _gc = None
        try:
            import anthropic as _an2
            _gc = _an2.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
        except Exception:
            pass
        pool = list(LAST_ARTICLES) or list(articles)
        briefing, report.source_dropped_items = sf.source_match_guard(briefing, pool)
        # 원문 대조 — 과장 동사(적발/폭로/전격/선언)·원문 밖 수치 교정 (2026-10-19)
        try:
            import grounding
            briefing, report.grounding_notes = grounding.apply(briefing, pool)
        except Exception as ge:
            logger.warning(f"[원문대조] 실패(무시): {ge}")
        briefing, report.breaking_notes = sf.enforce_breaking(briefing, pool, _gc)
        prior_titles = [p["text"] for p in prior]
        briefing, report.fill_notes = sf.fill_empty_sections(briefing, pool, _gc, prior_titles)
        briefing, report.rebuttal_notes = sf.enforce_rebuttal(briefing, pool, _gc)

        # ── 생성 단계(속보·채움·반박) 뒤 최종 관문 (2026-10-21 결함1·2·3·4)
        #    이 세 단계는 LLM 이 새 항목을 만들어 넣는다. 기존에는 출처 매칭·원문 대조가
        #    이보다 앞에서만 돌아, 생성 항목이 검증 없이 발행됐다(16건 중 6건 출처 불명).
        try:
            import entity_registry as _er
            briefing, report.policy_notes = _er.policy_gate(briefing)
        except Exception as pe:
            logger.warning(f"[정책게이트] 실패(무시): {pe}")
        try:
            import grounding
            briefing, gnotes2 = grounding.apply(briefing, pool)
            report.grounding_notes += gnotes2
        except Exception as ge2:
            logger.warning(f"[원문대조2] 실패(무시): {ge2}")
        try:
            import source_bind
            briefing, report.bound_items, report.unbound_dropped = source_bind.bind(briefing, pool)
        except Exception as be:
            logger.error(f"[출처결속] 실패(무시): {be}")
        briefing, empty_notes = sf.mark_empty_sections(briefing)
        report.fill_notes += empty_notes

        briefing, cap_notes = sf.cap_sections(briefing)
        report.fill_notes += cap_notes
        briefing, report.style_notes = style_fix.fix_style(briefing, _gc)
        # 헤드라인은 style_fix(▪ 줄만)·headline_guard(프레임 어휘만) 어디서도
        # 사실 대조를 받지 않았다 → 수집 풀과 동사·종결 대조 (결함5)
        try:
            from grounding import check_headline
            _hl = [i for i, ln in enumerate(briefing.split("\n")) if ln.strip().startswith("🔥")]
            if _hl:
                _lines = briefing.split("\n")
                for j in range(_hl[0] + 1, min(_hl[0] + 4, len(_lines))):
                    if _lines[j].strip():
                        fixed, hnotes = check_headline(_lines[j].strip(), pool)
                        if hnotes:
                            _lines[j] = fixed
                            report.headline_fixed += hnotes
                            briefing = "\n".join(_lines)
                        break
        except Exception as he:
            logger.warning(f"[헤드라인 대조] 실패(무시): {he}")
        report.section_counts = sf.section_counts(briefing)
        if any(sf.HARD_RE.search(a.get("title", "")) for a in pool):
            from headline_guard import ensure_breaking_in_headline
            briefing, hb = ensure_breaking_in_headline(briefing, [a.get("title", "") for a in pool if sf.HARD_RE.search(a.get("title", ""))][:1], _gc)
            if hb:
                report.headline_fixed.append(hb)
    except Exception as sf_err:
        logger.error(f"[섹션가드] 실패(무시): {sf_err}", exc_info=True)

    # 공용 레이아웃 — 헤더(출처 2링크)·푸터(참고 2링크)·섹션 간격 재조립
    # (config/briefing_layout.json, 정보공유방 브리핑과 동일 템플릿)
    try:
        from briefing_layout import apply_layout
        briefing = apply_layout(briefing)
    except Exception as lay_err:
        logger.error(f"[레이아웃] 적용 실패 — 원문 발송: {lay_err}")

    success = send_telegram_message(briefing)
# DB 저장
    try:
        from app import create_app, db
        from app.models.briefing import Briefing as BriefingModel
        _app = create_app()
        with _app.app_context():
            btype = 'political_afternoon' if is_afternoon else 'political_evening'
            first_line = briefing.split('\n')[0][:200]
            record = BriefingModel(
                briefing_type=btype,
                title=first_line,
                content=briefing,
                article_count=len(articles),
            )
            db.session.add(record)
            db.session.commit()
            logger.info(f"정치 브리핑 DB 저장 완료 (id={record.id})")
            # 채널 알림
            # send_telegram_message 에서 이미 전문 발송이 완료되었으므로 주석 처리
            # (중복 및 짤린 메시지 발송 방지)
            # try:
            #     from app.utils.telegram_notify import notify_new_briefing
            #     notify_new_briefing(record)
            # except Exception as ne:
            #     logger.error(f"정치 브리핑 채널 알림 실패: {ne}")
    except Exception as e:
        logger.error(f"정치 브리핑 DB 저장 실패: {e}")
    if success:
        logger.info(f"=== 정치 브리핑 완료 ({period}) ===")
    else:
        logger.error(f"=== 정치 브리핑 전송 실패 ({period}) ===")
        report.extra.append("⚠️ 텔레그램 전송 실패")
    try:
        report.send()
    except Exception as re_err:
        logger.warning(f"[회차요약] 전송 실패(무시): {re_err}")


def afternoon_political_briefing():
    """오후 1시 브리핑"""
    send_political_briefing(is_afternoon=True)


def evening_political_briefing():
    """오후 10시 브리핑"""
    send_political_briefing(is_afternoon=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("정치 브리핑 테스트 실행...")
    send_political_briefing(is_afternoon=True)
