"""주간 편향 리포트 생성 및 텔레그램 전송"""
import os
import requests
from datetime import datetime, timedelta
from collections import defaultdict


def generate_weekly_report():
    """최근 7일 편향 데이터를 분석하여 리포트를 생성한다.

    Returns:
        dict with keys: top_clusters, top_conservative, top_progressive,
                       most_divided_cluster, telegram_text, generated_at
    """
    from app.models.bias import NewsArticle, ArticleCluster
    from app import db

    cutoff = datetime.now() - timedelta(days=7)

    # --- 1. 클러스터 크기 TOP 3 ---
    articles = NewsArticle.query.filter(
        NewsArticle.created_at >= cutoff,
    ).all()

    cluster_counts = defaultdict(list)
    for a in articles:
        if a.cluster_id:
            cluster_counts[a.cluster_id].append(a)

    top_clusters = []
    if cluster_counts:
        sorted_clusters = sorted(cluster_counts.items(), key=lambda x: len(x[1]), reverse=True)[:3]
        for cluster_id, arts in sorted_clusters:
            cluster = ArticleCluster.query.get(cluster_id)
            if cluster:
                sources = list(set(a.source for a in arts if a.source))
                top_clusters.append({
                    'id': cluster_id,
                    'title': cluster.title,
                    'count': len(arts),
                    'sources': sources,
                })

    # --- 2. 언론사별 평균 정치축 편향 TOP 3 보수/진보 ---
    source_scores = defaultdict(list)
    for a in articles:
        if a.source and a.source_political is not None:
            source_scores[a.source].append(a.source_political)

    source_avg = {}
    for src, scores in source_scores.items():
        if len(scores) >= 2:  # 최소 2건 이상
            source_avg[src] = sum(scores) / len(scores)

    sorted_by_score = sorted(source_avg.items(), key=lambda x: x[1])
    top_progressive = sorted_by_score[:3]  # 가장 진보 (낮은 점수)
    top_conservative = sorted_by_score[-3:][::-1]  # 가장 보수 (높은 점수)

    # --- 3. 진보-보수 언론이 가장 다르게 다룬 클러스터 ---
    most_divided = None
    max_deviation = 0.0

    for cluster_id, arts in cluster_counts.items():
        pol_scores = [a.source_political for a in arts if a.source_political is not None]
        if len(pol_scores) >= 2:
            deviation = max(pol_scores) - min(pol_scores)
            if deviation > max_deviation:
                max_deviation = deviation
                cluster = ArticleCluster.query.get(cluster_id)
                if cluster:
                    most_prog = min(arts, key=lambda a: a.source_political if a.source_political is not None else 0)
                    most_cons = max(arts, key=lambda a: a.source_political if a.source_political is not None else 0)
                    most_divided = {
                        'id': cluster_id,
                        'title': cluster.title,
                        'deviation': round(deviation, 1),
                        'progressive_source': most_prog.source,
                        'progressive_score': most_prog.source_political,
                        'conservative_source': most_cons.source,
                        'conservative_score': most_cons.source_political,
                    }

    # --- 텔레그램 메시지 포맷 ---
    now = datetime.now()
    week_start = (now - timedelta(days=7)).strftime('%m/%d')
    week_end = now.strftime('%m/%d')

    lines = [
        f"📊 *NR2 YouCheck 주간 편향 리포트*",
        f"📅 {week_start} ~ {week_end}",
        "",
    ]

    # TOP 클러스터
    if top_clusters:
        lines.append("🔥 *가장 많은 언론사가 다룬 사건*")
        for i, c in enumerate(top_clusters, 1):
            sources_str = ', '.join(c['sources'][:5])
            if len(c['sources']) > 5:
                sources_str += f' 외 {len(c["sources"]) - 5}곳'
            lines.append(f"  {i}. {c['title']}")
            lines.append(f"     → {c['count']}개 기사 ({sources_str})")
        lines.append("")

    # 보수 TOP 3
    if top_conservative:
        lines.append("🔴 *보수 성향 TOP 3 언론사* (이번 주)")
        for src, score in top_conservative:
            bar = _score_bar(score)
            lines.append(f"  • {src} {bar} ({score:+.0f})")
        lines.append("")

    # 진보 TOP 3
    if top_progressive:
        lines.append("🔵 *진보 성향 TOP 3 언론사* (이번 주)")
        for src, score in top_progressive:
            bar = _score_bar(score)
            lines.append(f"  • {src} {bar} ({score:+.0f})")
        lines.append("")

    # 가장 다르게 다룬 사건
    if most_divided:
        lines.append("⚡ *진보↔보수 시각차 가장 큰 사건*")
        lines.append(f"  📰 {most_divided['title']}")
        lines.append(f"  🔵 {most_divided['progressive_source']} ({most_divided['progressive_score']:+.0f})")
        lines.append(f"  🔴 {most_divided['conservative_source']} ({most_divided['conservative_score']:+.0f})")
        lines.append(f"  📏 편차: {most_divided['deviation']}점")
        lines.append("")

    lines.append(f"📈 이번 주 분석 기사: {len(articles)}건")
    lines.append("👉 자세히 보기: https://nr2.kr/bias")

    telegram_text = '\n'.join(lines)

    return {
        'top_clusters': top_clusters,
        'top_conservative': [{'source': s, 'score': round(sc, 1)} for s, sc in top_conservative],
        'top_progressive': [{'source': s, 'score': round(sc, 1)} for s, sc in top_progressive],
        'most_divided_cluster': most_divided,
        'total_articles': len(articles),
        'telegram_text': telegram_text,
        'generated_at': now.isoformat(),
        'week_start': week_start,
        'week_end': week_end,
    }


def _score_bar(score):
    """점수를 시각적 바로 변환 (-100~100)"""
    normalized = int((score + 100) / 200 * 10)
    normalized = max(0, min(10, normalized))
    return '▓' * normalized + '░' * (10 - normalized)


def send_weekly_report_to_telegram(text=None):
    """주간 리포트를 텔레그램으로 전송한다.

    Args:
        text: 전송할 텍스트. None이면 자동 생성.

    Returns:
        dict with 'success' bool and 'message' str
    """
    bot_token = os.environ.get('NUREONGI_NEWS_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_REPORT_CHAT_ID', '@gazzzza2025')

    if not bot_token:
        return {'success': False, 'message': 'NUREONGI_NEWS_BOT_TOKEN 환경변수가 설정되지 않았습니다'}

    if text is None:
        report = generate_weekly_report()
        text = report['telegram_text']

    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'Markdown',
        'disable_web_page_preview': True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return {'success': True, 'message': '텔레그램 전송 완료'}
    except Exception as e:
        return {'success': False, 'message': f'전송 실패: {str(e)[:200]}'}
