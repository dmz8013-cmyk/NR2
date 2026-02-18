# 🚀 NR2 배포 가이드 (Railway)

## 준비사항

### 1. Railway 계정 생성
- https://railway.app 접속
- GitHub 계정으로 로그인

### 2. PostgreSQL 플러그인 추가
1. Railway 대시보드에서 "New Project" 클릭
2. "Deploy from GitHub repo" 선택
3. NR2 저장소 선택
4. "Add Plugin" → "PostgreSQL" 추가

## 환경변수 설정

Railway 프로젝트 설정에서 다음 환경변수를 추가하세요:

```bash
# Flask Configuration
FLASK_ENV=production
SECRET_KEY=your-super-secret-key-change-this-in-production
FLASK_DEBUG=False

# Database (Railway가 자동으로 설정)
# DATABASE_URL은 자동으로 생성됨

# Security
MAX_LOGIN_ATTEMPTS=5
LOCKOUT_DURATION=1800

# Upload Configuration
MAX_CONTENT_LENGTH=16777216
MAX_IMAGE_SIZE=1920
MAX_IMAGE_FILE_SIZE=1048576

# Pagination
POSTS_PER_PAGE=20

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/nr2.log
```

## 배포 단계

### 1. 코드 준비

```bash
# 의존성 확인
pip install -r requirements.txt

# 데이터베이스 마이그레이션 생성
flask db init  # 최초 1회만
flask db migrate -m "Initial migration"
flask db upgrade

# 로컬에서 테스트
python run.py
```

### 2. Git 저장소 설정

```bash
# Git 초기화 (아직 안 했다면)
git init

# .gitignore 확인
# .env, *.db, __pycache__ 등이 포함되어 있는지 확인

# 커밋
git add .
git commit -m "Initial commit for deployment"

# GitHub에 푸시
git remote add origin https://github.com/your-username/nr2.git
git branch -M main
git push -u origin main
```

### 3. Railway 배포

1. **프로젝트 연결**
   - Railway 대시보드에서 "New Project"
   - "Deploy from GitHub repo" 선택
   - NR2 저장소 선택

2. **PostgreSQL 추가**
   - "Add Plugin" → "PostgreSQL"
   - DATABASE_URL이 자동으로 설정됨

3. **환경변수 설정**
   - Settings → Variables
   - 위의 환경변수들 추가

4. **배포 완료**
   - Railway가 자동으로 빌드 및 배포
   - 5-10분 소요

## 배포 후 확인

### 1. 데이터베이스 초기화

Railway Shell에서 실행:

```bash
# Railway Shell 접속
# Railway Dashboard → Shell

# 데이터베이스 마이그레이션
flask db upgrade

# 관리자 계정 생성 (Python Shell)
python
>>> from app import create_app, db
>>> from app.models import User
>>> app = create_app('production')
>>> with app.app_context():
>>>     admin = User(email='admin@nr2.com', nickname='관리자', is_admin=True)
>>>     admin.set_password('YourSecurePassword123')
>>>     db.session.add(admin)
>>>     db.session.commit()
>>>     print('Admin created!')
```

### 2. 도메인 확인

```bash
# Railway가 제공하는 URL 확인
# https://your-app.up.railway.app

# 커스텀 도메인 설정 (선택사항)
# Settings → Domains → Add Domain
```

## 모니터링

### 로그 확인

```bash
# Railway Dashboard → Logs
# 실시간 로그 확인 가능
```

### 데이터베이스 백업

```bash
# Railway에서 PostgreSQL 백업 설정
# PostgreSQL Plugin → Backups

# 로컬 백업 (Railway CLI 필요)
railway run python -c "
from app import create_app, db
import subprocess
app = create_app('production')
with app.app_context():
    subprocess.run(['pg_dump', '-Fc', 'DATABASE_URL', '-f', 'backup.dump'])
"
```

## 트러블슈팅

### 빌드 실패

```bash
# requirements.txt 확인
# Python 버전 확인 (runtime.txt)
# Procfile 문법 확인
```

### 데이터베이스 연결 오류

```bash
# DATABASE_URL 환경변수 확인
# PostgreSQL 플러그인 상태 확인
# config.py의 URL 변환 로직 확인 (postgres:// → postgresql://)
```

### 정적 파일 문제

```bash
# Railway는 자동으로 정적 파일 서빙
# app/static/ 경로 확인
# 필요시 CDN 사용 권장 (Cloudflare, AWS S3)
```

## 성능 최적화

### 1. Gunicorn Workers

```bash
# Procfile에서 workers 수 조정
web: gunicorn run:app --bind 0.0.0.0:$PORT --workers 4

# 권장: CPU 코어 수 * 2 + 1
```

### 2. 데이터베이스 인덱스

```bash
# 자주 조회되는 컬럼에 인덱스 추가
# models 파일에서 index=True 설정 확인
```

### 3. 이미지 최적화

```bash
# 업로드된 이미지 자동 리사이징 (구현됨)
# MAX_IMAGE_SIZE=1920
# MAX_IMAGE_FILE_SIZE=1048576
```

## 보안 체크리스트

- [ ] SECRET_KEY 변경
- [ ] DEBUG=False 설정
- [ ] HTTPS 강제 (Railway 자동)
- [ ] CSRF 보호 활성화 (구현됨)
- [ ] 비밀번호 강도 검사 (구현됨)
- [ ] 로그인 시도 제한 (구현됨)
- [ ] SQL Injection 방지 (SQLAlchemy)
- [ ] XSS 필터링 (구현됨)
- [ ] 보안 헤더 설정 (구현됨)

## 비용 예상

Railway Free Tier:
- $5 credit/month
- 500시간 실행 시간
- PostgreSQL 1GB

추정 비용:
- 소규모 (~100 사용자): Free tier
- 중규모 (~1000 사용자): $10-20/month
- 대규모 (1000+ 사용자): $50+/month

## 추가 리소스

- Railway 문서: https://docs.railway.app
- PostgreSQL 가이드: https://www.postgresql.org/docs/
- Flask 프로덕션 가이드: https://flask.palletsprojects.com/en/latest/deploying/

## 문의

문제가 발생하면:
1. Railway Logs 확인
2. GitHub Issues 등록
3. Railway Discord 커뮤니티
