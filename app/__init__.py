import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from config import config

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()


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

    # Import models for Flask-Migrate
    from app import models

    # 방문자 추적
    from app.tracking import init_tracking
    init_tracking(app)

    # DB 테이블 자동 생성
    with app.app_context():
        db.create_all()

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
