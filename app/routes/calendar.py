from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from app import db
from app.models import Event

bp = Blueprint('calendar', __name__, url_prefix='/calendar')


@bp.route('/')
@login_required
def index():
    """캘린더 메인 페이지"""
    return render_template('calendar/index.html')


@bp.route('/api/events')
@login_required
def get_events():
    """일정 목록 조회 (JSON API)"""
    # FullCalendar의 start/end 파라미터
    start = request.args.get('start')
    end = request.args.get('end')

    # 쿼리 기본
    query = Event.query.filter_by(user_id=current_user.id)

    # 날짜 필터링
    if start:
        start_date = datetime.fromisoformat(start.replace('Z', '+00:00'))
        query = query.filter(Event.start_date >= start_date)
    if end:
        end_date = datetime.fromisoformat(end.replace('Z', '+00:00'))
        query = query.filter(Event.start_date <= end_date)

    events = query.all()

    # FullCalendar 형식으로 변환
    events_data = []
    for event in events:
        event_dict = {
            'id': event.id,
            'title': event.title,
            'start': event.start_date.isoformat(),
            'allDay': event.all_day,
            'color': event.color,
            'description': event.description
        }
        if event.end_date:
            event_dict['end'] = event.end_date.isoformat()

        events_data.append(event_dict)

    return jsonify(events_data)


@bp.route('/api/events', methods=['POST'])
@login_required
def create_event():
    """일정 생성 (JSON API)"""
    data = request.get_json()

    title = data.get('title', '').strip()
    description = data.get('description', '').strip()
    start_date_str = data.get('start')
    end_date_str = data.get('end')
    all_day = data.get('allDay', False)
    color = data.get('color', '#3B82F6')

    # 유효성 검사
    if not title:
        return jsonify({'error': '제목을 입력해주세요.'}), 400

    if not start_date_str:
        return jsonify({'error': '시작일을 입력해주세요.'}), 400

    try:
        start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))
        end_date = None
        if end_date_str:
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
    except ValueError:
        return jsonify({'error': '올바른 날짜 형식이 아닙니다.'}), 400

    # 일정 생성
    event = Event(
        title=title,
        description=description,
        start_date=start_date,
        end_date=end_date,
        all_day=all_day,
        color=color,
        user_id=current_user.id
    )
    db.session.add(event)
    db.session.commit()

    return jsonify({
        'id': event.id,
        'title': event.title,
        'start': event.start_date.isoformat(),
        'end': event.end_date.isoformat() if event.end_date else None,
        'allDay': event.all_day,
        'color': event.color
    }), 201


@bp.route('/api/events/<int:event_id>', methods=['PUT'])
@login_required
def update_event(event_id):
    """일정 수정 (JSON API)"""
    event = Event.query.get_or_404(event_id)

    # 권한 확인
    if event.user_id != current_user.id:
        return jsonify({'error': '수정 권한이 없습니다.'}), 403

    data = request.get_json()

    # 업데이트
    if 'title' in data:
        event.title = data['title'].strip()
    if 'description' in data:
        event.description = data['description'].strip()
    if 'start' in data:
        event.start_date = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
    if 'end' in data:
        if data['end']:
            event.end_date = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))
        else:
            event.end_date = None
    if 'allDay' in data:
        event.all_day = data['allDay']
    if 'color' in data:
        event.color = data['color']

    db.session.commit()

    return jsonify({
        'id': event.id,
        'title': event.title,
        'start': event.start_date.isoformat(),
        'end': event.end_date.isoformat() if event.end_date else None,
        'allDay': event.all_day,
        'color': event.color
    })


@bp.route('/api/events/<int:event_id>', methods=['DELETE'])
@login_required
def delete_event(event_id):
    """일정 삭제 (JSON API)"""
    event = Event.query.get_or_404(event_id)

    # 권한 확인
    if event.user_id != current_user.id:
        return jsonify({'error': '삭제 권한이 없습니다.'}), 403

    db.session.delete(event)
    db.session.commit()

    return jsonify({'message': '일정이 삭제되었습니다.'}), 200
