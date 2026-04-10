import os
import re
import json
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
AESA_CHANNEL = "@nr2aesa"       # 채널 username
INFO_GROUP_ID = os.environ.get("TELEGRAM_INFO_GROUP_ID", "")  # 정보방 group_id (음수값)

def get_message_stats(channel, message_id):
    """
    웹 페이지 임베드 URL을 활용하여 메시지 뷰수와 전체 리액션 수 수집합니다.
    참고: 텔레그램 공식 Bot API 단말에는 특정 메시지 내역을 조회하는 'getMessages'나 
    'getMessageReactionCount' 메소드가 기본적으로 제공되지 않습니다 (MTProto Client API 사용 필요).
    따라서 requests를 이용한 embed 페이지 정보 파싱 방식이 가장 가볍고 확실한 대안입니다.
    """
    channel_name = channel.lstrip('@')
    url = f"https://t.me/{channel_name}/{message_id}?embed=1"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        text = r.text
        
        # 1. 뷰수(Views) 파싱
        views = 0
        views_match = re.search(r'<span class="tgme_widget_message_views">([^<]+)</span>', text)
        if views_match:
            views_str = views_match.group(1).strip()
            # "1.2K", "1.5M" 형식 대응
            if 'K' in views_str.upper():
                views = int(float(views_str.upper().replace('K', '')) * 1000)
            elif 'M' in views_str.upper():
                views = int(float(views_str.upper().replace('M', '')) * 1000000)
            else:
                views = int(views_str.replace(',', ''))
                
        # 2. 리액션(Reactions) 수 파싱 합계
        reactions_count = 0
        reactions_match = re.search(r'var TWidgetReactions\s*=\s*(\[.*?\]);', text)
        if reactions_match:
            try:
                reactions_data = json.loads(reactions_match.group(1))
                reactions_count = sum(item.get('count', 0) for item in reactions_data)
            except json.JSONDecodeError:
                pass
                
        return views, reactions_count

    except requests.RequestException as e:
        print(f"Error fetching stats for message {message_id}: {e}")
        return 0, 0


def get_message_views(channel, message_id):
    """개별 메시지 뷰수만 반환"""
    views, _ = get_message_stats(channel, message_id)
    return views


def get_reactions(channel, message_id):
    """메시지 리액션 수 합계만 반환"""
    _, reactions = get_message_stats(channel, message_id)
    return reactions


def get_channel_messages(limit=50):
    """
    AESA 채널 개별 메시지의 뷰수/리액션을 갱신 (DB에 저장된 message_id 활용).
    채널의 메시지는 bot api의 getUpdates로 즉시 조회가 불가하므로, 저장된 DB를 스캔하는 용도로 사용.
    """
    # 실제 운영 시에는 다음과 같이 구현:
    # 1. DB (예: AesaArticle) 에서 telegram_message_id가 있는 최근 기사 limit개를 조회
    # 2. 각 message_id 별로 get_message_stats() 호출하여 값 갱신
    # 3. DB commit
    
    # 예시 코드
    """
    articles = AesaArticle.query.filter(AesaArticle.telegram_message_id.isnot(None)) \
                                .order_by(AesaArticle.id.desc()).limit(limit).all()
    for article in articles:
        views, reactions = get_message_stats(AESA_CHANNEL, article.telegram_message_id)
        article.views = views
        article.reactions = reactions
    db.session.commit()
    """
    pass


if __name__ == "__main__":
    # 간단한 테스트
    test_id = 100  # @nr2aesa 채널에 실제로 존재하는 게시물 번호로 변경 가능
    print(f"[{AESA_CHANNEL}] 게시물 번호 {test_id} 통계 조회 테스트 중...")
    
    views, reactions = get_message_stats(AESA_CHANNEL, test_id)
    
    print("-" * 30)
    print(f"Views: {views}")
    print(f"Reactions: {reactions}")
    print("-" * 30)
