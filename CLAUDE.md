# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NR2 is a Flask-based Korean community platform for news and information sharing. It features multi-board discussions, a voting system, breaking news, and an admin dashboard. Deployed on Railway with PostgreSQL.

## Common Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run development server (port 5001)
python run.py

# Database migrations
flask db migrate -m "description"
flask db upgrade
flask db downgrade

# Run tests
python Tests/test_login.py          # single test
python -m pytest Tests/test_*.py   # all tests
```

## Architecture

**Entry point:** `run.py` → `app/__init__.py` (app factory) → blueprints registered from `app/routes/`

**7 Blueprints:**
- `auth` — registration, login, profile, image upload
- `boards` — posts (4 board types), comments, likes, search, pagination
- `main` — homepage
- `admin` — dashboard with full CRUD over users/posts/comments/votes/news
- `votes` — poll creation and voting
- `calendar` — events
- `news` — breaking news (admin-only creation)

**Database:** SQLite in dev, PostgreSQL in production. Models in `app/models/` — key relationships: User → Posts → Comments/Likes/Images; Vote → VoteOption → VoteResponse.

**Configuration:** `config.py` defines `DevelopmentConfig`, `ProductionConfig`, `TestingConfig`. Active config is selected via `FLASK_ENV`. Key settings: 20 posts/page, max 16MB uploads, 5 login attempts before 30-min lockout.

**Templates:** Jinja2 + Tailwind CSS + Alpine.js. All templates extend `app/templates/layouts/base.html`.

## Board Types

Four boards identified by `board_type` string:
- `free` — 자유정보 (Free Information)
- `left` — LEFT정보 (Progressive News)
- `right` — RIGHT정보 (Conservative News)
- `fact` — 팩트체크 (Fact-Checking)

## Key Patterns

- Admin routes use `@admin_required` decorator (defined in `app/routes/admin.py`)
- File uploads go to `app/static/uploads/` (profile images and post images handled separately via `app/utils/image_processing.py`)
- CSRF protection is active on all forms via Flask-WTF
- Login brute-force tracking via `LoginAttempt` model (stores IP + email + timestamp)

## Environment Variables

Copy `.env.example` to `.env`. Required for production:
- `SECRET_KEY`, `DATABASE_URL`, `FLASK_ENV`
- Optional: `MAX_LOGIN_ATTEMPTS`, `LOCKOUT_DURATION`, `POSTS_PER_PAGE`, `LOG_LEVEL`

## Deployment

Production runs on Railway. `Procfile`:
```
web: gunicorn run:app --bind 0.0.0.0:$PORT --workers 4 --timeout 120
```
Python 3.11 (see `runtime.txt`). See `Documentation/DEPLOYMENT.md` for full Railway setup.

## Bots

`Bots/` contains standalone async Telegram bots for news scraping — these run independently from the main app and are not part of the Flask application.
