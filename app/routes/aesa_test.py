import os
from flask import Blueprint, jsonify
from app.models.aesa_article import AesaArticle
from aesa_monitoring_bot import send_telegram_alert
from app import db
from sqlalchemy import func

bp = Blueprint('aesa_test', __name__)

@bp.route('/api/aesa/stats')
def aesa_stats():
    res = db.session.query(AesaArticle.score, func.count(AesaArticle.id)).group_by(AesaArticle.score).all()
    stats = [{"score": r[0], "count": r[1]} for r in res]
    total = AesaArticle.query.count()
    return jsonify({"total": total, "distribution": stats})

@bp.route('/api/aesa/test')
def aesa_test():
    article = AesaArticle.query.order_by(AesaArticle.score.desc()).first()
    if not article:
        return jsonify({"error": "No articles in DB"}), 404
        
    try:
        send_telegram_alert(
            article.source, 
            article.title, 
            article.url, 
            article.score, 
            article.summary, 
            is_urgent=True
        )
        return jsonify({
            "success": True, 
            "sent": {
                "title": article.title,
                "score": article.score,
                "status": article.status
            }
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
