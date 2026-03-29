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

        # 뱃지 기본 데이터 시딩
        try:
            from app.models.badge import Badge
            seed_badges = [
                # 출석 뱃지
                {'code': 'ATTEND_7', 'name': '7일 출석', 'description': '7일 연속 로그인 달성', 'icon': '🚶', 'badge_type': 'attendance', 'condition_value': 7},
                {'code': 'ATTEND_30', 'name': '30일 출석', 'description': '30일 연속 로그인 달성', 'icon': '🏃', 'badge_type': 'attendance', 'condition_value': 30},
                {'code': 'ATTEND_100', 'name': '100일 출석', 'description': '100일 연속 로그인 달성', 'icon': '🔥', 'badge_type': 'attendance', 'condition_value': 100},
                # 글쓰기 뱃지
                {'code': 'POST_10', 'name': '게시판 꿈나무', 'description': '게시글 10개 작성', 'icon': '🌱', 'badge_type': 'post', 'condition_value': 10},
                {'code': 'POST_50', 'name': '게시판 인싸', 'description': '게시글 50개 작성', 'icon': '🎤', 'badge_type': 'post', 'condition_value': 50},
                {'code': 'POST_100', 'name': '게시판 고인물', 'description': '게시글 100개 작성', 'icon': '👑', 'badge_type': 'post', 'condition_value': 100},
                # 댓글 뱃지
                {'code': 'COMMENT_50', 'name': '소통의 시작', 'description': '댓글 50개 작성', 'icon': '💬', 'badge_type': 'comment', 'condition_value': 50},
                {'code': 'COMMENT_200', 'name': '프로 소통러', 'description': '댓글 200개 작성', 'icon': '🗣️', 'badge_type': 'comment', 'condition_value': 200},
                # NP 뱃지
                {'code': 'NP_1000', 'name': '천만 다행', 'description': 'NP 1,000점 달성', 'icon': '💰', 'badge_type': 'np', 'condition_value': 1000},
                {'code': 'NP_5000', 'name': '오천만 원', 'description': 'NP 5,000점 달성', 'icon': '💸', 'badge_type': 'np', 'condition_value': 5000},
                {'code': 'NP_10000', 'name': '만수르', 'description': 'NP 10,000점 달성', 'icon': '💎', 'badge_type': 'np', 'condition_value': 10000},
                # 직군 뱃지
                {'code': 'JOB_AI', 'name': 'AI 엔지니어', 'description': 'AI 관련 직군 인증', 'icon': '🤖', 'badge_type': 'job', 'condition_value': 0},
                {'code': 'JOB_DEV', 'name': '개발자', 'description': '개발 관련 직군 인증', 'icon': '💻', 'badge_type': 'job', 'condition_value': 0},
                {'code': 'JOB_MARKETER', 'name': '마케터', 'description': '마케팅 관련 직군 인증', 'icon': '📈', 'badge_type': 'job', 'condition_value': 0},
            ]
            
            for b_data in seed_badges:
                if not Badge.query.filter_by(code=b_data['code']).first():
                    b = Badge(**b_data)
                    db.session.add(b)
            db.session.commit()
            app.logger.info('[Badge] 기본 뱃지 시딩 완료')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'[Badge] 기본 뱃지 시딩 실패: {e}')
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

        # posts 테이블에 external_url, og_image 컬럼 추가 (누렁이 픽)
        for col_sql in [
            "ALTER TABLE posts ADD COLUMN external_url VARCHAR(500)",
            "ALTER TABLE posts ADD COLUMN og_image VARCHAR(500)",
        ]:
            try:
                db.session.execute(db.text(col_sql))
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

        # 온보딩 완료 여부 컬럼 추가
        try:
            db.session.execute(db.text(
                "ALTER TABLE users ADD COLUMN onboarding_completed BOOLEAN DEFAULT FALSE"
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()

        # 첫 댓글 보상 여부 컬럼 추가
        try:
            db.session.execute(db.text(
                "ALTER TABLE users ADD COLUMN first_comment_rewarded BOOLEAN DEFAULT FALSE"
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

    # === 아티클 자동 시딩 (누렁이 픽) ===
    with app.app_context():
        try:
            from app.models.post import Post
            musk_title = '"돈의 시대가 끝난다?" 일론 머스크가 말하는 \'폭발적 풍요\'의 미래와 5가지 충격적 통찰'
            if not Post.query.filter_by(title=musk_title, board_type='pick').first():
                bot_user = User.query.filter_by(nickname='누렁이봇').first()
                if not bot_user:
                    bot_user = User.query.filter_by(is_admin=True).first()
                if bot_user:
                    # 콘텐츠 파일 직접 읽기 (순환 import 방지)
                    content_path = os.path.join(
                        os.path.dirname(__file__), '..', 'scripts', 'seed_musk_article_content.html'
                    )
                    with open(content_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    post = Post(
                        title=musk_title,
                        content=content,
                        board_type='pick',
                        user_id=bot_user.id,
                    )
                    db.session.add(post)
                    db.session.commit()
                    app.logger.info(f'[아티클 시딩] 머스크 아티클 게시 완료 (post_id={post.id})')
                    # 텔레그램 알림
                    try:
                        from app.utils.telegram_notify import notify_new_post
                        notify_new_post(post)
                    except Exception:
                        pass
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'[아티클 시딩] 실패: {e}')

    # === AESA 브리핑 아티클 시딩 ===
    with app.app_context():
        try:
            from app.models.post import Post
            aesa_title = '2026 경제·산업 전망 및 글로벌 AI 기술 혁신 브리핑'
            if not Post.query.filter_by(title=aesa_title, board_type='aesa').first():
                bot_user = User.query.filter_by(nickname='누렁이봇').first()
                if not bot_user:
                    bot_user = User.query.filter_by(is_admin=True).first()
                if bot_user:
                    content_path = os.path.join(
                        os.path.dirname(__file__), '..', 'scripts', 'seed_aesa_briefing_content.html'
                    )
                    with open(content_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    post = Post(
                        title=aesa_title,
                        content=content,
                        board_type='aesa',
                        user_id=bot_user.id,
                    )
                    db.session.add(post)
                    db.session.commit()
                    app.logger.info(f'[AESA 시딩] 경제·AI 브리핑 게시 완료 (post_id={post.id})')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'[AESA 시딩] 실패: {e}')

    # === 자유게시판 정리: None 글 + 잘못 배치된 크로스포스팅 글 삭제 ===
    with app.app_context():
        try:
            from app.models.post import Post

            # 1) title이 None/NULL인 글 삭제
            null_posts = Post.query.filter(
                db.or_(Post.title == 'None', Post.title == 'none', Post.title.is_(None))
            ).all()
            null_count = len(null_posts)
            for p in null_posts:
                db.session.delete(p)

            # 2) 자유게시판(free)에 잘못 올라간 크로스포스팅 글 삭제
            #    (user_id=1이고 external_url이 있는 뉴스성 글)
            misplaced = Post.query.filter(
                Post.board_type == 'free',
                Post.user_id == 1,
                Post.external_url.isnot(None),
            ).all()
            misplaced_count = len(misplaced)
            for p in misplaced:
                db.session.delete(p)

            if null_count or misplaced_count:
                db.session.commit()
                app.logger.info(
                    f'[정리] None 글 {null_count}개, 자유게시판 잘못 배치 글 {misplaced_count}개 삭제'
                )
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'[정리] 자유게시판 정리 실패: {e}')

    # Security headers
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # === Flask CLI: 라운지 시딩 ===
    @app.cli.command('seed-lounges')
    def seed_lounges_command():
        """각 라운지 게시판에 첫 질문 글 시딩 (3개 미만일 때만)"""
        from app.models.post import Post

        SEED_DATA = [
            {
                'board_type': 'lounge_media',
                'title': '요즘 기사 쓰면서 AI 어떻게 활용하고 계세요?',
                'content': (
                    'ChatGPT, Claude, Vrew 등 AI 도구가 취재·작성 방식을 바꾸고 있는데, '
                    '실제 현장에서 어떻게 쓰고 계신지 궁금합니다. '
                    '잘 쓰는 방법도, 한계도 솔직하게 나눠봐요.'
                ),
            },
            {
                'board_type': 'lounge_congress',
                'title': '이번 지방선거에서 기초의원 후보 고르는 기준이 있으신가요?',
                'content': (
                    '6월 3일 지방선거가 다가오고 있습니다. '
                    '구의원·시의원 후보를 선택할 때 어떤 기준으로 보시나요? '
                    '정당? 인물? 공약? 솔직한 이야기 나눠봐요.'
                ),
            },
            {
                'board_type': 'lounge_govt',
                'title': '최근 행정 처리 중 가장 황당했던 경험 있으신가요?',
                'content': (
                    '법은 안 어겼는데 행정이 벽이 되는 순간들, 다들 한 번쯤 겪어봤을 것 같아요. '
                    '민원 대응, 인허가, 공문 처리 등 경험담 편하게 올려주세요.'
                ),
            },
            {
                'board_type': 'lounge_corp',
                'title': '스타트업·중소기업 대표님들, 요즘 가장 큰 고민이 뭔가요?',
                'content': (
                    '자금, 인력, 영업, 정부지원 등 다양한 이슈가 있을 텐데, '
                    '현재 가장 발목 잡는 문제가 무엇인지 솔직하게 이야기 나눠봐요.'
                ),
            },
            {
                'board_type': 'lounge_public',
                'title': 'nr2.kr 처음 왔는데, 어떻게 알고 오셨나요?',
                'content': (
                    '텔레그램 정보방을 통해? 지인 소개? 유튜브를 보고? '
                    '여기까지 오신 경로가 궁금합니다. 자기소개도 함께 남겨주세요 🙌'
                ),
            },
            {
                'board_type': 'lounge_bamboo',
                'title': '요즘 직장에서 AI 때문에 달라진 일상, 익명으로 털어놓기',
                'content': (
                    'AI가 생산성을 높여줬나요, 아니면 오히려 스트레스인가요? '
                    '회사에서 AI 사용 강요받거나 반대로 못 쓰게 막는 경우도 있다고 하던데. '
                    '익명이니까 솔직하게요.'
                ),
            },
        ]

        # 누렁이봇 또는 admin 계정 찾기
        bot_user = User.query.filter_by(nickname='누렁이봇').first()
        if not bot_user:
            bot_user = User.query.filter_by(is_admin=True).first()
        if not bot_user:
            print('[시딩] 누렁이봇 또는 admin 계정을 찾을 수 없습니다.')
            return

        seeded = 0
        for data in SEED_DATA:
            board_type = data['board_type']
            count = Post.query.filter_by(board_type=board_type).count()
            if count >= 3:
                print(f'  ⏭️  {board_type}: 이미 {count}개 글이 있어 스킵')
                continue

            # 동일 제목 중복 방지
            exists = Post.query.filter_by(
                board_type=board_type, title=data['title']
            ).first()
            if exists:
                print(f'  ⏭️  {board_type}: 이미 시딩된 글 존재 — 스킵')
                continue

            post = Post(
                title=data['title'],
                content=data['content'],
                board_type=board_type,
                user_id=bot_user.id,
            )
            db.session.add(post)
            seeded += 1
            print(f'  ✅ {board_type}: "{data["title"][:30]}..." 시딩 완료')

        db.session.commit()
        print(f'[시딩] 완료 — {seeded}개 라운지에 첫 글 게시')

    return app
