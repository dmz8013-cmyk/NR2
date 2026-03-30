import os
import sys
import traceback

# app 모듈 경로 추가
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.utils.rss_briefing import run_briefing

def send_error_to_telegram(app_context, error_msg):
    """에러 발생 시 텔레그램으로 알림을 보냅니다."""
    with app_context:
        from flask import current_app
        import requests
        
        bot_token = current_app.config.get('TELEGRAM_BOT_TOKEN')
        chat_id = current_app.config.get('TELEGRAM_CHAT_ID')
        
        if not bot_token or not chat_id:
            return
            
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": f"🚨 [자동 브리핑 에러]\n\n{error_msg}",
            "parse_mode": "HTML"
        }
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception:
            pass


def main():
    try:
        app = create_app()
        ctx = app.app_context()
        
        print("데일리 브리핑 생성을 시작합니다...")
        success, msg = run_briefing(ctx)
        
        if success:
            print(f"브리핑 생성 완료: {msg}")
        else:
            print(f"브리핑 생성 실패: {msg}")
            send_error_to_telegram(ctx, f"브리핑 작업 실패: {msg}")
            
    except Exception as e:
        error_trace = traceback.format_exc()
        print(f"치명적 에러 발생:\n{error_trace}")
        
        # 긴급 에러 알림
        try:
            temp_app = create_app()
            send_error_to_telegram(temp_app.app_context(), f"크론잡 코드 에러: <pre>{str(e)}</pre>")
        except:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
