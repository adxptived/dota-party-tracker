"""Нумерованные миграции схемы SQLite.

Версия базы хранится в `PRAGMA user_version`. Каждая миграция — функция `(conn) -> None` под своим
номером в MIGRATIONS; `migrate()` выполняет по порядку те, чей номер больше версии базы. Одна миграция —
одна транзакция вместе со сменой `user_version`: сбой посередине откатывает её целиком, и база остаётся
на прежней версии.

Правила:
- выпущенную миграцию не редактируем — новое изменение схемы идёт следующим номером;
- миграция пишет сама только через `conn.execute` (без `executescript`: тот завершает транзакцию);
- перед миграцией существующей базы делается копия `backups/pre-migration-v<N>-<имя>.db`.

Миграции 1–2 — исторические: до нумерации бот на каждом старте досоздавал таблицы и недостающие колонки
и ставил версию 2, не меняя её при добавлении колонок. Поэтому для баз с версией 0–2 обе выполняются
всегда (они идемпотентны), а строгий порядок начинается с 3.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger(__name__)

LEGACY_VERSION = 2  # до этой версии включительно схема «догонялась» идемпотентно на каждом старте


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def add_missing(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = set(table_columns(conn, table))
    for name, decl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def rebuild_table(conn: sqlite3.Connection, table: str, ddl_body: str, columns: list[str]) -> None:
    """Пересоздать таблицу с новым определением, перенеся перечисленные колонки (так SQLite убирает колонки и ключи).

    Индексы и триггеры таблицы пропадают вместе со старой — их миграция создаёт заново. Триггеры ДРУГИХ таблиц,
    которые на неё ссылаются, вызывающий снимает заранее: иначе переименование споткнётся об их тела.
    Счётчик AUTOINCREMENT сохраняется — id удалённых строк не выдаются повторно.
    """
    listed = ", ".join(columns)
    has_seq = conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone() is not None
    seq = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone() if has_seq else None
    conn.execute(f"CREATE TABLE {table}__new ({ddl_body})")
    conn.execute(f"INSERT INTO {table}__new ({listed}) SELECT {listed} FROM {table}")
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}__new RENAME TO {table}")
    if seq is not None:
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN (?, ?)", (table, f"{table}__new"))
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (table, seq[0]))


def drop_triggers(conn: sqlite3.Connection, *names: str) -> None:
    for name in names:
        conn.execute(f"DROP TRIGGER IF EXISTS {name}")


# --- 1: исходные таблицы -------------------------------------------------------------------------------

def _m001_base_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chats (
            chat_id          INTEGER PRIMARY KEY,
            digest_hour      INTEGER NOT NULL DEFAULT 10,
            mmr_step         INTEGER NOT NULL DEFAULT 25,
            tz               TEXT    NOT NULL DEFAULT 'Europe/Moscow'
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS contest_leaders (
            chat_id INTEGER NOT NULL,
            period  TEXT    NOT NULL,
            key     TEXT    NOT NULL,
            leader  TEXT    NOT NULL,
            PRIMARY KEY (chat_id, period, key)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS players (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id               INTEGER NOT NULL,
            account_id            INTEGER NOT NULL,
            display_name          TEXT    NOT NULL,
            anchor_mmr            INTEGER,
            anchor_ts             INTEGER NOT NULL,
            created_ts            INTEGER NOT NULL,
            last_rank_tier        INTEGER,
            last_leaderboard_rank INTEGER,
            updated_ts            INTEGER,
            UNIQUE(chat_id, account_id)
        )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS matches (
            player_id   INTEGER NOT NULL,
            match_id    INTEGER NOT NULL,
            start_time  INTEGER NOT NULL,
            player_slot INTEGER NOT NULL,
            radiant_win INTEGER NOT NULL,
            lobby_type  INTEGER,
            kills       INTEGER NOT NULL DEFAULT 0,
            deaths      INTEGER NOT NULL DEFAULT 0,
            assists     INTEGER NOT NULL DEFAULT 0,
            hero_id     INTEGER,
            PRIMARY KEY (player_id, match_id)
        )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_matches_player_time ON matches (player_id, start_time)")


# --- 2: всё, что до нумерации добавлялось «если колонки нет» ---------------------------------------------

def _m002_legacy_columns(conn: sqlite3.Connection) -> None:
    add_missing(conn, "chats", {
        "last_digest_date": "TEXT", "notify_steam": "INTEGER NOT NULL DEFAULT 1",
        "notify_games": "INTEGER NOT NULL DEFAULT 1", "notify_weekly": "INTEGER NOT NULL DEFAULT 1",
        "last_weekly": "TEXT", "notify_start": "INTEGER NOT NULL DEFAULT 1",
        "tag_mmr": "INTEGER NOT NULL DEFAULT 0",
        "notify_digest": "INTEGER NOT NULL DEFAULT 1",
        "admin_only": "INTEGER NOT NULL DEFAULT 1",
        "active": "INTEGER NOT NULL DEFAULT 1",
        "prefer_text": "INTEGER NOT NULL DEFAULT 0",
    })
    # Старая история — уже «оповещённая»: иначе после обновления бот завалил бы чат старыми играми.
    if "notified" not in table_columns(conn, "matches"):
        conn.execute("ALTER TABLE matches ADD COLUMN notified INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE matches SET notified = 1")
    add_missing(conn, "players", {
        "last_gpm": "REAL", "last_xpm": "REAL", "last_last_hits": "REAL",
        "last_lanes": "TEXT", "last_gpm_median": "REAL", "last_gpm_best": "REAL",
        "steam_name": "TEXT", "steam_avatar": "TEXT",
        "profile_ts": "INTEGER", "history_ts": "INTEGER",
        "insights_dirty": "INTEGER NOT NULL DEFAULT 0",
        "fh_unavailable": "INTEGER NOT NULL DEFAULT 0",
        "ingame_since": "INTEGER", "ingame_misses": "INTEGER NOT NULL DEFAULT 0",
        "tg_user_id": "INTEGER", "last_tag": "TEXT",
        "data_ver": "INTEGER NOT NULL DEFAULT 0",
    })
    add_missing(conn, "matches", {
        "duration": "INTEGER", "party_size": "INTEGER", "average_rank": "INTEGER",
        "gpm": "REAL", "xpm": "REAL", "last_hits": "INTEGER", "denies": "INTEGER",
        "hero_damage": "INTEGER", "tower_damage": "INTEGER", "hero_healing": "INTEGER",
        "net_worth": "INTEGER", "level": "INTEGER", "perf_score": "REAL",
        "bench_json": "TEXT", "enriched": "INTEGER NOT NULL DEFAULT 0",
        "position": "INTEGER", "role": "TEXT", "lane": "TEXT", "imp": "INTEGER",
        "stratz_done": "INTEGER NOT NULL DEFAULT 0",
        "stratz_tries": "INTEGER NOT NULL DEFAULT 0",
        "enrich_tries": "INTEGER NOT NULL DEFAULT 0",
        "stratz_next_ts": "INTEGER NOT NULL DEFAULT 0",
        "leaver_status": "INTEGER",
    })
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_matches_unnotified ON matches(player_id, start_time) WHERE notified = 0"
    )
    _v2_data_ver_triggers(conn)


def _v2_data_ver_triggers(conn: sqlite3.Connection) -> None:
    """«Версия данных» игрока: любое изменение его матчей (кроме служебных счётчиков) двигает players.data_ver."""
    bump = "UPDATE players SET data_ver = data_ver + 1 WHERE id = {}.player_id"
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS matches_bump_ins AFTER INSERT ON matches BEGIN {bump.format('NEW')}; END")
    conn.execute(f"CREATE TRIGGER IF NOT EXISTS matches_bump_del AFTER DELETE ON matches BEGIN {bump.format('OLD')}; END")
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS matches_bump_upd AFTER UPDATE ON matches "
        "WHEN OLD.notified IS NEW.notified AND OLD.enrich_tries IS NEW.enrich_tries "
        "AND OLD.stratz_tries IS NEW.stratz_tries AND OLD.stratz_next_ts IS NEW.stratz_next_ts "
        f"BEGIN {bump.format('NEW')}; END"
    )


# --- 3: мёртвые колонки игрока ----------------------------------------------------------------------------

_PLAYERS_V3 = """
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id               INTEGER NOT NULL,
    account_id            INTEGER NOT NULL,
    display_name          TEXT    NOT NULL,
    anchor_mmr            INTEGER,
    anchor_ts             INTEGER NOT NULL,
    created_ts            INTEGER NOT NULL,
    last_rank_tier        INTEGER,
    last_leaderboard_rank INTEGER,
    updated_ts            INTEGER,
    steam_name            TEXT,
    steam_avatar          TEXT,
    profile_ts            INTEGER,
    history_ts            INTEGER,
    fh_unavailable        INTEGER NOT NULL DEFAULT 0,
    ingame_since          INTEGER,
    ingame_misses         INTEGER NOT NULL DEFAULT 0,
    tg_user_id            INTEGER,
    last_tag              TEXT,
    data_ver              INTEGER NOT NULL DEFAULT 0,
    UNIQUE(chat_id, account_id)
"""


def _m003_drop_dead_player_columns(conn: sqlite3.Connection) -> None:
    """Карьерные средние (last_gpm … last_gpm_best) и insights_dirty бот давно не запрашивает и не показывает."""
    keep = [
        "id", "chat_id", "account_id", "display_name", "anchor_mmr", "anchor_ts", "created_ts",
        "last_rank_tier", "last_leaderboard_rank", "updated_ts", "steam_name", "steam_avatar",
        "profile_ts", "history_ts", "fh_unavailable", "ingame_since", "ingame_misses",
        "tg_user_id", "last_tag", "data_ver",
    ]
    drop_triggers(conn, "matches_bump_ins", "matches_bump_del", "matches_bump_upd")
    rebuild_table(conn, "players", _PLAYERS_V3, keep)
    _v2_data_ver_triggers(conn)


MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, _m001_base_tables),
    (2, _m002_legacy_columns),
    (3, _m003_drop_dead_player_columns),
]

LATEST_VERSION = MIGRATIONS[-1][0]


def _has_tables(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'chats'").fetchone() is not None


def _backup_before(db_path: str, version: int) -> Optional[Path]:
    """Копия базы перед миграцией: откат версии бота без неё невозможен (старый код новую схему не откроет)."""
    source = Path(db_path)
    if not source.is_file():
        return None
    folder = source.parent / "backups"
    target = folder / f"pre-migration-v{version}-{source.stem}.db"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(str(source))
        try:
            dst = sqlite3.connect(str(target))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
    except (OSError, sqlite3.Error):
        log.warning("Не удалось сделать копию базы перед миграцией (%s) — продолжаю без неё", target, exc_info=True)
        return None
    log.info("Копия базы перед миграцией: %s", target)
    return target


def migrate(db_path: str, migrations: Optional[list] = None, backup: bool = True) -> int:
    """Довести базу до последней версии; вернуть её версию. База новее кода — RuntimeError."""
    migrations = MIGRATIONS if migrations is None else migrations
    latest = migrations[-1][0]
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)  # транзакциями управляем сами
    try:
        conn.execute("PRAGMA journal_mode = WAL")  # режим хранится в файле БД — достаточно один раз
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > latest:
            raise RuntimeError(
                f"База {db_path} создана более новой версией бота (схема {version}, эта версия знает "
                f"{latest}). Обновите бота или восстановите базу из бэкапа."
            )
        legacy = version <= LEGACY_VERSION
        if version == latest:
            return version
        if backup and _has_tables(conn):
            _backup_before(db_path, version)
        for number, step in migrations:
            if number <= version and not (legacy and number <= LEGACY_VERSION):
                continue
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Версию перечитываем под блокировкой: второй процесс мог выполнить миграцию, пока мы ждали.
                current = conn.execute("PRAGMA user_version").fetchone()[0]
                if number > current or (legacy and number <= LEGACY_VERSION and current <= LEGACY_VERSION):
                    step(conn)
                    if number > current:
                        conn.execute(f"PRAGMA user_version = {number}")
                        log.info("Схема базы обновлена до версии %s (%s)", number, step.__name__)
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()
