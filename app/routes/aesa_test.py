import os
from flask import Blueprint, jsonify, request
from app.models.aesa_article import AesaArticle
from aesa_monitoring_bot import send_telegram_alert, send_batch_alerts
from app import db
from sqlalchemy import func
from datetime import datetime, timedelta

bp = Blueprint('aesa_test', __name__)

@bp.route('/api/aesa/stats')
def aesa_stats():
    res = db.session.query(AesaArticle.score, func.count(AesaArticle.id)).group_by(AesaArticle.score).all()
    stats = [{"score": r[0], "count": r[1]} for r in res]
    total = AesaArticle.query.count()

    # 소스별 기사 수
    source_counts = db.session.query(
        AesaArticle.source, func.count(AesaArticle.id)
    ).group_by(AesaArticle.source).order_by(func.count(AesaArticle.id).desc()).all()

    # 상태별 기사 수
    status_counts = db.session.query(
        AesaArticle.status, func.count(AesaArticle.id)
    ).group_by(AesaArticle.status).all()

    # 최근 30분 기사
    cutoff_30m = datetime.now() - timedelta(minutes=30)
    recent_30m = AesaArticle.query.filter(AesaArticle.created_at >= cutoff_30m).count()
    recent_30m_7plus = AesaArticle.query.filter(
        AesaArticle.created_at >= cutoff_30m,
        AesaArticle.score >= 7
    ).count()

    # 컬럼 존재 여부 체크
    has_lenses_col = True
    try:
        db.session.execute(db.text("SELECT lenses FROM aesa_articles LIMIT 1"))
    except Exception:
        has_lenses_col = False
        db.session.rollback()

    return jsonify({
        "total": total,
        "distribution": stats,
        "by_source": [{"source": s, "count": c} for s, c in source_counts],
        "by_status": [{"status": s, "count": c} for s, c in status_counts],
        "recent_30m": {"total": recent_30m, "score_7plus": recent_30m_7plus},
        "db_columns": {"lenses": has_lenses_col}
    })

@bp.route('/api/aesa/test')
def aesa_test():
    article = AesaArticle.query.order_by(AesaArticle.score.desc()).first()
    if not article:
        return jsonify({"error": "No articles in DB"}), 404

    try:
        lenses = article.lenses.split(',') if hasattr(article, 'lenses') and article.lenses else []
        korea_link = getattr(article, 'korea_investment_link', False)
        send_telegram_alert(
            article.source, article.title, article.url,
            article.score, article.summary,
            lenses=lenses, korea_link=korea_link, is_urgent=True
        )
        return jsonify({
            "success": True,
            "sent": {"title": article.title, "score": article.score, "status": article.status}
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/aesa/batch-now')
def aesa_batch_now():
    """수동 배치 발송 트리거"""
    secret = request.args.get('key', '')
    expected = os.environ.get('AESA_ADMIN_KEY', 'aesa-batch-2026')
    if secret != expected:
        return jsonify({"error": "unauthorized"}), 403

    try:
        send_batch_alerts()
        return jsonify({"success": True, "message": "배치 발송 완료"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@bp.route('/api/aesa/cleanup-source')
def aesa_cleanup_source():
    """특정 소스의 기사를 DB에서 삭제"""
    secret = request.args.get('key', '')
    expected = os.environ.get('AESA_ADMIN_KEY', 'aesa-batch-2026')
    source = request.args.get('source', '')
    if secret != expected or not source:
        return jsonify({"error": "unauthorized or missing source"}), 403
    try:
        count = AesaArticle.query.filter_by(source=source).count()
        AesaArticle.query.filter_by(source=source).delete()
        db.session.commit()
        remain = AesaArticle.query.filter_by(source=source).count()
        return jsonify({"success": True, "deleted": count, "remaining": remain, "source": source})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@bp.route('/api/aesa/diagnose')
def aesa_diagnose():
    """전체 진단: DB 상태 + 컬럼 체크 + 최근 기사 목록"""
    diag = {}

    # 1. 테이블 존재 여부
    try:
        total = AesaArticle.query.count()
        diag['table_exists'] = True
        diag['total_articles'] = total
    except Exception as e:
        diag['table_exists'] = False
        diag['error'] = str(e)
        return jsonify(diag)

    # 2. 컬럼 체크
    for col in ['lenses', 'korea_investment_link']:
        try:
            db.session.execute(db.text(f"SELECT {col} FROM aesa_articles LIMIT 1"))
            diag[f'col_{col}'] = True
        except Exception:
            diag[f'col_{col}'] = False
            db.session.rollback()

    # 3. status 분포
    status_counts = db.session.query(
        AesaArticle.status, func.count(AesaArticle.id)
    ).group_by(AesaArticle.status).all()
    diag['status_distribution'] = {s: c for s, c in status_counts}

    # 4. queued_batch 대기 건수
    diag['queued_batch_count'] = AesaArticle.query.filter_by(status='queued_batch').count()

    # 5. 최근 10개 기사
    recent = AesaArticle.query.order_by(AesaArticle.created_at.desc()).limit(10).all()
    diag['recent_articles'] = [{
        'id': a.id, 'source': a.source, 'score': a.score,
        'status': a.status, 'title': a.title[:50],
        'created_at': a.created_at.isoformat() if a.created_at else None
    } for a in recent]

    return jsonify(diag)
