import os
import sys
from flask import Blueprint, request, session, redirect, url_for, jsonify, render_template_string

# telegram_stats.py 임포트를 위해 root 경로 추가
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from telegram_stats import get_message_stats, AESA_CHANNEL

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>AESA Telegram Dashboard</title>
    <style>
        body { font-family: sans-serif; padding: 20px; background-color: #f9f9f9; }
        .card { background: #fff; border: 1px solid #ddd; padding: 20px; border-radius: 8px; max-width: 500px; margin: 0 auto; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { text-align: center; }
        input[type="number"] { padding: 8px; width: calc(100% - 90px); margin-right: 10px; }
        button { padding: 8px 15px; background: #007bff; color: auto; color: white; border: none; border-radius: 4px; cursor: pointer; }
        button:hover { background: #0056b3; }
        .result-box { margin-top: 15px; padding: 15px; background: #e9ecef; border-radius: 4px; font-weight: bold; }
        .logout { float: right; background: #dc3545; }
        .logout:hover { background: #c82333; }
    </style>
</head>
<body>
    <form action="/dashboard/login" method="post" style="display: inline;">
        <input type="hidden" name="logout" value="true" />
        <button type="submit" class="logout">로그아웃</button>
    </form>
    <h1>AESA Telegram Dashboard</h1>
    <div class="card">
        <h3>통계 데이터 조회</h3>
        <div style="display: flex;">
            <input type="number" id="msgId" placeholder="Message ID (예: 100)" />
            <button onclick="fetchStats()">조회</button>
        </div>
        <div id="result" class="result-box" style="display: none;"></div>
    </div>
    
    <script>
        function fetchStats() {
            const msgId = document.getElementById('msgId').value;
            if(!msgId) return;
            
            const resultDiv = document.getElementById('result');
            resultDiv.style.display = 'block';
            resultDiv.innerText = "로딩 중...";
            
            fetch('/dashboard/api/stats?message_id=' + msgId)
                .then(res => res.json())
                .then(data => {
                    if(data.error) {
                        resultDiv.style.color = 'red';
                        resultDiv.innerText = "에러: " + data.error;
                    } else {
                        resultDiv.style.color = 'black';
                        resultDiv.innerText = `[${data.channel}] Message ID: ${data.message_id}\n👀 뷰 수 (Views): ${data.views}\n❤️ 리액션 (Reactions): ${data.reactions}`;
                    }
                })
                .catch(err => {
                    resultDiv.style.color = 'red';
                    resultDiv.innerText = "조회 실패";
                });
        }
    </script>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>대시보드 로그인</title>
    <style>
        body { font-family: sans-serif; background: #f0f2f5; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .login-box { background: white; padding: 30px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); text-align: center; }
        input[type="password"] { padding: 10px; margin-bottom: 20px; width: 100%; box-sizing: border-box; }
        button { padding: 10px 20px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; width: 100%; }
        button:hover { background: #0056b3; }
    </style>
</head>
<body>
    <div class="login-box">
        <h2>대시보드 로그인</h2>
        {% if error %}<p style="color:red; font-size: 14px;">{{ error }}</p>{% endif %}
        <form method="post">
            <input type="password" name="password" placeholder="비밀번호" required />
            <button type="submit">로그인</button>
        </form>
    </div>
</body>
</html>
"""

@dashboard_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if 'logout' in request.form:
            session.pop('dashboard_auth', None)
            return redirect(url_for('dashboard.login'))
            
        password = request.form.get('password')
        if password == os.environ.get('DASHBOARD_PASSWORD'):
            session['dashboard_auth'] = True
            return redirect(url_for('dashboard.index'))
        else:
            return render_template_string(LOGIN_HTML, error="비밀번호가 틀렸습니다.")
            
    if session.get('dashboard_auth'):
        return redirect(url_for('dashboard.index'))
        
    return render_template_string(LOGIN_HTML)

@dashboard_bp.route('')
def index():
    if not session.get('dashboard_auth'):
        return redirect(url_for('dashboard.login'))
    return render_template_string(DASHBOARD_HTML)

@dashboard_bp.route('/api/stats')
def api_stats():
    if not session.get('dashboard_auth'):
        return jsonify({'error': 'Unauthorized'}), 401
        
    message_id_str = request.args.get('message_id')
    if not message_id_str or not message_id_str.isdigit():
        return jsonify({'error': '유효하지 않은 message_id 입니다.'}), 400
        
    message_id = int(message_id_str)
    
    # telegram_stats.py 함수 호출
    views, reactions = get_message_stats(AESA_CHANNEL, message_id)
    
    return jsonify({
        'channel': AESA_CHANNEL,
        'message_id': message_id,
        'views': views,
        'reactions': reactions
    })
