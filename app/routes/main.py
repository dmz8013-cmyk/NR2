from flask import Blueprint, render_template

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    """메인 페이지"""
    return render_template('main/index.html')


@bp.route('/about')
def about():
    """소개 페이지"""
    return render_template('main/about.html')


@bp.route('/policy')
def policy():
    return render_template('policy.html')
