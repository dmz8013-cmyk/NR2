import logging
from flask import flash
from app import db
from app.models.badge import Badge, UserBadge

logger = logging.getLogger(__name__)

def check_and_award_badges(user):
    """
    유저의 각종 통계를 바탕으로 뱃지 발급 조건을 확인하고,
    조건에 해당하며 아직 받지 않은 뱃지가 있다면 발급합니다.
    """
    if not user:
        return []

    new_badges = []

    # 1. 출석 뱃지
    if user.login_streak >= 7: new_badges.append(award_badge(user, 'ATTEND_7'))
    if user.login_streak >= 30: new_badges.append(award_badge(user, 'ATTEND_30'))
    if user.login_streak >= 100: new_badges.append(award_badge(user, 'ATTEND_100'))

    # 2. 글 쓰기 뱃지
    post_count = user.posts.count()
    if post_count >= 10: new_badges.append(award_badge(user, 'POST_10'))
    if post_count >= 50: new_badges.append(award_badge(user, 'POST_50'))
    if post_count >= 100: new_badges.append(award_badge(user, 'POST_100'))

    # 3. 댓글 쓰기 뱃지
    comment_count = user.comments.count()
    if comment_count >= 50: new_badges.append(award_badge(user, 'COMMENT_50'))
    if comment_count >= 200: new_badges.append(award_badge(user, 'COMMENT_200'))

    # 4. NP 뱃지
    np = user.total_np or 0
    if np >= 1000: new_badges.append(award_badge(user, 'NP_1000'))
    if np >= 5000: new_badges.append(award_badge(user, 'NP_5000'))
    if np >= 10000: new_badges.append(award_badge(user, 'NP_10000'))

    # 5. 직군 인증 뱃지 (job_category 필드가 존재하고, 값이 있는 경우)
    if getattr(user, 'job_category', None):
        if user.job_category == 'ai': new_badges.append(award_badge(user, 'JOB_AI'))
        elif user.job_category == '개발자': new_badges.append(award_badge(user, 'JOB_DEV'))
        elif user.job_category == '마케터': new_badges.append(award_badge(user, 'JOB_MARKETER'))
        # job_category 값 매핑에 따라 다를 수 있으나, 현재 알려진 정보를 기반으로 작성.

    # Remove None values
    awarded = [b for b in new_badges if b is not None]
    
    if awarded:
        try:
            db.session.commit()
            for b in awarded:
                flash(f"'{b.icon} {b.name}' 뱃지를 새롭게 획득했습니다!", 'success')
                logger.info(f"유저 {user.nickname}님이 {b.code} 뱃지 획득")
        except Exception as e:
            db.session.rollback()
            logger.error(f"뱃지 발급 중 오류 발생: {e}")
            return []

    return awarded

def award_badge(user, badge_code):
    """
    특정 뱃지 코드를 유저에게 발급. 이미 있으면 반환하지 않음.
    첫 뱃지라면 자동 대표 뱃지로 장착.
    """
    badge = Badge.query.filter_by(code=badge_code).first()
    if not badge:
        return None

    existing = UserBadge.query.filter_by(user_id=user.id, badge_id=badge.id).first()
    if not existing:
        ub = UserBadge(user_id=user.id, badge_id=badge.id)
        # 만약 이 유저의 첫 뱃지라면 자동으로 대표 뱃지(닉네임 옆 표시)로 지정
        if user.user_badges.count() == 0:
            ub.is_primary = True
            
        db.session.add(ub)
        return badge
        
    return None
