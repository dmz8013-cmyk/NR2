import os
import time
import logging
import feedparser
import anthropic
import requests
from datetime import datetime, time as dtime, timezone, timedelta

KST = timezone(timedelta(hours=9))
from app import create_app, db
from app.models.aesa_article import AesaArticle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# RSS Feeds List (30개 소스)
# 자체 RSS 없는 소스 → Google News RSS 프록시 사용
RSS_FEEDS = {
    # ── 정치·지정학 ──
    'Foreign Policy': 'https://foreignpolicy.com/feed/',
    'Foreign Affairs': 'https://www.foreignaffairs.com/rss.xml',
    'The Diplomat': 'https://thediplomat.com/feed/',
    'Politico': 'https://rss.politico.com/politics-news.xml',
    'Axios': 'https://api.axios.com/feed/',
    'Brookings': 'https://news.google.com/rss/search?q=site:brookings.edu+when:3d&hl=en&gl=US&ceid=US:en',
    'CFR': 'https://news.google.com/rss/search?q=site:cfr.org+when:3d&hl=en&gl=US&ceid=US:en',
    'RAND': 'https://www.rand.org/blog.xml',
    # ── 경제·금융 ──
    'Wall Street Journal': 'https://feeds.a.dj.com/rss/RSSWorldNews.xml',
    'Financial Times': 'https://www.ft.com/rss/home',
    'The Economist': 'https://www.economist.com/the-world-this-week/rss.xml',
    'Bloomberg': 'https://feeds.bloomberg.com/markets/news.rss',
    'Reuters': 'https://news.google.com/rss/search?q=site:reuters.com+when:1d&hl=en&gl=US&ceid=US:en',
    # ── 기술·AI ──
    'MIT Tech Review': 'https://www.technologyreview.com/feed/',
    'Wired': 'https://www.wired.com/feed/rss',
    'Ars Technica': 'https://feeds.arstechnica.com/arstechnica/index',
    # ── 아시아 ──
    'SCMP': 'https://www.scmp.com/rss/91/feed',
    'Nikkei Asia': 'https://news.google.com/rss/search?q=site:asia.nikkei.com+when:1d&hl=en&gl=US&ceid=US:en',
    'Asia Times': 'https://asiatimes.com/feed/',
    'Caixin Global': 'https://news.google.com/rss/search?q=site:caixinglobal.com+when:2d&hl=en&gl=US&ceid=US:en',
    # ── 유럽·중동 ──
    'The Atlantic': 'https://www.theatlantic.com/feed/all/',
    'Al Jazeera': 'https://www.aljazeera.com/xml/rss/all.xml',
    'Der Spiegel Intl': 'https://www.spiegel.de/international/index.rss',
    'Le Monde Diplo': 'https://mondediplo.com/spip.php?page=backend',
    'Arab News': 'https://news.google.com/rss/search?q=site:arabnews.com+when:1d&hl=en&gl=US&ceid=US:en',
    # ── 추가 유력지 ──
    'New York Times': 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
    'The Guardian': 'https://www.theguardian.com/world/rss',
    'Corriere della Sera': 'https://www.corriere.it/rss/homepage.xml',
    'La Repubblica': 'https://www.repubblica.it/rss/homepage/rss2.0.xml',
    'ANSA': 'https://www.ansa.it/sito/notizie/mondo/mondo_rss.xml',
}

# Google News RSS 프록시를 사용하는 소스: entry.link가 Google 리다이렉트 URL일 수 있음
GOOGLE_NEWS_SOURCES = {'Nikkei Asia', 'Reuters', 'Caixin Global', 'Brookings', 'CFR', 'Arab News'}

PROMPT_TEMPLATE = """
다음 뉴스 기사를 분석하여 AESA 4개 렌즈 기준으로 0점부터 10점 사이의 점수를 매겨주세요.

[AESA 4개 렌즈]
[A] AI·기술권력 — AI, 반도체, 빅테크 플랫폼 권력, 기술 패권 경쟁
[B] 국제정치·지정학 — 전쟁, 외교, 동맹 재편, 제재, 영토 분쟁, 패권 경쟁
[C] 문화트렌드 — 세대 변화, 소비 패턴, 미디어·콘텐츠, 사회 운동
[D] 투자·금융·경제권력 — 글로벌 금리·환율·원자재, 중앙은행 정책(Fed/ECB/BOJ/PBOC), 빅테크·방산·에너지 실적·M&A, 헤지펀드·국부펀드 포지션, 무역전쟁·관세·공급망 재편, AI·반도체 투자 흐름, 암호화폐 기관 자금

결과물은 오직 다음 JSON 포맷으로만 반환하세요:
{{
  "score": 0~10의 정수,
  "lenses": ["A", "B", "C", "D"] 중 해당하는 렌즈 배열 (복수 가능),
  "korea_investment_link": true 또는 false (한국 투자시장과 연결고리 존재 여부),
  "korean_summary": "한국 언론 관점에서의 해당 기사 한 줄 요약",
  "korea_insight": "한국 정치·경제·시장 관점 시사점 1~2줄. 이 기사가 한국에 미치는 영향을 코스피·원화·금리·정책·외교·산업 중 해당되는 관점으로 분석. 한국과 직접 관련 없으면 null로 반환.",
  "reason": "점수 부여 이유 (짧게)"
}}

[채점 기준]
- 0~5점: 평범한 뉴스
- 6~8점: [A] [B] [C] [D] 중 하나 이상 관련성이 깊은 경우
- 9~10점: 위 4개 렌즈에 부합하고 파급력이 매우 큰 특종/비공개 분석
* 한국 언론에서 아직 널리 보도되지 않은 각도(Angle)나 신선한 관점(Blind spot)이 존재하면 +2점 보너스
* [D] 렌즈 해당 기사 중 한국 투자시장과 직접 연결고리가 있으면(예: Fed 금리→원달러→코스피, 원자재→한국 수출기업) +1점 보너스

기사 제목: {title}
기사 요약: {summary}
출처: {source}
"""

THREADS_PROMPT_TEMPLATE = """당신은 누렁이(AESA) 브랜드의 Threads 작성자입니다.
아래 기사를 바탕으로 Threads 포스트 초안을 작성하세요.

[AESA 글쓰기 규칙]
- 소제목에 이모지 없음
- 짧고 끊기는 문장, 여운 있게
- "나는 이걸 이렇게 읽는다."로 시작
- 독자에게 불편한 질문 직접 던지기
- 결론 깔끔하게 닫지 않음 (미완 구조)
- 뉴스 요약 아닌 구조 분석·관점
- 마지막 줄: "이상한 나라의 누렁이 🐕"
- 전체 200자 이내

기사 정보:
제목: {title}
요약: {korean_summary}
렌즈: {lenses}
URL: {url}

Threads 초안만 출력하세요. 다른 설명 없이 본문만 작성하세요."""


def generate_threads_draft(title, korean_summary, lenses, url):
    """Claude API로 AESA 스타일 Threads 초안 생성"""
    try:
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
        lens_str = ', '.join(f'[{l}]' for l in lenses) if lenses else '[?]'

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": THREADS_PROMPT_TEMPLATE.format(
                    title=title,
                    korean_summary=korean_summary,
                    lenses=lens_str,
                    url=url
                )
            }]
        )
        draft = response.content[0].text.strip()
        logger.info(f"[AESA Threads] 초안 생성 완료 ({len(draft)}자)")
        return draft
    except Exception as e:
        logger.error(f"[AESA Threads] 초안 생성 실패: {e}")
        return None


def _resolve_google_news_url(entry):
    """Google News RSS entry에서 실제 기사 URL을 추출"""
    link = entry.get('link', '')
    # 기존 코드의 source.get('href')는 개별 기사가 아닌 언론사 '메인 홈페이지' 주소를 반환하여 
    # 모든 새 기사를 중복(dup) 처리하게 만든 원인이었습니다.
    # Google News proxy URL 자체가 기사별 고유값이므로 그대로 반환합니다.
    return link


def _clean_title(title):
    """Google News RSS 제목에서 ' - 소스명' 접미사 제거"""
    # 패턴: "Article Title - Reuters" → "Article Title"
    for suffix in [' - Reuters', ' - Bloomberg', ' - Nikkei Asia',
                   ' - The Japan Times', ' - South China Morning Post',
                   ' - Caixin Global', ' - Brookings Institution',
                   ' - Council on Foreign Relations', ' - Arab News',
                   ' - Brookings', ' - CFR']:
        if title.endswith(suffix):
            return title[:-len(suffix)]
    return title


def process_rss_feeds():
    """5분마다 실행: RSS 수집 → Claude 채점 → DB 저장.
    9점 이상은 즉시 텔레그램 발송, 7~8점은 queued_batch로 대기.
    """
    import json
    app = create_app()
    with app.app_context():
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))

        stats = {}

        for source_name, feed_url in RSS_FEEDS.items():
            logger.info(f"[AESA] Polling RSS: {source_name}")
            source_stats = {'fetched': 0, 'skipped_dup': 0, 'scored': 0, 'urgent_sent': 0, 'queued': 0, 'low_score': 0, 'errors': 0}

            try:
                resp = requests.get(feed_url, timeout=20, headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; AESA-Monitor/1.0)'
                })
                if resp.status_code != 200:
                    logger.error(f"[AESA] {source_name}: HTTP {resp.status_code} — RSS 피드 접근 실패")
                    source_stats['errors'] = 1
                    stats[source_name] = source_stats
                    continue

                feed = feedparser.parse(resp.content)
                entries = feed.entries[:10]
                source_stats['fetched'] = len(entries)

                if not entries:
                    logger.warning(f"[AESA] {source_name}: RSS 파싱 성공하나 entries 0개 (bozo={feed.bozo})")
                    stats[source_name] = source_stats
                    continue

                for entry in entries:
                    if source_name in GOOGLE_NEWS_SOURCES:
                        url = _resolve_google_news_url(entry)
                    else:
                        url = entry.get('link', '')

                    if not url:
                        continue

                    existing = AesaArticle.query.filter_by(url=url).first()
                    if existing:
                        source_stats['skipped_dup'] += 1
                        continue

                    title = _clean_title(entry.get('title', 'No title'))
                    summary_text = entry.get('summary', '') or entry.get('description', '')

                    prompt = PROMPT_TEMPLATE.format(title=title, summary=summary_text[:1500], source=source_name)

                    lenses = []
                    korea_link = False
                    score = 0
                    summary = ""
                    korea_insight = None

                    try:
                        response = client.messages.create(
                            model="claude-sonnet-4-20250514",
                            max_tokens=400,
                            system="당신은 최고 수준의 국제정치, 기술 트렌드, 글로벌 금융 분석가입니다.",
                            messages=[{"role": "user", "content": prompt}]
                        )

                        response_text = response.content[0].text
                        if "{" in response_text and "}" in response_text:
                            start = response_text.find("{")
                            end = response_text.rfind("}") + 1
                            json_str = response_text[start:end]
                            result = json.loads(json_str)
                            score = min(int(result.get("score", 0)), 10)
                            summary = result.get("korean_summary", "")
                            lenses = result.get("lenses", [])
                            korea_link = bool(result.get("korea_investment_link", False))
                            korea_insight = result.get("korea_insight")
                    except Exception as e:
                        logger.error(f"[AESA] {source_name}: Claude API 또는 JSON 파싱 에러: {e}")
                        summary = "분석 실패"
                        source_stats['errors'] += 1

                    lens_tag = ''.join(f'[{l}]' for l in lenses) if lenses else '[?]'
                    source_stats['scored'] += 1
                    logger.info(f"[AESA] {source_name}: score={score} lens={lens_tag} kr_link={korea_link} kr_insight={bool(korea_insight)} | {title[:50]}")

                    now_kst = datetime.now(KST)
                    is_night = dtime(2, 0) <= now_kst.time() < dtime(6, 0)

                    # 9점 이상: 즉시 발송 (긴급 속보) + Threads 초안 동시 발송
                    # 7~8점: 배치 대기열에 적재
                    # 6점 이하: 일간 요약 대기
                    if score >= 9:
                        if is_night:
                            status = 'queued_for_morning'
                        else:
                            send_telegram_alert(source_name, title, url, score, summary,
                                                lenses=lenses, korea_link=korea_link, is_urgent=True, korea_insight=korea_insight)
                            # Threads 초안 생성 및 발송
                            threads_draft = generate_threads_draft(title, summary, lenses, url)
                            if threads_draft:
                                threads_msg = f"✍️ *Threads 초안 (복사용)*\n"
                                threads_msg += "━" * 20 + "\n\n"
                                threads_msg += threads_draft
                                _send_telegram_raw(threads_msg)
                            status = 'sent_urgent'
                            source_stats['urgent_sent'] += 1
                    elif score >= 7:
                        status = 'queued_batch' if not is_night else 'queued_for_morning'
                        source_stats['queued'] += 1
                    else:
                        status = 'queued_for_summary'
                        source_stats['low_score'] += 1

                    article_kwargs = dict(
                        url=url,
                        title=title,
                        source=source_name,
                        score=score,
                        summary=summary,
                        status=status
                    )
                    # lenses/korea_investment_link 컬럼이 아직 없을 수 있음 (마이그레이션 미적용)
                    try:
                        article_kwargs['lenses'] = ','.join(lenses) if lenses else ''
                        article_kwargs['korea_investment_link'] = korea_link
                        article_kwargs['korea_insight'] = korea_insight
                    except Exception:
                        pass

                    article = AesaArticle(**article_kwargs)
                    try:
                        db.session.add(article)
                        db.session.commit()
                    except Exception as db_err:
                        db.session.rollback()
                        # lenses/korea_investment_link 없이 재시도
                        logger.warning(f"[AESA] DB 저장 실패, 기본 컬럼만 재시���: {db_err}")
                        article = AesaArticle(
                            url=url, title=title, source=source_name,
                            score=score, summary=summary, status=status
                        )
                        try:
                            db.session.add(article)
                            db.session.commit()
                        except Exception as retry_err:
                            db.session.rollback()
                            logger.error(f"[AESA] DB 저장 최종 실패: {retry_err}")
                            source_stats['errors'] += 1

            except Exception as e:
                logger.error(f"[AESA] {source_name}: 폴링 중 에러 발생: {e}", exc_info=True)
                source_stats['errors'] += 1

            stats[source_name] = source_stats

        logger.info("[AESA] ========== 폴링 사이클 완료 ==========")
        for src, s in stats.items():
            logger.info(f"[AESA] {src}: fetched={s['fetched']} dup={s['skipped_dup']} scored={s['scored']} urgent={s['urgent_sent']} queued={s['queued']} low={s['low_score']} err={s['errors']}")


def send_batch_alerts():
    """15분마다 실행: queued_batch 상태 기사를 점수순 정렬 → 상위 5개 일괄 발송."""
    app = create_app()
    with app.app_context():
        now_kst = datetime.now(KST)
        is_night = dtime(2, 0) <= now_kst.time() < dtime(6, 0)
        if is_night:
            logger.info("[AESA 배치] 야간 시간대 (KST) — 발송 보류")
            return

        # queued_batch 상태 기사 추출
        candidates = AesaArticle.query.filter_by(status='queued_batch').all()

        if not candidates:
            logger.info("[AESA 배치] 발송 대기 기사 없음")
            return

        # 정렬: 점수 내림차순, 동점이면 최신순
        candidates.sort(key=lambda a: (-a.score, -a.id))
        to_send = candidates[:5]

        logger.info(f"[AESA 배치] {len(candidates)}건 대기 중 → 상위 {len(to_send)}건 발송")

        # 배치 헤더 메시지 발송
        header = f"📡 *AESA 15분 브리핑*\n"
        header += f"⏰ {now_kst.strftime('%H:%M')} KST | {len(to_send)}건 주요 기사\n"
        header += "━" * 20
        _send_telegram_raw(header)

        # 개별 기사 발송
        for item in to_send:
            lenses = item.lenses.split(',') if item.lenses else []
            korea_insight = getattr(item, 'korea_insight', None)
            send_telegram_alert(
                item.source, item.title, item.url, item.score, item.summary,
                lenses=lenses, korea_link=item.korea_investment_link,
                korea_insight=korea_insight
            )
            item.status = 'sent_batch'

        # 나머지 (5개 초과분)는 일간 요약으로 강등
        for item in candidates[5:]:
            item.status = 'queued_for_summary'

        db.session.commit()
        logger.info(f"[AESA 배치] 발송 완료 {len(to_send)}건, 요약 강등 {len(candidates) - len(to_send)}건")

def _send_telegram_raw(text):
    """텔레그램에 raw 텍스트 메시지 발송 (배치 헤더용)"""
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('AESA_TELEGRAM_CHANNEL_ID', os.environ.get('TELEGRAM_CHAT_ID'))
    if not bot_token or not chat_id:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}
        )
    except Exception as e:
        logger.error(f"Telegram raw send error: {e}")


def send_telegram_alert(source, title, url, score, summary,
                        lenses=None, korea_link=False, is_urgent=False, korea_insight=None):
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('AESA_TELEGRAM_CHANNEL_ID', os.environ.get('TELEGRAM_CHAT_ID'))

    if not bot_token or not chat_id:
        logger.warning("Telegram config missing.")
        return

    # 렌즈 태그
    lens_tag = ''.join(f'[{l}]' for l in (lenses or [])) or '[?]'
    kr_flag = " 🇰🇷" if korea_link else ""

    icon = "🚨 [긴급/특종 AESA 알림]" if is_urgent else "🔔 [AESA 주요 알림]"
    text = f"{icon}\n\n"
    text += f"*{source}* (점수: {score}/10)\n"
    text += f"[{title}]({url})\n\n"
    text += f"💡 1줄 요약:\n{summary}\n\n"
    
    if korea_insight:
        text += f"🇰🇷 한국 시사점:\n{korea_insight}\n\n"
        
    text += f"🔍 렌즈: {lens_tag}{kr_flag}"
    
    try:
        api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': False
        }
        response = requests.post(api_url, json=payload)
        if not response.ok:
            logger.error(f"Telegram API Error: {response.text}")
    except Exception as e:
        logger.error(f"Telegram send error: {e}")

def flush_nighttime_queue():
    app = create_app()
    with app.app_context():
        queued = AesaArticle.query.filter_by(status='queued_for_morning').all()
        if not queued:
            logger.info("야간 발송 대기열 비어있음.")
            return
            
        logger.info(f"야간 발송 대기열 {len(queued)}건 발송 시작.")
        for item in queued:
            lenses = item.lenses.split(',') if getattr(item, 'lenses', None) else []
            korea_insight = getattr(item, 'korea_insight', None)
            korea_link = getattr(item, 'korea_investment_link', False)
            send_telegram_alert(
                item.source, item.title, item.url, item.score, item.summary,
                lenses=lenses, korea_link=korea_link, is_urgent=(item.score >= 9),
                korea_insight=korea_insight
            )
            item.status = 'sent'
        db.session.commit()

def send_daily_summary_email():
    app = create_app()
    with app.app_context():
        # 어제/오늘 사이클의 요약. 점수 6 이하 위주 + 전체
        from datetime import timedelta
        yesterday = datetime.now() - timedelta(days=1)
        items = AesaArticle.query.filter(
            AesaArticle.status == 'queued_for_summary',
            AesaArticle.created_at >= yesterday
        ).order_by(AesaArticle.score.desc()).all()
        
        if not items:
            return
            
        logger.info(f"Daily summary {len(items)} items email send...")
        from flask_mail import Message
        from app import mail
        
        html_content = "<h2>AESA 일간 해외언론 모니터링 요약 (6점 이하 잔여 기사)</h2>"
        for i, item in enumerate(items, 1):
            html_content += f"<p>{i}. <b>[{item.source}]</b> <a href='{item.url}'>{item.title}</a> (Score: {item.score})<br/>{item.summary}</p>"
        
        recipients_str = os.environ.get('AESA_EMAIL_RECIPIENTS', os.environ.get('ADMIN_EMAIL', ''))
        recipients = [r.strip() for r in recipients_str.split(',') if r.strip()]
        
        if not recipients:
            logger.warning("No email recipients configured for daily summary.")
            return

        msg = Message("AESA 해외언론 일간 요약 브리핑", recipients=recipients, html=html_content)
        try:
            mail.send(msg)
            for item in items:
                item.status = 'sent_summary'
            db.session.commit()
            logger.info("Daily summary sent successfully.")
        except Exception as e:
            logger.error(f"Failed to send daily summary: {e}")

def send_daily_content_report():
    """매일 오전 7시 실행: 전날 수집 기사 중 영상 콘텐츠 후보 TOP3 텔레그램 발송."""
    import json
    app = create_app()
    with app.app_context():
        from datetime import timedelta

        # 전날 00:00 ~ 23:59 KST
        now = datetime.now()
        yesterday_start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_end = yesterday_start.replace(hour=23, minute=59, second=59)

        candidates = AesaArticle.query.filter(
            AesaArticle.created_at >= yesterday_start,
            AesaArticle.created_at <= yesterday_end,
            AesaArticle.score >= 7
        ).order_by(AesaArticle.score.desc()).limit(20).all()

        if not candidates:
            logger.info("[AESA 콘텐츠] 전날 7점+ 기사 없음 — 스킵")
            return

        # Claude에 전달할 기사 목록 구성
        articles_for_prompt = []
        for a in candidates:
            articles_for_prompt.append({
                "title": a.title,
                "source": a.source,
                "score": a.score,
                "summary": a.summary or "",
                "lenses": a.lenses.split(',') if a.lenses else [],
                "url": a.url
            })

        articles_json = json.dumps(articles_for_prompt, ensure_ascii=False, indent=2)

        prompt = f"""당신은 누렁이 AESA 유튜브 채널의 콘텐츠 디렉터입니다.
아래 기사 목록에서 유튜브 영상으로 만들기 가장 좋은 TOP3를 선정하세요.

[AESA 콘텐츠 3가지 조건 — 동시 충족 필수]
① 첨예성: 통념을 뒤집는 도발
② 철학적 깊이: 권력·문명·전략의 인사이트
③ 10만 훅: 선언적·도발적 제목 프레이밍

[4개 렌즈]
[A] AI·기술권력
[B] 국제정치·지정학
[C] 문화트렌드
[D] 투자·금융·경제권력

각 후보마다 아래 JSON 형식으로 출력:
{{
  "rank": 1,
  "title_candidates": ["제목1 (훅 포함)", "제목2 (훅 포함)"],
  "core_angle": "핵심 앵글 1~2줄",
  "lenses": ["B", "D"],
  "reason": "선정 이유 1줄",
  "source": "출처 언론사",
  "original_title": "원문 제목"
}}

JSON 배열로만 응답. 다른 텍스트 없음.

기사 목록:
{articles_json}"""

        try:
            client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text.strip()
            # JSON 배열 추출
            if "[" in response_text and "]" in response_text:
                start = response_text.find("[")
                end = response_text.rfind("]") + 1
                top3 = json.loads(response_text[start:end])
            else:
                logger.error("[AESA 콘텐츠] Claude 응답에서 JSON 배열 파싱 실패")
                return

        except Exception as e:
            logger.error(f"[AESA 콘텐츠] Claude API 에러: {e}")
            return

        # 텔레그램 메시지 구성
        date_str = yesterday_start.strftime('%Y.%m.%d')
        msg = f"🎬 *AESA 영상 콘텐츠 후보 TOP3*\n"
        msg += f"📅 {date_str} 수집 기사 기준\n"
        msg += "━" * 20 + "\n"

        for item in top3[:3]:
            rank = item.get("rank", "?")
            titles = item.get("title_candidates", [])
            angle = item.get("core_angle", "")
            lenses_list = item.get("lenses", [])
            reason = item.get("reason", "")
            source = item.get("source", "")
            original = item.get("original_title", "")

            lens_tag = ''.join(f'[{l}]' for l in lenses_list)
            title_lines = '\n'.join(f'   • {t}' for t in titles)

            msg += f"\n*#{rank}* {lens_tag}\n"
            msg += f"📰 원문: {original}\n"
            msg += f"   출처: {source}\n"
            msg += f"🎯 앵글: {angle}\n"
            msg += f"✏️ 제목 후보:\n{title_lines}\n"
            msg += f"💬 선정 이유: {reason}\n"
            msg += "─" * 18 + "\n"

        msg += "\n_※ 제목은 초안입니다. 최종 선택은 PD 판단._"

        _send_telegram_raw(msg)
        logger.info(f"[AESA 콘텐츠] TOP3 발송 완료 (대상 기사 {len(candidates)}건)")


if __name__ == "__main__":
    process_rss_feeds()
