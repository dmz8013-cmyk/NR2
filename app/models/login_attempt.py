from datetime import datetime, timedelta
from app import db


class LoginAttempt(db.Model):
    """로그인 시도 추적 모델"""
    __tablename__ = 'login_attempts'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=False)
    success = db.Column(db.Boolean, default=False)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    @staticmethod
    def is_locked(email, max_attempts=5, lockout_duration=1800):
        """
        계정이 잠겨있는지 확인

        Args:
            email: 확인할 이메일
            max_attempts: 최대 시도 횟수
            lockout_duration: 잠금 시간 (초)

        Returns:
            (is_locked, remaining_time): 잠금 여부와 남은 시간
        """
        cutoff_time = datetime.utcnow() - timedelta(seconds=lockout_duration)

        # 최근 시도 중 실패한 시도 수 확인
        failed_attempts = LoginAttempt.query.filter(
            LoginAttempt.email == email,
            LoginAttempt.success == False,
            LoginAttempt.attempted_at > cutoff_time
        ).order_by(LoginAttempt.attempted_at.desc()).all()

        if len(failed_attempts) >= max_attempts:
            # 가장 최근 실패 시도로부터 경과 시간 계산
            latest_attempt = failed_attempts[0]
            elapsed = (datetime.utcnow() - latest_attempt.attempted_at).total_seconds()
            remaining = max(0, lockout_duration - elapsed)

            if remaining > 0:
                return True, int(remaining)

        return False, 0

    @staticmethod
    def record_attempt(email, ip_address, success=False):
        """로그인 시도 기록"""
        attempt = LoginAttempt(
            email=email,
            ip_address=ip_address,
            success=success
        )
        db.session.add(attempt)
        db.session.commit()

        # 성공한 경우 이전 실패 기록 삭제
        if success:
            LoginAttempt.query.filter(
                LoginAttempt.email == email,
                LoginAttempt.success == False
            ).delete()
            db.session.commit()

    @staticmethod
    def get_remaining_attempts(email, max_attempts=5, lockout_duration=1800):
        """남은 시도 횟수 확인"""
        cutoff_time = datetime.utcnow() - timedelta(seconds=lockout_duration)

        failed_count = LoginAttempt.query.filter(
            LoginAttempt.email == email,
            LoginAttempt.success == False,
            LoginAttempt.attempted_at > cutoff_time
        ).count()

        return max(0, max_attempts - failed_count)

    def __repr__(self):
        return f'<LoginAttempt {self.email} at {self.attempted_at}>'
