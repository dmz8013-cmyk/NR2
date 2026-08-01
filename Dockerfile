FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required by python packages and playwright
#  - tzdata       : ZoneInfo("Asia/Seoul") 등 zoneinfo 조회 (slim 이미지 기본 미포함)
#  - fonts-noto-* : 카드뉴스 chromium 렌더 시 한글/이모지 폰트 폴백
#    (Pretendard 는 CDN 로드하지만, CDN 실패·이모지(🐕) 대비용 안전망)
RUN apt-get update && apt-get install -y \
    gcc libpq-dev wget tzdata \
    fonts-noto-cjk fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*
ENV TZ=Asia/Seoul

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright installation
RUN pip install playwright
RUN playwright install chromium
RUN playwright install-deps chromium

COPY . .

# CMD uses shell-form via sh -c to expand $PORT (Railway injects at runtime).
# NR2 (scheduler) service overrides this via UI Start Command.
CMD ["sh", "-c", "exec gunicorn run:app --bind 0.0.0.0:${PORT:-5000} --workers 4 --timeout 120 --access-logfile - --error-logfile -"]
