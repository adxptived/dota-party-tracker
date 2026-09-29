from datetime import datetime, timezone

from mmrbot.scheduler import due_local_date
from mmrbot.storage import Chat


def chat(digest_hour=10, tz="Europe/Moscow", last=None):
    return Chat(chat_id=1, digest_hour=digest_hour, mmr_step=25, tz=tz, last_digest_date=last)


def utc(y, m, d, h, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def test_due_at_digest_hour():
    # 07:00 UTC == 10:00 МСК
    assert due_local_date(chat(digest_hour=10), utc(2026, 9, 29, 7)) == "2026-09-29"


def test_not_due_before_hour():
    # 06:00 UTC == 09:00 МСК < 10
    assert due_local_date(chat(digest_hour=10), utc(2026, 9, 29, 6)) is None


def test_catch_up_after_hour_same_day():
    # 08:00 UTC == 11:00 МСК, дайджест ещё не слали → догоняем
    assert due_local_date(chat(digest_hour=10), utc(2026, 9, 29, 8)) == "2026-09-29"


def test_not_due_if_already_sent_today():
    c = chat(digest_hour=10, last="2026-09-29")
    assert due_local_date(c, utc(2026, 9, 29, 7)) is None


def test_due_next_day_after_previous_send():
    c = chat(digest_hour=10, last="2026-09-28")
    assert due_local_date(c, utc(2026, 9, 29, 7)) == "2026-09-29"


def test_respects_chat_timezone():
    # Asia/Yekaterinburg = UTC+5; 05:00 UTC == 10:00 YEKT
    c = chat(digest_hour=10, tz="Asia/Yekaterinburg")
    assert due_local_date(c, utc(2026, 9, 29, 5)) == "2026-09-29"


def test_bad_timezone_falls_back_to_moscow():
    c = chat(digest_hour=10, tz="Not/AZone")
    assert due_local_date(c, utc(2026, 9, 29, 7)) == "2026-09-29"
