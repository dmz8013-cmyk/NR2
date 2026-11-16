"""THREADS_DRAFT_ENABLED 플래그. 실행: python3 tests/test_threads_flag.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import aesa_monitoring_bot as bot


class _Boom:
    def __init__(self, *a, **k):
        raise AssertionError("플래그가 꺼져 있는데 Anthropic 클라이언트를 만들었다")


def test_default_off_no_api_call():
    os.environ.pop("THREADS_DRAFT_ENABLED", None)
    orig = bot.anthropic.Anthropic
    bot.anthropic.Anthropic = _Boom
    try:
        assert bot.threads_draft_enabled() is False
        assert bot.generate_threads_draft("t", "s", ["A"], "u") is None
        os.environ["THREADS_DRAFT_ENABLED"] = "false"
        assert bot.generate_threads_draft("t", "s", ["A"], "u") is None
    finally:
        bot.anthropic.Anthropic = orig
        os.environ.pop("THREADS_DRAFT_ENABLED", None)


def test_on_calls_api():
    calls = []

    class _Resp:
        content = [type("B", (), {"text": " 초안 "})()]

    class _Client:
        def __init__(self, *a, **k):
            self.messages = self
        def create(self, **kw):
            calls.append(kw["model"]); return _Resp()

    os.environ["THREADS_DRAFT_ENABLED"] = "true"
    orig = bot.anthropic.Anthropic
    bot.anthropic.Anthropic = _Client
    try:
        assert bot.generate_threads_draft("t", "s", ["A"], "u") == "초안" and len(calls) == 1
    finally:
        bot.anthropic.Anthropic = orig
        os.environ.pop("THREADS_DRAFT_ENABLED", None)


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("PASS", n)
