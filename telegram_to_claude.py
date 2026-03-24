#!/usr/bin/env python3
"""
텔레그램 → Claude Code 브릿지
텔레그램에서 보낸 메시지를 Claude Code에 전달하고 결과를 텔레그램으로 회신.

사용법:
  1. .env에 CLAUDE_BRIDGE_BOT_TOKEN, CLAUDE_BRIDGE_CHAT_ID 설정
  2. python telegram_to_claude.py

chat_id 모르면:
  CLAUDE_BRIDGE_BOT_TOKEN만 설정 후 실행 → 봇에 아무 메시지 보내면 chat_id 출력됨
"""
import os
import sys
import subprocess
import time
import signal
import requests
from datetime import datetime

# ─── 설정 ───────────────────────────────────────
BOT_TOKEN = os.environ.get("CLAUDE_BRIDGE_BOT_TOKEN", "")
ALLOWED_CHAT_ID = os.environ.get("CLAUDE_BRIDGE_CHAT_ID", "")
NR2_DIR = os.path.dirname(os.path.abspath(__file__))  # NR2 프로젝트 루트
MAX_RESPONSE_LEN = 4000  # 텔레그램 메시지 길이 제한

# ─── 안전 장치 ──────────────────────────────────
# 금지 패턴: 시스템 파괴 방지
BLOCKED_PATTERNS = [
    "rm -rf",
    "sudo ",
    "chmod 777",
    "mkfs",
    "> /dev/",
    "dd if=",
    ":(){ :|:& };:",
]

running = True


def signal_handler(sig, frame):
    global running
    print("\n🛑 브릿지 종료 중...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def send_telegram(chat_id: str, text: str):
    """텔레그램으로 메시지 전송"""
    # 텔레그램 4096자 제한 대응
    if len(text) > MAX_RESPONSE_LEN:
        text = text[:MAX_RESPONSE_LEN] + "\n\n⚠️ (응답이 길어서 잘림)"

    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
    except Exception as e:
        print(f"  ❌ 텔레그램 전송 실패: {e}")


def is_safe_command(text: str) -> bool:
    """위험한 명령어 패턴 검사"""
    lower = text.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in lower:
            return False
    return True


def run_claude(prompt: str) -> str:
    """Claude Code CLI 실행 후 결과 반환"""
    try:
        result = subprocess.run(
            ["claude", "-p", "--output-format", "text", prompt],
            cwd=NR2_DIR,
            capture_output=True,
            text=True,
            timeout=300,  # 5분 타임아웃
        )
        output = result.stdout.strip()
        if result.returncode != 0 and result.stderr:
            output += f"\n\n⚠️ stderr: {result.stderr.strip()[:500]}"
        return output if output else "(빈 응답)"
    except subprocess.TimeoutExpired:
        return "⏰ 타임아웃: 5분 초과. 복잡한 작업은 직접 실행해주세요."
    except FileNotFoundError:
        return "❌ 'claude' CLI를 찾을 수 없습니다. Claude Code가 설치되어 있는지 확인하세요."
    except Exception as e:
        return f"❌ 실행 오류: {e}"


def main():
    if not BOT_TOKEN:
        print("❌ CLAUDE_BRIDGE_BOT_TOKEN 환경변수를 설정하세요.")
        print("   export CLAUDE_BRIDGE_BOT_TOKEN='your-bot-token'")
        sys.exit(1)

    # chat_id 확인 모드
    if not ALLOWED_CHAT_ID:
        print("=" * 50)
        print("📋 chat_id 확인 모드")
        print("   텔레그램에서 이 봇에 아무 메시지를 보내세요.")
        print("   chat_id가 출력되면 .env에 추가하세요.")
        print("=" * 50)

    print(f"\n🤖 텔레그램 → Claude 브릿지 시작")
    print(f"   작업 디렉토리: {NR2_DIR}")
    if ALLOWED_CHAT_ID:
        print(f"   허용 chat_id: {ALLOWED_CHAT_ID}")
    else:
        print(f"   ⚠️  chat_id 미설정 — 확인 모드로 동작")
    print(f"   시작 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    offset = 0
    while running:
        try:
            res = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35,
            )
            data = res.json()

            if not data.get("ok"):
                print(f"❌ API 오류: {data}")
                time.sleep(5)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "")
                sender = msg.get("from", {}).get("first_name", "?")

                if not text:
                    continue

                # chat_id 확인 모드
                if not ALLOWED_CHAT_ID:
                    print(f"\n📌 메시지 수신!")
                    print(f"   보낸 사람: {sender}")
                    print(f"   chat_id: {chat_id}")
                    print(f"\n   👉 .env에 추가하세요:")
                    print(f"   CLAUDE_BRIDGE_CHAT_ID={chat_id}")
                    send_telegram(
                        chat_id,
                        f"✅ 당신의 chat_id: <code>{chat_id}</code>\n\n"
                        f".env에 CLAUDE_BRIDGE_CHAT_ID={chat_id} 를 추가하고 "
                        f"브릿지를 재시작하세요.",
                    )
                    continue

                # 보안: 본인 chat_id만 허용
                if chat_id != ALLOWED_CHAT_ID:
                    print(f"  🚫 차단됨: chat_id={chat_id}, sender={sender}")
                    continue

                # 특수 명령어
                if text == "/status":
                    send_telegram(
                        chat_id,
                        f"✅ 브릿지 가동 중\n"
                        f"📂 {NR2_DIR}\n"
                        f"🕐 {datetime.now().strftime('%H:%M:%S')}",
                    )
                    continue

                if text == "/help":
                    send_telegram(
                        chat_id,
                        "🤖 <b>Claude 브릿지 명령어</b>\n\n"
                        "일반 텍스트 → Claude Code에 전달\n"
                        "/status → 브릿지 상태 확인\n"
                        "/help → 도움말\n\n"
                        "예시:\n"
                        "<code>nr2.kr 자유게시판 글 목록 보여줘</code>\n"
                        "<code>git log --oneline -5</code>",
                    )
                    continue

                # 안전 검사
                if not is_safe_command(text):
                    send_telegram(chat_id, "🚫 보안 정책에 의해 차단된 명령입니다.")
                    print(f"  🚫 차단된 명령: {text[:50]}")
                    continue

                # Claude Code 실행
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(f"  [{timestamp}] 📩 {sender}: {text[:80]}")
                send_telegram(chat_id, f"⏳ 처리 중...\n<code>{text[:100]}</code>")

                result = run_claude(text)

                print(f"  [{datetime.now().strftime('%H:%M:%S')}] ✅ 응답 ({len(result)}자)")
                send_telegram(chat_id, f"🤖 <b>Claude 응답:</b>\n\n{result}")

        except requests.exceptions.Timeout:
            continue  # long polling 타임아웃은 정상
        except requests.exceptions.ConnectionError:
            print("  ⚠️ 네트워크 연결 오류, 5초 후 재시도...")
            time.sleep(5)
        except Exception as e:
            print(f"  ❌ 오류: {e}")
            time.sleep(3)

    print("👋 브릿지가 종료되었습니다.")


if __name__ == "__main__":
    main()
