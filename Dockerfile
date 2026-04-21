FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required by python packages and playwright
RUN apt-get update && apt-get install -y \
    gcc libpq-dev wget \
    && rm -rf /var/lib/apt/lists/*

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
