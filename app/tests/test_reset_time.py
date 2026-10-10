"""Reset times read from limit messages, for "Continue with the same model later"."""

import time

from backend import usage

NOW = time.mktime((2026, 10, 9, 20, 0, 0, 0, 0, -1))


def _hm(t):
    return time.strftime("%d %H:%M", time.localtime(t))


def test_codex_try_again_at_pm_is_today():
    assert _hm(usage.reset_from_text("try again at 10:21 PM.", NOW)) == "09 22:21"


def test_a_time_already_past_is_tomorrow():
    assert _hm(usage.reset_from_text("resets at 9am", NOW)) == "10 09:00"


def test_epoch_after_bar():
    assert usage.reset_from_text("Claude AI usage limit reached|1791580000", NOW) == 1791580000.0


def test_bare_number_is_not_a_time():
    assert usage.reset_from_text("retry at 5", NOW) is None
