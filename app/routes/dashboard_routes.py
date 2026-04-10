import os
import sys
from flask import Blueprint, request, session, redirect, url_for, jsonify, render_template_string

# telegram_stats.py 임포트를 위해 root 경로 추가
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from telegram_stats import get_message_stats, AESA_CHANNEL

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>누렁이 대시보드</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif; background: #0f0f0f; color: #e8e8e8; min-height: 100vh; padding: 24px; }
.header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 28px; }
.header-left h1 { font-size: 18px; font-weight: 600; color: #fff; letter-spacing: -0.02em; }
.header-left p { font-size: 12px; color: #666; margin-top: 4px; }
.refresh-btn { background: #1a1a1a; border: 1px solid #2a2a2a; color: #888; font-size: 12px; padding: 8px 14px; border-radius: 8px; cursor: pointer; }
.tabs { display: flex; gap: 6px; margin-bottom: 24px; }
.tab { padding: 7px 16px; border-radius: 8px; font-size: 13px; cursor: pointer; border: 1px solid #2a2a2a; background: transparent; color: #666; }
.tab.active { background: #C87941; border-color: #C87941; color: #fff; font-weight: 500; }
.metrics-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 20px; }
.metric { background: #1a1a1a; border: 1px solid #222; border-radius: 10px; padding: 16px; }
.metric-label { font-size: 11px; color: #555; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 8px; }
.metric-value { font-size: 26px; font-weight: 600; color: #fff; letter-spacing: -0.03em; }
.metric-delta { font-size: 11px; margin-top: 5px; }
.delta-up { color: #4ade80; }
.delta-down { color: #f87171; }
.charts-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.card { background: #1a1a1a; border: 1px solid #222; border-radius: 10px; padding: 18px; }
.card-label { font-size: 11px; color: #555; text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 14px; }
.top-row { display: flex; align-items: center; gap: 12px; padding: 11px 0; border-bottom: 1px solid #1e1e1e; }
.top-row:last-child { border-bottom: none; }
.rank { font-size: 11px; color: #444; width: 18px; flex-shrink: 0; font-weight: 600; }
.art-info { flex: 1; min-width: 0; }
.art-title { font-size: 13px; color: #ddd; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.art-meta { font-size: 11px; color: #555; margin-top: 3px; }
.art-views { font-size: 13px; font-weight: 600; color: #C87941; flex-shrink: 0; }
.lens-badge { display: inline-block; font-size: 10px; padding: 1px 5px; border-radius: 3px; margin-right: 5px; font-weight: 600; }
.la { background: #1a2a3a; color: #5ba3d9; }
.lb { background: #1a2a1a; color: #5ba35b; }
.lc { background: #2a2010; color: #c8a041; }
.ld { background: #2a1a1a; color: #d97b7b; }
.loading { display: flex; align-items: center; justify-content: center; height: 100px; color: #444; font-size: 13px; }
#info-view { display: none; }
</style>
</head>
<body>
<div class="header">
  <div class="header-left"><h1>누렁이 텔레그램 KPI</h1><p id="last-updated">로딩 중...</p></div>
  <button class="refresh-btn" onclick="loadData()">새로고침</button>
</div>
<div class="tabs">
  <button class="tab active" onclick="switchTab('aesa',this)">누렁이 AESA</button>
  <button class="tab" onclick="switchTab('info',this)">누렁이 정보방</button>
</div>
<div id="aesa-view">
  <div class="metrics-grid">
    <div class="metric"><div class="metric-label">총 뷰수</div><div class="metric-value" id="a-views">—</div><div class="metric-delta" id="a-views-d"></div></div>
    <div class="metric"><div class="metric-label">평균 반응률</div><div class="metric-value" id="a-react">—</div><div class="metric-delta" id="a-react-d"></div></div>
    <div class="metric"><div class="metric-label">주간 발송</div><div class="metric-value" id="a-sent">—</div><div class="metric-delta" id="a-sent-d"></div></div>
    <div class="metric"><div class="metric-label">9점+ 즉시알림</div><div class="metric-value" id="a-9plus">—</div><div class="metric-delta" id="a-9plus-d"></div></div>
  </div>
  <div class="charts-row">
    <div class="card"><div class="card-label">일별 뷰수</div><div style="position:relative;height:180px;"><canvas id="viewChart" role="img" aria-label="일별 뷰수"></canvas></div></div>
    <div class="card"><div class="card-label">시간대별 반응률</div><div style="position:relative;height:180px;"><canvas id="hourChart" role="img" aria-label="시간대별 반응률"></canvas></div></div>
  </div>
  <div class="charts-row">
    <div class="card"><div class="card-label">렌즈별 발송 비율</div><div style="display:flex;align-items:center;gap:20px;"><div style="position:relative;height:160px;width:160px;flex-shrink:0;"><canvas id="lensChart" role="img" aria-label="렌즈별 비율"></canvas></div><div id="lens-legend" style="font-size:12px;color:#666;line-height:2;"></div></div></div>
    <div class="card"><div class="card-label">점수 분포</div><div style="position:relative;height:160px;"><canvas id="scoreChart" role="img" aria-label="점수 분포"></canvas></div></div>
  </div>
  <div class="card"><div class="card-label">이번 주 TOP 기사</div><div id="top-articles"><div class="loading">로딩 중...</div></div></div>
</div>
<div id="info-view">
  <div class="metrics-grid">
    <div class="metric"><div class="metric-label">멤버 수</div><div class="metric-value" id="i-members">—</div><div class="metric-delta" id="i-members-d"></div></div>
    <div class="metric"><div class="metric-label">주간 발송</div><div class="metric-value" id="i-sent">—</div><div class="metric-delta" id="i-sent-d"></div></div>
    <div class="metric"><div class="metric-label">평균 반응수</div><div class="metric-value" id="i-react">—</div><div class="metric-delta" id="i-react-d"></div></div>
    <div class="metric"><div class="metric-label">반응률</div><div class="metric-value" id="i-rate">—</div><div class="metric-delta" id="i-rate-d"></div></div>
  </div>
  <div class="card" style="margin-bottom:12px;"><div class="card-label">일별 반응 추이</div><div style="position:relative;height:200px;"><canvas id="infoReactChart" role="img" aria-label="정보방 반응 추이"></canvas></div></div>
  <div class="card"><div class="card-label">시간대별 발송 효율</div><div style="position:relative;height:180px;"><canvas id="infoHourChart" role="img" aria-label="시간대별 효율"></canvas></div></div>
</div>
<script>
let ch={};
function dc(id){if(ch[id]){ch[id].destroy();delete ch[id];}}
const CC='#C87941',tc='rgba(255,255,255,0.35)',gc='rgba(255,255,255,0.06)';
const bo={responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},scales:{x:{ticks:{color:tc,font:{size:10}},grid:{color:gc}},y:{ticks:{color:tc,font:{size:10}},grid:{color:gc}}}};
function fn(n){if(n>=10000)return(n/10000).toFixed(1)+'만';if(n>=1000)return(n/1000).toFixed(1)+'k';return String(n);}
function sd(id,val,sfx=''){const el=document.getElementById(id);if(!el||val===undefined)return;el.textContent=(val>=0?'+':'')+val+sfx+' vs 전주';el.className='metric-delta '+(val>=0?'delta-up':'delta-down');}
function rA(data){
  const a=data.aesa;
  document.getElementById('a-views').textContent=fn(a.total_views||0);
  document.getElementById('a-react').textContent=(a.avg_reaction_rate||0).toFixed(1)+'%';
  document.getElementById('a-sent').textContent=a.total_sent||0;
  document.getElementById('a-9plus').textContent=a.instant_alerts||0;
  sd('a-views-d',a.views_delta_pct,'%');sd('a-react-d',a.reaction_delta_pct,'%p');sd('a-sent-d',a.sent_delta);sd('a-9plus-d',a.alerts_delta,'건');
  dc('viewChart');ch['viewChart']=new Chart(document.getElementById('viewChart'),{type:'bar',data:{labels:a.daily_views.map(d=>d.date),datasets:[{data:a.daily_views.map(d=>d.views),backgroundColor:CC,borderRadius:5}]},options:bo});
  dc('hourChart');ch['hourChart']=new Chart(document.getElementById('hourChart'),{type:'line',data:{labels:a.hourly_reactions.map(h=>h.hour+'시'),datasets:[{data:a.hourly_reactions.map(h=>parseFloat(h.rate.toFixed(2))),borderColor:'#4ade80',backgroundColor:'rgba(74,222,128,0.08)',tension:0.4,fill:true,pointBackgroundColor:'#4ade80',pointRadius:3}]},options:{...bo,scales:{...bo.scales,y:{...bo.scales.y,ticks:{...bo.scales.y.ticks,callback:v=>v+'%'}}}}});
  dc('lensChart');const lc=['#378ADD','#4ade80','#C87941','#f87171'],ll=['A AI·기술','B 지정학','C 문화','D 투자·경제'];
  ch['lensChart']=new Chart(document.getElementById('lensChart'),{type:'doughnut',data:{labels:ll,datasets:[{data:a.lens_dist,backgroundColor:lc,borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},cutout:'65%'}});
  document.getElementById('lens-legend').innerHTML=ll.map((l,i)=>`<div style="display:flex;align-items:center;gap:6px;"><span style="width:8px;height:8px;border-radius:2px;background:${lc[i]};display:inline-block;"></span><span>${l} <span style="color:#888">${a.lens_dist[i]}건</span></span></div>`).join('');
  dc('scoreChart');ch['scoreChart']=new Chart(document.getElementById('scoreChart'),{type:'bar',data:{labels:a.score_dist.map(s=>s.score+'점'),datasets:[{data:a.score_dist.map(s=>s.count),backgroundColor:a.score_dist.map(s=>s.score>=9?'#f87171':s.score>=7?CC:'#333'),borderRadius:4}]},options:bo});
  const lx={A:'la',B:'lb',C:'lc',D:'ld'},te=document.getElementById('top-articles');
  if(!a.top_articles||!a.top_articles.length){te.innerHTML='<div class="loading">데이터 없음</div>';return;}
  te.innerHTML=a.top_articles.map((art,i)=>`<div class="top-row"><div class="rank">0${i+1}</div><div class="art-info"><div class="art-title"><span class="lens-badge ${lx[art.lens]||'la'}">${art.lens}</span>${art.title}</div><div class="art-meta">${art.source} · ${art.score}점 · ${art.type}</div></div><div class="art-views">${fn(art.views)}</div></div>`).join('');
}
function rI(data){
  const inf=data.info;
  document.getElementById('i-members').textContent=(inf.members||0).toLocaleString();
  document.getElementById('i-sent').textContent=inf.total_sent||0;
  document.getElementById('i-react').textContent=inf.avg_reactions||0;
  document.getElementById('i-rate').textContent=(inf.reaction_rate||0).toFixed(1)+'%';
  sd('i-members-d',inf.members_delta,'명');sd('i-sent-d',inf.sent_delta,'건');sd('i-react-d',inf.reactions_delta);sd('i-rate-d',inf.rate_delta,'%p');
  dc('infoReactChart');ch['infoReactChart']=new Chart(document.getElementById('infoReactChart'),{type:'line',data:{labels:inf.daily_reactions.map(d=>d.date),datasets:[{data:inf.daily_reactions.map(d=>d.count),borderColor:CC,backgroundColor:'rgba(200,121,65,0.08)',tension:0.4,fill:true,pointBackgroundColor:CC,pointRadius:3}]},options:bo});
  dc('infoHourChart');ch['infoHourChart']=new Chart(document.getElementById('infoHourChart'),{type:'bar',data:{labels:inf.hourly_efficiency.map(h=>h.hour+'시'),datasets:[{data:inf.hourly_efficiency.map(h=>h.avg_reactions),backgroundColor:inf.hourly_efficiency.map(h=>h.hour===7?CC:'#2a2a2a'),borderRadius:4}]},options:bo});
}
async function loadData(){
  document.getElementById('last-updated').textContent='불러오는 중...';
  try{
    const res=await fetch('/dashboard/api/stats');
    if(!res.ok)throw new Error(res.status);
    const data=await res.json();
    rA(data);rI(data);
    const now=new Date();
    document.getElementById('last-updated').textContent=`마지막 갱신: ${now.getMonth()+1}/${now.getDate()} ${now.getHours()}:${String(now.getMinutes()).padStart(2,'0')}`;
  }catch(e){document.getElementById('last-updated').textContent='로딩 실패: '+e.message;}
}
function switchTab(c,btn){document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));btn.classList.add('active');document.getElementById('aesa-view').style.display=c==='aesa'?'block':'none';document.getElementById('info-view').style.display=c==='info'?'block':'none';}
loadData();
</script>
</body>
</html>"""

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
