import os
from app import create_app, db
from app.models import User, Post, PostImage, Comment, Like, Vote, VoteOption, VoteResponse, Event

# Create Flask app
app = create_app(os.getenv('FLASK_ENV', 'development'))


@app.shell_context_processor
def make_shell_context():
    """Flask shell에서 사용할 컨텍스트 설정"""
    return {
        'db': db,
        'User': User,
        'Post': Post,
        'PostImage': PostImage,
        'Comment': Comment,
        'Like': Like,
        'Vote': Vote,
        'VoteOption': VoteOption,
        'VoteResponse': VoteResponse,
        'Event': Event,
    }


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
