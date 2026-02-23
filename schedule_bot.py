"""누렁이 일정봇 - 매일 아침 주요 일정 전송 (개인 텔레그램)"""
import os
import requests
import logging
from bs4 import BeautifulSoup
from datetime import datetime

logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get('SCHEDULE_BOT_TOKEN', '8734510853:AAHsqC3fQfC0K02-xrWEZgnh9ZDGUIi2P44')
CHAT_ID = '5132309076'

HEADERS = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'}


def get_news1_schedule():
    """뉴스1에서 오늘의 주요 일정 기사 크롤링"""
    try:
        today = datetime.now().strftime('%Y%m%d')
        today_kr = datetime.now().strftime('%m월 %d일')
        
        # 뉴스1 검색
        url = f"https://www.news1.kr/search?query=주요일정+{today_kr}"
        res = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 기사 링크 찾기
        links = soup.select('a')
        schedule_url = None
        for link in links:
            text = link.get_text(strip=True)
            href = link.get('href', '')
            if '주요 일정' in text and href.startswith('http'):
                schedule_url = href
                break
            if '일정' in text and today_kr.replace('0', '') in text and href.startswith('http'):
                schedule_url = href
                break
        
        if not schedule_url:
            # 네이버 검색 대안
            naver_url = f"https://search.naver.com/search.naver?query=뉴스1+오늘의+주요일정+{today_kr}"
            res2 = requests.get(naver_url, headers=HEADERS, timeout=10)
            soup2 = BeautifulSoup(res2.text, 'html.parser')
            for a in soup2.select('a'):
                href = a.get('href', '')
                if 'news1.kr' in href and ('일정' in a.get_text(strip=True)):
                    schedule_url = href
                    break
        
        if schedule_url:
            art_res = requests.get(schedule_url, headers=HEADERS, timeout=10)
            art_soup = BeautifulSoup(art_res.text, 'html.parser')
            
            # 기사 본문 추출
            body = art_soup.select_one('.article_body, .content, #articleBody, .news_body')
            if body:
                return body.get_text('\n', strip=True)
            
            # 대안: p 태그
            paragraphs = art_soup.select('article p, .article p')
            if paragraphs:
                return '\n'.join(p.get_text(strip=True) for p in paragraphs)
        
        return None
    except Exception as e:
        logger.error(f"뉴스1 일정 크롤링 실패: {e}")
        return None


def get_assembly_schedule():
    """국회 오늘 일정 크롤링"""
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        url = f"https://www.assembly.go.kr/portal/bbs/B0000052/contents.do"
        res = requests.get(url, headers=HEADERS, timeout=10)
        
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            schedule_items = soup.select('.schedule_list li, .cal_schedule li, td.on .schedule')
            if schedule_items:
                items = [item.get_text(strip=True) for item in schedule_items[:20]]
                return '\n'.join(items)
        return None
    except Exception as e:
        logger.error(f"국회 일정 크롤링 실패: {e}")
        return None


def send_schedule():
    """일정 취합 후 텔레그램 전송"""
    today_str = datetime.now().strftime('%Y년 %m월 %d일 (%a)')
    day_names = {'Mon': '월', 'Tue': '화', 'Wed': '수', 'Thu': '목', 'Fri': '금', 'Sat': '토', 'Sun': '일'}
    for eng, kor in day_names.items():
        today_str = today_str.replace(eng, kor)
    
    message_parts = [f"📌 <b>{today_str} 주요 일정</b> 📌\n"]
    
    # 뉴스1 일정
    news1 = get_news1_schedule()
    if news1:
        # 너무 길면 앞부분만
        if len(news1) > 3500:
            news1 = news1[:3500] + "\n\n... (이하 생략)"
        message_parts.append(news1)
    else:
        message_parts.append("⚠️ 뉴스1 일정 기사를 찾지 못했습니다.")
    
    message = '\n'.join(message_parts)
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            'chat_id': CHAT_ID,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True,
        }, timeout=10)
        
        if resp.status_code == 200:
            logger.info("일정봇 전송 완료 ✅")
            print("일정봇 전송 완료 ✅")
        else:
            logger.error(f"일정봇 전송 실패: {resp.text}")
            print(f"전송 실패: {resp.text}")
    except Exception as e:
        logger.error(f"일정봇 전송 오류: {e}")
        print(f"전송 오류: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    send_schedule()
