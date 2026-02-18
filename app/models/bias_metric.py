from app import db
from datetime import datetime


class BiasMetric(db.Model):
    __tablename__ = 'bias_metrics'
    
    id = db.Column(db.Integer, primary_key=True)
    keyword = db.Column(db.String(100), nullable=False, index=True)
    left_count = db.Column(db.Integer, default=0)
    right_count = db.Column(db.Integer, default=0)
    bias_ratio = db.Column(db.Float, default=0.0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    def __repr__(self):
        return f'<BiasMetric {self.keyword}: L{self.left_count} R{self.right_count}>'
    
    def calculate_bias_ratio(self):
        total = self.left_count + self.right_count
        if total == 0:
            return 0.0
        return (self.right_count - self.left_count) / total
    
    def get_bias_percentage(self):
        total = self.left_count + self.right_count
        if total == 0:
            return {'left': 0, 'right': 0}
        return {
            'left': round((self.left_count / total) * 100, 1),
            'right': round((self.right_count / total) * 100, 1)
        }
    
    def is_blind_spot(self, threshold=80):
        percentages = self.get_bias_percentage()
        return percentages['left'] >= threshold or percentages['right'] >= threshold
