import os
import re
os.environ.setdefault('TZ', 'Asia/Seoul')
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
from config import config

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()
mail = Mail()


def create_app(config_name='default'):
    """Flask 애플리케이션 팩토리"""
    app = Flask(__name__)

    # Load configuration
    app.config.from_object(config[config_name])

    # Initialize extensions with app
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    mail.init_app(app)

    # Configure Flask-Login
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '로그인이 필요합니다.'
    login_manager.login_message_category = 'warning'

    # User loader callback
    @login_manager.user_loader
    def load_user(user_id):
        from app.models import User
        return User.query.get(int(user_id))

    # Create upload folder if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'profiles'), exist_ok=True)

    # Setup logging
    if not app.debug and not app.testing:
        # Create logs directory
        if not os.path.exists('logs'):
            os.mkdir('logs')

        # File handler
        file_handler = RotatingFileHandler(
            app.config.get('LOG_FILE', 'logs/nr2.log'),
            maxBytes=10240000,  # 10MB
            backupCount=10
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(getattr(logging, app.config.get('LOG_LEVEL', 'INFO')))
        app.logger.addHandler(file_handler)

        app.logger.setLevel(getattr(logging, app.config.get('LOG_LEVEL', 'INFO')))
        app.logger.info('NR2 application startup')

    # Error handlers
    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        app.logger.error(f'Server Error: {error}')
        return render_template('errors/500.html'), 500

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('errors/403.html'), 403

    @app.errorhandler(413)
    def too_large(error):
        return '파일 크기가 너무 큽니다. 최대 16MB까지 업로드 가능합니다.', 413

    # Register blueprints
    from app.routes import auth, boards, main, admin, votes, calendar, news, bias
    app.register_blueprint(auth.bp)
    app.register_blueprint(boards.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(votes.bp)
    app.register_blueprint(calendar.bp)
    app.register_blueprint(news.bp)
    app.register_blueprint(bias.bp)

    from app.routes import briefings
    app.register_blueprint(briefings.bp)

    # KST 시간대 Jinja2 필터
    KST = timezone(timedelta(hours=9))
    def format_kst(dt, fmt='%Y-%m-%d %H:%M'):
        if not dt:
            return ''
        if isinstance(dt, str):
            return dt
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(KST).strftime(fmt)
    app.jinja_env.filters['kst'] = format_kst
    app.jinja_env.filters['kst_short'] = lambda dt: format_kst(dt, '%m/%d %H:%M')
    app.jinja_env.filters['kst_full'] = lambda dt: format_kst(dt, '%Y-%m-%d %H:%M:%S')

    # 게시글 미리보기 텍스트 정리 필터
    def clean_preview(text, length=80):
        if not text:
            return ''
        clean = re.sub(r'<[^>]+>', '', text)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean[:length] + '...' if len(clean) > length else clean
    app.jinja_env.filters['clean_preview'] = clean_preview

    # NP 등급 필터
    from app.models.np_point import get_next_grade, get_grade
    app.jinja_env.filters['np_next_grade'] = lambda np: get_next_grade(np or 0)
    app.jinja_env.filters['np_grade'] = lambda np: get_grade(np or 0)

    # Import models for Flask-Migrate
    from app import models

    # 방문자 추적
    from app.tracking import init_tracking
    init_tracking(app)

    # DB 테이블 자동 생성 + 마이그레이션 보완
    with app.app_context():
        db.create_all()
        # youtube_video_id 컬럼이 없으면 추가 (db.create_all은 기존 테이블에 컬럼 추가 불가)
        try:
            db.session.execute(db.text(
                "ALTER TABLE posts ADD COLUMN youtube_video_id VARCHAR(20)"
            ))
            db.session.commit()
            app.logger.info('posts.youtube_video_id 컬럼 추가 완료')
        except Exception:
            db.session.rollback()

        # 부방장 권한 시스템 컬럼 추가
        for col_sql in [
            "ALTER TABLE users ADD COLUMN is_vice_admin BOOLEAN DEFAULT FALSE",
            "ALTER TABLE users ADD COLUMN warning_count INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN suspended_until TIMESTAMP",
        ]:
            try:
                db.session.execute(db.text(col_sql))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # 비밀번호 재설정 토큰 컬럼 추가
        for col_sql in [
            "ALTER TABLE users ADD COLUMN reset_token VARCHAR(100)",
            "ALTER TABLE users ADD COLUMN reset_token_expires TIMESTAMP",
        ]:
            try:
                db.session.execute(db.text(col_sql))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # 이메일 인증 컬럼 추가 (기존 유저는 TRUE)
        for col_sql in [
            "ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT TRUE",
            "ALTER TABLE users ADD COLUMN email_verify_token VARCHAR(100)",
        ]:
            try:
                db.session.execute(db.text(col_sql))
                db.session.commit()
            except Exception:
                db.session.rollback()

        # 미인증 회원 전원 인증 처리
        try:
            db.session.execute(db.text(
                "UPDATE users SET email_verified = TRUE WHERE email_verified = FALSE OR email_verified IS NULL"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # 댓글 대댓글(parent_id) 컬럼 추가
        try:
            db.session.execute(db.text(
                "ALTER TABLE comments ADD COLUMN parent_id INTEGER REFERENCES comments(id)"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # news_articles 테이블에 scraped_content 컬럼 추가
        try:
            db.session.execute(db.text(
                "ALTER TABLE news_articles ADD COLUMN scraped_content TEXT"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # news_articles 테이블에 is_archived 컬럼 추가
        try:
            db.session.execute(db.text(
                "ALTER TABLE news_articles ADD COLUMN is_archived BOOLEAN DEFAULT FALSE"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # [1회성] 기존 기사 전부 아카이브 처리 (24시간 이전 기사)
        try:
            db.session.execute(db.text(
                "UPDATE news_articles SET is_archived = TRUE WHERE is_archived = FALSE AND created_at < NOW() - INTERVAL '24 hours'"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # news_articles 테이블에 is_visible 컬럼 추가
        try:
            db.session.execute(db.text(
                "ALTER TABLE news_articles ADD COLUMN is_visible BOOLEAN DEFAULT TRUE"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # 오늘자 시사·정치·AI·경제 기사 중 최신 10개 자동 노출
        try:
            db.session.execute(db.text("""
                UPDATE news_articles SET is_visible = TRUE
                WHERE id IN (
                    SELECT id FROM news_articles
                    WHERE created_at >= NOW() - INTERVAL '48 hours'
                      AND is_archived = FALSE
                      AND (
                        title ILIKE '%정치%' OR title ILIKE '%대통령%' OR title ILIKE '%국회%'
                        OR title ILIKE '%여야%' OR title ILIKE '%민주당%' OR title ILIKE '%국민의힘%'
                        OR title ILIKE '%AI%' OR title ILIKE '%인공지능%' OR title ILIKE '%ChatGPT%'
                        OR title ILIKE '%경제%' OR title ILIKE '%금리%' OR title ILIKE '%환율%'
                        OR title ILIKE '%삼성%' OR title ILIKE '%반도체%' OR title ILIKE '%테슬라%'
                        OR title ILIKE '%시사%' OR title ILIKE '%검찰%' OR title ILIKE '%외교%'
                        OR title ILIKE '%트럼프%' OR title ILIKE '%북한%' OR title ILIKE '%안보%'
                      )
                    ORDER BY created_at DESC
                    LIMIT 10
                )
            """))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # users 테이블에 job_category 컬럼 추가
        try:
            db.session.execute(db.text(
                "ALTER TABLE users ADD COLUMN job_category VARCHAR(20) DEFAULT 'public'"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # users 테이블에 NP 관련 컬럼 추가
        try:
            db.session.execute(db.text(
                "ALTER TABLE users ADD COLUMN total_np INTEGER DEFAULT 0"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text(
                "ALTER TABLE users ADD COLUMN last_login_date DATE"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
        try:
            db.session.execute(db.text(
                "ALTER TABLE users ADD COLUMN login_streak INTEGER DEFAULT 0"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # point_history 테이블 생성
        try:
            db.session.execute(db.text("""
                CREATE TABLE IF NOT EXISTS point_history (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id),
                    action_type VARCHAR(50) NOT NULL,
                    points INTEGER NOT NULL,
                    description VARCHAR(200) NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # [1회성] 기존 가입자 NP 소급 지급
        try:
            from app.models.np_point import PointHistory
            already_done = PointHistory.query.filter_by(action_type='retroactive_bulk').first()
            if not already_done:
                from app.models import User, Post, Comment
                users = User.query.all()
                for u in users:
                    np = 100  # 가입 보너스
                    post_count = Post.query.filter_by(user_id=u.id).count()
                    comment_count = Comment.query.filter_by(user_id=u.id).count()
                    np += post_count * 10
                    np += comment_count * 5
                    u.total_np = np
                    db.session.add(PointHistory(
                        user_id=u.id, action_type='retroactive_bulk',
                        points=np, description=f'소급지급: 가입100+글{post_count}x10+댓글{comment_count}x5'
                    ))
                db.session.commit()
                app.logger.info('[NP] 기존 가입자 NP 소급 지급 완료')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'[NP] 소급 지급 오류: {e}')

        # [1회성] AESA 게시판 이준석 관련 자동 게시글 삭제
        try:
            from app.models import Post
            lee_posts = Post.query.filter(
                Post.board_type == 'aesa',
                db.or_(
                    Post.title.ilike('%이준석%'),
                    Post.content.ilike('%이준석%')
                )
            ).all()
            if lee_posts:
                for p in lee_posts:
                    db.session.delete(p)
                db.session.commit()
                app.logger.info(f'[AESA 정리] 이준석 관련 {len(lee_posts)}건 삭제 완료')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'[AESA 정리] 삭제 실패: {e}')

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    return app
