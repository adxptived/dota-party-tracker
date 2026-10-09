"""Часовые пояса на zoneinfo: границы суток, переименованные и неизвестные имена."""
from datetime import datetime, timezone

from mmrbot import timezones
from mmrbot.formatting import fmt_local
from mmrbot.stats import local_day_start, winrate_by_hour
from mmrbot.storage import Storage
from tests.legacy_db import make_v2


def _ts(*args) -> int:
    return int(datetime(*args, tzinfo=timezone.utc).timestamp())


def test_day_start_follows_chat_zone():
    moment = _ts(2026, 10, 9, 22, 30)  # 01:30 следующих суток в Москве
    assert local_day_start(moment, "Europe/Moscow") == _ts(2026, 10, 9, 21, 0)
    assert local_day_start(moment, "UTC") == _ts(2026, 10, 9, 0, 0)


def test_day_start_on_dst_change_days():
    # Нью-Йорк, 8 марта 2026: в 02:00 часы переводятся вперёд — сутки начинаются в 05:00 UTC, следующие — в 04:00
    assert local_day_start(_ts(2026, 3, 8, 15, 0), "America/New_York") == _ts(2026, 3, 8, 5, 0)
    assert local_day_start(_ts(2026, 3, 9, 15, 0), "America/New_York") == _ts(2026, 3, 9, 4, 0)
    # 1 ноября 2026: перевод назад — сутки длятся 25 часов
    assert local_day_start(_ts(2026, 11, 1, 23, 0), "America/New_York") == _ts(2026, 11, 1, 4, 0)
    assert local_day_start(_ts(2026, 11, 2, 23, 0), "America/New_York") == _ts(2026, 11, 2, 5, 0)


def test_unknown_zone_falls_back_like_before():
    moment = _ts(2026, 10, 9, 22, 30)
    assert local_day_start(moment, "Mars/Olympus") == local_day_start(moment, "Europe/Moscow")
    assert local_day_start(moment, "") == local_day_start(moment, "Europe/Moscow")
    assert fmt_local(moment, "Mars/Olympus", "%d.%m %H:%M") == "09.10 22:30 UTC"  # даты — в UTC с пометкой
    assert fmt_local(moment, "Europe/Moscow", "%d.%m %H:%M") == "10.10 01:30"


def test_hours_are_local():
    match = {"start_time": _ts(2026, 10, 9, 22, 30), "player_slot": 0, "radiant_win": True}
    assert winrate_by_hour([match], "Europe/Moscow") == {1: (1, 1)}
    assert winrate_by_hour([match], "Asia/Yekaterinburg") == {3: (1, 1)}


def test_renamed_zone_is_understood_under_old_name():
    moment = _ts(2026, 7, 1, 22, 30)  # летом в Киеве UTC+3
    assert timezones.is_valid("Europe/Kiev")
    assert local_day_start(moment, "Europe/Kiev") == local_day_start(moment, "Europe/Kyiv") == _ts(2026, 7, 1, 21, 0)


def test_missing_zone_database_degrades_to_utc(monkeypatch):
    def nothing(name):  # так ведёт себя zoneinfo без системной базы поясов и без пакета tzdata
        raise LookupError(name)

    timezones._load.cache_clear()
    monkeypatch.setattr(timezones, "ZoneInfo", nothing)
    try:
        assert timezones.zone("Europe/Moscow") is timezone.utc
        assert not timezones.is_valid("Europe/Moscow")
    finally:
        timezones._load.cache_clear()


def test_stored_kiev_is_renamed_by_migration(tmp_path):
    path = str(tmp_path / "bot.db")
    conn = make_v2(path)
    conn.execute("INSERT INTO chats (chat_id, tz) VALUES (1, 'Europe/Kiev'), (2, 'Asia/Almaty')")
    conn.commit()
    conn.close()
    storage = Storage(path)
    assert storage.get_or_create_chat(1).tz == "Europe/Kyiv"
    assert storage.get_or_create_chat(2).tz == "Asia/Almaty"


def test_default_tz_env_accepts_old_name(monkeypatch):
    from mmrbot.config import load_config
    monkeypatch.setenv("BOT_TOKEN", "1:test")
    monkeypatch.setenv("DEFAULT_TZ", "Europe/Kiev")
    assert load_config().default_tz == "Europe/Kyiv"
    monkeypatch.setenv("DEFAULT_TZ", "Нигде/Никогда")
    assert load_config().default_tz == "Europe/Moscow"
