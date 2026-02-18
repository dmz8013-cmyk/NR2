# 🔒 보안 및 성능 강화 문서

NR2 프로젝트에 적용된 보안 및 성능 최적화 가이드입니다.

## 📋 목차

1. [보안 강화](#보안-강화)
2. [성능 최적화](#성능-최적화)
3. [안정성 개선](#안정성-개선)
4. [배포 준비](#배포-준비)

---

## 🔐 보안 강화

### 1. CSRF 보호

**구현 위치:** `app/__init__.py`

```python
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()
csrf.init_app(app)
```

**설정:**
- 모든 POST/PUT/DELETE 요청에 자동으로 CSRF 토큰 검증
- `config.py`에서 `WTF_CSRF_ENABLED = True`로 설정

**템플릿 사용법:**
```html
<form method="POST">
    {{ form.csrf_token }}
    <!-- 또는 -->
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
</form>
```

### 2. 비밀번호 강도 검사

**구현 위치:** `app/utils/validators.py`

**요구사항:**
- 최소 8자 이상
- 영문 대문자 포함
- 영문 소문자 포함
- 숫자 포함

```python
def validate_password_strength(password):
    """비밀번호 강도 검증
    Returns: (is_valid, message)
    """
    if len(password) < 8:
        return False, "비밀번호는 최소 8자 이상이어야 합니다."
    if not re.search(r'[a-z]', password):
        return False, "비밀번호에 영문 소문자가 포함되어야 합니다."
    if not re.search(r'[A-Z]', password):
        return False, "비밀번호에 영문 대문자가 포함되어야 합니다."
    if not re.search(r'\d', password):
        return False, "비밀번호에 숫자가 포함되어야 합니다."
    return True, "비밀번호가 유효합니다."
```

**적용 위치:** `app/routes/auth.py` 회원가입 라우트

### 3. 로그인 시도 제한

**구현 위치:** `app/models/login_attempt.py`

**설정:**
- 최대 시도 횟수: 5회 (환경변수 `MAX_LOGIN_ATTEMPTS`)
- 잠금 시간: 30분 (환경변수 `LOCKOUT_DURATION`, 초 단위)

**기능:**
- IP 주소별 로그인 시도 기록
- 실패 횟수 초과 시 계정 일시 잠금
- 남은 시도 횟수 표시
- 잠금 시간 경과 후 자동 해제

```python
# 로그인 시도 확인
is_locked, remaining_time = LoginAttempt.is_locked(
    email,
    max_attempts=5,
    lockout_duration=1800
)

if is_locked:
    flash(f'로그인 시도 횟수를 초과했습니다. {minutes}분 {seconds}초 후에 다시 시도해주세요.')
```

**데이터베이스:**
```sql
CREATE TABLE login_attempts (
    id INTEGER PRIMARY KEY,
    email VARCHAR(120) NOT NULL,
    ip_address VARCHAR(45) NOT NULL,
    success BOOLEAN DEFAULT FALSE,
    attempted_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_login_attempts_email ON login_attempts (email);
CREATE INDEX ix_login_attempts_attempted_at ON login_attempts (attempted_at);
```

### 4. SQL Injection 방지

**구현 방법:** SQLAlchemy ORM 사용

- 모든 데이터베이스 쿼리는 SQLAlchemy ORM을 통해 실행
- 매개변수화된 쿼리로 SQL Injection 자동 방지
- Raw SQL 사용 금지 (필요시 `text()` 함수와 바인딩 파라미터 사용)

**좋은 예:**
```python
user = User.query.filter_by(email=email).first()
posts = Post.query.filter(Post.title.like(f'%{keyword}%')).all()
```

**나쁜 예 (사용 금지):**
```python
# ❌ SQL Injection 위험
query = f"SELECT * FROM users WHERE email = '{email}'"
```

### 5. XSS 필터링

**구현 위치:** `app/utils/validators.py`

```python
from markupsafe import escape

def sanitize_html(text):
    """XSS 공격 방지를 위한 HTML 이스케이프"""
    if text is None:
        return None
    return escape(text)
```

**적용 권장 위치:**
- 사용자 입력 데이터 저장 전
- 닉네임, 게시글 제목, 댓글 내용 등

**템플릿 자동 이스케이프:**
Jinja2는 기본적으로 모든 변수를 자동 이스케이프합니다.
```html
{{ user.nickname }}  <!-- 자동으로 이스케이프됨 -->
{{ content | safe }}  <!-- 이스케이프 해제 - 주의해서 사용 -->
```

### 6. 보안 헤더

**구현 위치:** `app/__init__.py`

```python
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    if not app.debug:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response
```

**헤더 설명:**
- `X-Content-Type-Options`: MIME 타입 스니핑 방지
- `X-Frame-Options`: 클릭재킹 공격 방지
- `X-XSS-Protection`: XSS 필터 활성화
- `Strict-Transport-Security`: HTTPS 강제 (프로덕션)

---

## ⚡ 성능 최적화

### 1. 이미지 자동 리사이징

**구현 위치:** `app/utils/image_processing.py`

**설정:**
- 최대 이미지 크기: 1920px (환경변수 `MAX_IMAGE_SIZE`)
- 최대 파일 크기: 1MB (환경변수 `MAX_IMAGE_FILE_SIZE`)
- 기본 품질: 85%

**기능:**
- EXIF Orientation 자동 보정
- 자동 리사이징 (비율 유지)
- RGB 변환 (투명도 제거)
- 품질 조정을 통한 파일 크기 최적화
- JPEG 압축 최적화

```python
from app.utils.image_processing import optimize_image, save_upload_image

# 이미지 업로드 처리
if file:
    filename = save_upload_image(
        file,
        upload_folder='app/static/uploads',
        max_size=1920,
        max_file_size=1024*1024
    )
```

**성능 개선:**
- 저장 공간 절약: 평균 70-80% 감소
- 페이지 로딩 속도 향상
- 대역폭 절약

### 2. 데이터베이스 인덱스

**적용된 인덱스:**

```python
# Users 테이블
class User(db.Model):
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    nickname = db.Column(db.String(20), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

# Posts 테이블
class Post(db.Model):
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    board_id = db.Column(db.Integer, db.ForeignKey('boards.id'), index=True)

# Comments 테이블
class Comment(db.Model):
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

# LoginAttempt 테이블
class LoginAttempt(db.Model):
    email = db.Column(db.String(120), nullable=False, index=True)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
```

**성능 개선:**
- 로그인 쿼리 속도 향상
- 게시글 목록 조회 최적화
- 댓글 로딩 속도 개선
- 관리자 대시보드 통계 쿼리 최적화

### 3. PostgreSQL 연결 풀링

**구현 위치:** `config.py`

```python
class Config:
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,      # 연결 유효성 사전 검사
        'pool_recycle': 300,        # 5분마다 연결 재생성
        'pool_size': 10,            # 기본 연결 풀 크기
        'max_overflow': 20          # 최대 추가 연결 수
    }
```

**성능 개선:**
- 데이터베이스 연결 재사용
- 연결 오버헤드 감소
- 동시 사용자 처리 능력 향상

### 4. 페이지네이션

**설정:**
- 페이지당 게시글 수: 20개 (환경변수 `POSTS_PER_PAGE`)

**구현 예시:**
```python
posts = Post.query.paginate(
    page=page,
    per_page=app.config['POSTS_PER_PAGE'],
    error_out=False
)
```

**성능 개선:**
- 대량 데이터 로딩 방지
- 메모리 사용량 최적화
- 페이지 렌더링 속도 향상

---

## 🛡️ 안정성 개선

### 1. 에러 페이지

**구현 위치:**
- `app/templates/errors/404.html` - 페이지를 찾을 수 없음
- `app/templates/errors/500.html` - 서버 오류

**에러 핸들러:** `app/__init__.py`
```python
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
```

### 2. 로깅 시스템

**구현 위치:** `app/__init__.py`

**설정:**
- 로그 파일: `logs/nr2.log` (환경변수 `LOG_FILE`)
- 로그 레벨: INFO (환경변수 `LOG_LEVEL`)
- 파일 크기: 10MB 최대
- 백업 파일: 10개 유지

```python
from logging.handlers import RotatingFileHandler

file_handler = RotatingFileHandler(
    'logs/nr2.log',
    maxBytes=10240000,  # 10MB
    backupCount=10
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(file_handler)
```

**로그 기록 예시:**
```python
app.logger.info('User logged in: %s', user.email)
app.logger.warning('Failed login attempt: %s', email)
app.logger.error('Database error: %s', str(e))
```

### 3. 자동 백업

**스크립트:** `backup.sh`

**기능:**
- 데이터베이스 자동 백업
- 업로드 파일 백업
- Gzip 압축
- 구버전 자동 삭제 (DB: 30개, 업로드: 7개 유지)

**사용법:**
```bash
# 수동 실행
./backup.sh

# Cron 등록 (매일 새벽 2시)
0 2 * * * /path/to/nr2/backup.sh
```

### 4. 환경변수 분리

**파일:**
- `.env` - 실제 환경변수 (Git 제외)
- `.env.example` - 템플릿

**주요 환경변수:**
```bash
# Flask
FLASK_ENV=production
SECRET_KEY=your-secret-key-here
FLASK_DEBUG=False

# Database
DATABASE_URL=postgresql://user:pass@localhost/nr2

# Security
MAX_LOGIN_ATTEMPTS=5
LOCKOUT_DURATION=1800

# Upload
MAX_CONTENT_LENGTH=16777216
MAX_IMAGE_SIZE=1920
MAX_IMAGE_FILE_SIZE=1048576

# Pagination
POSTS_PER_PAGE=20

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/nr2.log
```

---

## 🚀 배포 준비

### 1. Requirements

**파일:** `requirements.txt`

**주요 의존성:**
- Flask 3.0.0+
- Flask-SQLAlchemy
- Flask-Login
- Flask-Migrate
- Flask-WTF (CSRF 보호)
- psycopg2-binary (PostgreSQL)
- gunicorn (WSGI 서버)
- Pillow (이미지 처리)

### 2. Procfile

**Railway/Heroku 배포 설정:**
```
web: gunicorn run:app --bind 0.0.0.0:$PORT --workers 4 --timeout 120
```

**Workers 수 권장:**
- CPU 코어 수 * 2 + 1
- 예: 2코어 = 5 workers

### 3. Runtime

**파일:** `runtime.txt`
```
python-3.11.7
```

### 4. Railway 설정

**파일:** `railway.json`
```json
{
  "build": {
    "builder": "NIXPACKS",
    "buildCommand": "pip install -r requirements.txt && flask db upgrade"
  },
  "deploy": {
    "startCommand": "gunicorn run:app --bind 0.0.0.0:$PORT --workers 4"
  }
}
```

### 5. 프로덕션 설정

**config.py - ProductionConfig:**
```python
class ProductionConfig(Config):
    DEBUG = False
    TESTING = False

    # PostgreSQL URL 자동 변환
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith('postgres://'):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            'postgres://', 'postgresql://', 1
        )

    # 보안 쿠키
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
```

---

## ✅ 보안 체크리스트

배포 전 확인사항:

- [ ] SECRET_KEY를 무작위 강력한 값으로 변경
- [ ] DEBUG=False 설정 확인
- [ ] 데이터베이스 URL 환경변수 설정
- [ ] CSRF 보호 활성화 확인
- [ ] 비밀번호 강도 검사 작동 확인
- [ ] 로그인 시도 제한 테스트
- [ ] XSS 필터링 확인
- [ ] 보안 헤더 설정 확인
- [ ] HTTPS 설정 (Railway 자동)
- [ ] 에러 페이지 확인
- [ ] 로그 시스템 작동 확인
- [ ] 백업 스크립트 테스트
- [ ] 이미지 최적화 작동 확인
- [ ] PostgreSQL 연결 확인
- [ ] 프로덕션 환경변수 설정 완료

---

## 📊 성능 벤치마크 (예상)

### 이미지 최적화

| 항목 | 최적화 전 | 최적화 후 | 개선율 |
|------|----------|----------|--------|
| 평균 파일 크기 | 3.5MB | 850KB | 75% ↓ |
| 페이지 로딩 시간 | 4.2초 | 1.3초 | 69% ↓ |
| 저장 공간 | 1GB | 250MB | 75% ↓ |

### 데이터베이스 쿼리

| 쿼리 | 인덱스 전 | 인덱스 후 | 개선율 |
|------|----------|----------|--------|
| 로그인 조회 | 120ms | 8ms | 93% ↓ |
| 게시글 목록 | 250ms | 35ms | 86% ↓ |
| 댓글 로딩 | 180ms | 22ms | 88% ↓ |

---

## 🔍 모니터링

### Railway 대시보드

- **로그 확인:** Railway Dashboard → Logs
- **리소스 사용량:** CPU, 메모리, 네트워크 모니터링
- **데이터베이스:** PostgreSQL 플러그인 상태 확인

### 로그 파일

```bash
# 로컬 로그 확인
tail -f logs/nr2.log

# Railway에서 로그 확인
railway logs

# 에러 필터링
railway logs | grep ERROR
```

---

## 🆘 트러블슈팅

### 로그인 잠금 해제

Railway Shell에서 실행:
```python
from app import create_app, db
from app.models import LoginAttempt

app = create_app('production')
with app.app_context():
    # 특정 이메일의 로그인 시도 기록 삭제
    LoginAttempt.query.filter_by(email='user@example.com').delete()
    db.session.commit()
    print('Login attempts cleared!')
```

### 이미지 재최적화

```python
from app.utils.image_processing import optimize_image
import os

upload_folder = 'app/static/uploads'
for filename in os.listdir(upload_folder):
    if filename.endswith(('.jpg', '.jpeg', '.png')):
        filepath = os.path.join(upload_folder, filename)
        optimize_image(filepath)
```

### 로그 분석

```bash
# 에러 로그 추출
grep ERROR logs/nr2.log > errors.log

# 로그인 실패 통계
grep "Failed login" logs/nr2.log | wc -l

# 날짜별 로그 필터
grep "2024-01-15" logs/nr2.log
```

---

## 📚 추가 리소스

- [Flask Security Best Practices](https://flask.palletsprojects.com/en/latest/security/)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [Railway Documentation](https://docs.railway.app)
- [PostgreSQL Performance](https://www.postgresql.org/docs/current/performance-tips.html)
- [Gunicorn Configuration](https://docs.gunicorn.org/en/stable/configure.html)

---

## 📝 변경 이력

| 날짜 | 버전 | 변경 내용 |
|------|------|----------|
| 2024-01-15 | 1.0.0 | 초기 보안 및 성능 강화 구현 |

---

## 👥 문의

문제 발생 시:
1. `logs/nr2.log` 확인
2. Railway Logs 확인
3. GitHub Issues 등록
4. Railway Discord 커뮤니티
