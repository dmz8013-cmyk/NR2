import os
from flask import Blueprint, request, jsonify
import anthropic
from app import csrf

kakao_bp = Blueprint('kakao_bp', __name__, url_prefix='/kakao')

@kakao_bp.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    try:
        data = request.json
        utterance = data['userRequest']['utterance']
        
        client = anthropic.Anthropic(
            api_key=os.environ.get('ANTHROPIC_API_KEY')
        )
        
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            system="당신은 누렁이입니다. SOB Production이 운영하는 AI 어시스턴트입니다. 국제정치, AI, 한국 시사에 대해 날카롭고 친근하게 핵심만 짧게 답합니다. 존댓말 사용.",
            messages=[
                {"role": "user", "content": utterance}
            ]
        )
        
        reply_text = response.content[0].text
        
        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": reply_text
                        }
                    }
                ]
            }
        })
        
    except Exception as e:
        return jsonify({
            "version": "2.0",
            "template": {
                "outputs": [
                    {
                        "simpleText": {
                            "text": "잠시 후 다시 시도해주세요."
                        }
                    }
                ]
            }
        })
