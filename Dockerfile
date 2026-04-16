FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1
ENV PORT=5000

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

# CMD is handled by Railway Start Command (web or worker)
CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:5000", "--workers", "4"]
