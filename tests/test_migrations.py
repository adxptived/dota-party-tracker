"""Нумерованные миграции: порядок, транзакционность, перенос данных со старых баз."""
import sqlite3

import pytest

from mmrbot import migrations
from mmrbot.migrations import LATEST_VERSION, migrate
from mmrbot.storage import SCHEMA_VERSION, Storage
from tests.legacy_db import add_match, add_player, make_v0, make_v2


def _version(path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _columns(path, table) -> set:
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def test_numbers_are_consecutive_and_storage_reports_latest():
    numbers = [number for number, _ in migrations.MIGRATIONS]
    assert numbers == list(range(1, len(numbers) + 1))
    assert SCHEMA_VERSION == LATEST_VERSION == numbers[-1]


def test_fresh_database_runs_every_migration(tmp_path):
    path = str(tmp_path / "new.db")
    Storage(path)
    assert _version(path) == LATEST_VERSION
    assert not (tmp_path / "backups").exists()  # копировать перед миграцией нечего


def test_reopening_up_to_date_database_changes_nothing(tmp_path, monkeypatch):
    path = str(tmp_path / "same.db")
    Storage(path)
    called = []
    monkeypatch.setattr(migrations, "MIGRATIONS", [(n, lambda conn, n=n: called.append(n)) for n, _ in migrations.MIGRATIONS])
    Storage(path)
    assert called == []


def test_only_pending_migrations_run(tmp_path):
    path = str(tmp_path / "steps.db")
    ran = []
    steps = [(1, lambda c: ran.append(1)), (2, lambda c: ran.append(2)), (3, lambda c: ran.append(3))]
    assert migrate(path, steps) == 3
    steps.append((4, lambda c: ran.append(4)))
    assert migrate(path, steps) == 4
    assert ran == [1, 2, 3, 4]


def test_failed_migration_rolls_back_and_keeps_version(tmp_path):
    path = str(tmp_path / "fail.db")

    def good(conn):
        conn.execute("CREATE TABLE chats (chat_id INTEGER PRIMARY KEY)")

    def broken(conn):
        conn.execute("CREATE TABLE half_done (x INTEGER)")
        conn.execute("INSERT INTO chats (chat_id) VALUES (1)")
        raise RuntimeError("сбой посреди миграции")

    with pytest.raises(RuntimeError):
        migrate(path, [(1, good), (2, lambda c: None), (3, lambda c: None), (4, broken)])
    assert _version(path) == 3
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM chats").fetchone()[0] == 0
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'half_done'").fetchone() is None
    conn.close()


def test_legacy_database_is_caught_up_even_when_already_stamped(tmp_path):
    """До нумерации версия 2 ставилась, а колонки добавлялись без её смены — базу с версией ≤ 2 догоняем целиком."""
    path = str(tmp_path / "old.db")
    conn = make_v0(path)
    add_player(conn, 100, 1, "Вася")
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()
    storage = Storage(path)
    assert storage.get_or_create_chat(100).prefer_text is False
    assert storage.get_player(100, "Вася").account_id == 1


def test_backup_is_made_before_migrating_existing_database(tmp_path):
    path = str(tmp_path / "bot.db")
    conn = make_v2(path)
    add_player(conn, 100, 1, "Вася", 5000)
    conn.commit()
    conn.close()
    Storage(path)
    copy = tmp_path / "backups" / "pre-migration-v2-bot.db"
    assert copy.exists()
    assert _version(str(copy)) == 2  # копия — база до миграции
    assert "last_gpm" in _columns(str(copy), "players")


def test_v2_database_loses_dead_columns_and_keeps_data(tmp_path):
    path = str(tmp_path / "bot.db")
    conn = make_v2(path)
    first = add_player(conn, 100, 1, "Вася", 5000, 10, 5, last_gpm=512.5, steam_name="vasya", tg_user_id=77)
    removed = add_player(conn, 100, 2, "Петя")
    conn.execute("DELETE FROM players WHERE id = ?", (removed,))
    add_match(conn, first, 11, 1000, kills=7, notified=1)
    conn.commit()
    conn.close()

    storage = Storage(path)
    assert not {"last_gpm", "last_xpm", "last_last_hits", "last_lanes", "last_gpm_median", "last_gpm_best",
                "insights_dirty"} & _columns(path, "players")
    player = storage.get_player(100, "Вася")
    assert (player.id, player.anchor_mmr, player.anchor_ts, player.created_ts) == (first, 5000, 10, 5)
    assert (player.steam_name, player.tg_user_id) == ("vasya", 77)
    assert [m["kills"] for m in storage.get_matches(player.id)] == [7]
    # id удалённого игрока не выдаётся заново: счётчик AUTOINCREMENT пережил пересборку таблицы
    assert storage.add_player(100, 3, "Коля", None, 0, 0).id > removed


def test_lanes_and_wards_columns_added_and_recent_stratz_matches_requeued(tmp_path):
    import time

    path = str(tmp_path / "bot.db")
    conn = make_v2(path)
    player = add_player(conn, 100, 1, "Вася", 5000, 10, 5)
    now = int(time.time())
    add_match(conn, player, 1, now - 5 * 86400, stratz_done=1, stratz_tries=3, stratz_next_ts=999, position=5)  # свежий
    add_match(conn, player, 2, now - 200 * 86400, stratz_done=1, position=1)                                    # старый
    add_match(conn, player, 3, now - 2 * 86400, stratz_done=0, stratz_tries=2)                                  # и так в очереди
    conn.commit()
    conn.close()

    storage = Storage(path)
    assert {"lane_result", "wards", "stacks"} <= _columns(path, "matches")
    rows = {m["match_id"]: m for m in storage.get_matches(player)}
    assert (rows[1]["stratz_done"], rows[1]["stratz_tries"], rows[1]["stratz_next_ts"]) == (0, 0, 0)
    assert rows[1]["position"] == 5 and rows[1]["lane_result"] is None  # данные не потеряны, ждут повторной выгрузки
    assert rows[2]["stratz_done"] == 1                                    # старые не трогаем
    assert rows[3]["stratz_tries"] == 2


def test_newer_database_is_refused_with_clear_message(tmp_path):
    path = str(tmp_path / "future.db")
    Storage(path)
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {LATEST_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="более новой версией"):
        Storage(path)
