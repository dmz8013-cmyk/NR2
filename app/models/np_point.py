"""누렁이 포인트(NP) 시스템 모델"""
from datetime import datetime, date, timedelta
from app import db


class PointHistory(db.Model):
    """포인트 적립/사용 내역"""
    __tablename__ = 'point_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)
    points = db.Column(db.Integer, nullable=False)  # 양수=적립, 음수=사용
    description = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    user = db.relationship('User', backref=db.backref('point_history', lazy='dynamic'))


# 포인트 규칙
NP_RULES = {
    'signup_bonus': 100,
    'post_write': 10,
    'comment_write': 5,
    'youcheck_vote': 5,
    'post_likes_10': 50,
    'weekly_streak': 50,
    'monthly_streak': 200,
}

# 하루 한도
DAILY_LIMITS = {
    'post_write': 5,    # 하루 최대 5회 = 50 NP
    'comment_write': 10,  # 하루 최대 10회 = 50 NP
}

# 등급 시스템
NP_GRADES = [
    {'name': '새끼 누렁이', 'icon': '\U0001f43e', 'min': 0, 'max': 499},
    {'name': '누렁이', 'icon': '\U0001f415', 'min': 500, 'max': 1999},
    {'name': '황금 누렁이', 'icon': '\U0001f981', 'min': 2000, 'max': 4999},
    {'name': '누렁이 대장', 'icon': '\U0001f451', 'min': 5000, 'max': 999999},
]


def get_grade(total_np):
    """NP 총량으로 등급 정보 반환"""
    for grade in NP_GRADES:
        if grade['min'] <= total_np <= grade['max']:
            return grade
    return NP_GRADES[0]


def get_next_grade(total_np):
    """다음 등급 정보 + 남은 NP 반환"""
    for i, grade in enumerate(NP_GRADES):
        if total_np <= grade['max']:
            if i < len(NP_GRADES) - 1:
                next_g = NP_GRADES[i + 1]
                remaining = next_g['min'] - total_np
                progress = (total_np - grade['min']) / (grade['max'] - grade['min'] + 1) * 100
                return {'next': next_g, 'remaining': remaining, 'progress': min(100, progress)}
            else:
                return {'next': None, 'remaining': 0, 'progress': 100}
    return {'next': None, 'remaining': 0, 'progress': 0}


def _daily_action_count(user_id, action_type):
    """오늘 해당 액션 횟수 조회"""
    today_start = datetime.combine(date.today(), datetime.min.time())
    return PointHistory.query.filter(
        PointHistory.user_id == user_id,
        PointHistory.action_type == action_type,
        PointHistory.created_at >= today_start,
        PointHistory.points > 0,
    ).count()


def award_np(user, action_type, description=None):
    """NP 적립 (하루 한도 체크 포함). 성공 시 적립 포인트, 실패 시 0 반환."""
    points = NP_RULES.get(action_type, 0)
    if points == 0:
        return 0

    # 하루 한도 체크
    if action_type in DAILY_LIMITS:
        count = _daily_action_count(user.id, action_type)
        if count >= DAILY_LIMITS[action_type]:
            return 0

    # 중복 체크 (1회성 보상)
    if action_type == 'signup_bonus':
        exists = PointHistory.query.filter_by(
            user_id=user.id, action_type='signup_bonus'
        ).first()
        if exists:
            return 0

    if description is None:
        desc_map = {
            'signup_bonus': '회원가입 보너스',
            'post_write': '글 작성',
            'comment_write': '댓글 작성',
            'youcheck_vote': 'YouCheck 투표',
            'post_likes_10': '내 글 추천 10개 돌파',
            'weekly_streak': '7일 연속 접속 보너스',
            'monthly_streak': '30일 연속 접속 보너스',
        }
        description = desc_map.get(action_type, action_type)

    history = PointHistory(
        user_id=user.id,
        action_type=action_type,
        points=points,
        description=description,
    )
    db.session.add(history)
    user.total_np = (user.total_np or 0) + points
    return points


def spend_np(user, points, description):
    """NP 사용. 성공 시 True, 잔액 부족 시 False."""
    if (user.total_np or 0) < points:
        return False

    history = PointHistory(
        user_id=user.id,
        action_type='spend',
        points=-points,
        description=description,
    )
    db.session.add(history)
    user.total_np -= points
    return True
