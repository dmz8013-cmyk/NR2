"""AI 브리핑 아카이브 모델"""
from datetime import datetime
from app import db


class Briefing(db.Model):
    __tablename__ = 'briefings'

    id = db.Column(db.Integer, primary_key=True)
    briefing_type = db.Column(db.String(20), nullable=False)  # 'ai_morning', 'ai_evening', 'political_afternoon', 'political_evening'
    title = db.Column(db.String(200), nullable=True)
    content = db.Column(db.Text, nullable=False)
    article_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)

    @property
    def type_label(self):
        labels = {
            'ai_morning': '🌅 아침 AI 브리핑',
            'ai_evening': '🌆 저녁 AI 브리핑',
            'political_afternoon': '🏛️ 오후 정치 브리핑',
            'political_evening': '🌙 저녁 정치 브리핑',
        }
        return labels.get(self.briefing_type, self.briefing_type)

    @property
    def type_badge_color(self):
        colors = {
            'ai_morning': '#F59E0B',
            'ai_evening': '#8B5CF6',
            'political_afternoon': '#3B82F6',
            'political_evening': '#EF4444',
        }
        return colors.get(self.briefing_type, '#6B7280')

    def __repr__(self):
        return f'<Briefing {self.briefing_type} {self.created_at}>'
