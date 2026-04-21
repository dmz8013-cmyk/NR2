"""nr2.kr URL 단축기 라우트.

- GET /s/<code>           → 원본 URL 301 리다이렉트 (실패 시 nr2.kr 302)
- GET /shortener          → 히어로/체험 페이지 (비로그인 허용)
- POST /api/shortener/create → JSON API (비로그인 허용, @csrf.exempt)
"""
import hashlib
import logging

from flask import Blueprint, render_template, request, redirect, jsonify
from flask_login import current_user

from app import csrf
from scripts.url_shortener import shorten_url, resolve_code

logger = logging.getLogger(__name__)

bp = Blueprint('shortener', __name__)


def _hash_ip(ip):
    if not ip:
        return None
    return hashlib.sha256(ip.encode('utf-8')).hexdigest()[:16]


def _detect_device(ua):
    low = (ua or '').lower()
    if 'tablet' in low or 'ipad' in low:
        return 'tablet'
    if 'mobile' in low or 'iphone' in low or 'android' in low:
        return 'mobile'
    return 'desktop'


@bp.route('/s/<code>')
def redirect_short_url(code):
    """단축 코드 → 원본 URL 301 리다이렉트. 미존재/만료 시 nr2.kr 302."""
    ip = request.headers.get('X-Forwarded-For', request.remote_addr) or ''
    ip = ip.split(',')[0].strip()
    ua = (request.headers.get('User-Agent') or '')[:500]

    meta = {
        'user_agent': ua,
        'ip_hash': _hash_ip(ip),
        'referer': (request.headers.get('Referer') or '')[:500],
        'device_type': _detect_device(ua),
    }

    original = resolve_code(code, request_meta=meta)
    if not original:
        return redirect('https://nr2.kr', code=302)
    return redirect(original, code=301)


@bp.route('/shortener')
def shortener_home():
    """히어로 페이지. 비로그인 체험 허용."""
    return render_template('shortener/home.html')


@bp.route('/api/shortener/create', methods=['POST'])
@csrf.exempt
def api_create_shortener():
    """URL 단축 JSON API. 비로그인 허용 (user_id=None)."""
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    if not url.startswith(('http://', 'https://')):
        return jsonify({'error': '유효한 URL을 입력해주세요 (http:// 또는 https://)'}), 400

    user_id = current_user.id if current_user.is_authenticated else None
    short = shorten_url(url, user_id=user_id, source_bot='web')

    if short == url:
        return jsonify({'error': '단축 실패. 잠시 후 다시 시도해주세요.'}), 500
    return jsonify({'short_url': short})
