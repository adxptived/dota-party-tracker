"""Базы старых версий схемы — для тестов миграций.

V2_STATEMENTS — точный слепок схемы последней версии до нумерованных миграций (user_version = 2):
его создавал прежний код (`_SCHEMA` + досоздание колонок). Миграции проверяются на нём, а не на
«новой базе с удалённой колонкой»: так тест повторяет то, что произойдёт с боевой базой.
"""
import sqlite3

V2_STATEMENTS = [
    """CREATE TABLE chats (
    chat_id          INTEGER PRIMARY KEY,
    digest_hour      INTEGER NOT NULL DEFAULT 10,
    mmr_step         INTEGER NOT NULL DEFAULT 25,
    tz               TEXT    NOT NULL DEFAULT 'Europe/Moscow',
    last_digest_date TEXT,
    notify_steam     INTEGER NOT NULL DEFAULT 1,
    notify_games     INTEGER NOT NULL DEFAULT 1,
    notify_weekly    INTEGER NOT NULL DEFAULT 1,
    last_weekly      TEXT,
    notify_start     INTEGER NOT NULL DEFAULT 1,
    tag_mmr          INTEGER NOT NULL DEFAULT 0,
    notify_digest    INTEGER NOT NULL DEFAULT 1,
    admin_only       INTEGER NOT NULL DEFAULT 1,
    active           INTEGER NOT NULL DEFAULT 1,
    prefer_text      INTEGER NOT NULL DEFAULT 0
)""",
    """CREATE TABLE contest_leaders (
    chat_id INTEGER NOT NULL,
    period  TEXT    NOT NULL,
    key     TEXT    NOT NULL,
    leader  TEXT    NOT NULL,
    PRIMARY KEY (chat_id, period, key)
)""",
    """CREATE TABLE players (
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
    last_gpm              REAL,
    last_xpm              REAL,
    last_last_hits        REAL,
    last_lanes            TEXT,
    last_gpm_median       REAL,
    last_gpm_best         REAL,
    steam_name            TEXT,
    steam_avatar          TEXT,
    profile_ts            INTEGER,
    history_ts            INTEGER,
    insights_dirty        INTEGER NOT NULL DEFAULT 0,
    fh_unavailable        INTEGER NOT NULL DEFAULT 0,
    ingame_since          INTEGER,
    ingame_misses         INTEGER NOT NULL DEFAULT 0,
    tg_user_id            INTEGER,
    last_tag              TEXT, data_ver INTEGER NOT NULL DEFAULT 0,
    UNIQUE(chat_id, account_id)
)""",
    """CREATE TABLE matches (
    player_id   INTEGER NOT NULL,
    match_id    INTEGER NOT NULL,
    start_time  INTEGER NOT NULL,
    player_slot INTEGER NOT NULL,
    radiant_win INTEGER NOT NULL,
    lobby_type  INTEGER,
    kills       INTEGER NOT NULL DEFAULT 0,
    deaths      INTEGER NOT NULL DEFAULT 0,
    assists     INTEGER NOT NULL DEFAULT 0,
    hero_id      INTEGER,
    duration     INTEGER,
    party_size   INTEGER,
    average_rank INTEGER,
    gpm          REAL,
    xpm          REAL,
    last_hits    INTEGER,
    denies       INTEGER,
    hero_damage  INTEGER,
    tower_damage INTEGER,
    hero_healing INTEGER,
    net_worth    INTEGER,
    level        INTEGER,
    perf_score   REAL,
    bench_json   TEXT,
    enriched     INTEGER NOT NULL DEFAULT 0,
    position     INTEGER,
    role         TEXT,
    lane         TEXT,
    imp          INTEGER,
    stratz_done  INTEGER NOT NULL DEFAULT 0,
    stratz_tries INTEGER NOT NULL DEFAULT 0,
    enrich_tries INTEGER NOT NULL DEFAULT 0,
    stratz_next_ts INTEGER NOT NULL DEFAULT 0,
    notified     INTEGER NOT NULL DEFAULT 0,
    leaver_status INTEGER,
    PRIMARY KEY (player_id, match_id)
)""",
    """CREATE INDEX idx_matches_player_time ON matches (player_id, start_time)""",
    """CREATE INDEX idx_matches_unnotified ON matches(player_id, start_time) WHERE notified = 0""",
    """CREATE TRIGGER matches_bump_ins AFTER INSERT ON matches BEGIN UPDATE players SET data_ver = data_ver + 1 WHERE id = NEW.player_id; END""",
    """CREATE TRIGGER matches_bump_del AFTER DELETE ON matches BEGIN UPDATE players SET data_ver = data_ver + 1 WHERE id = OLD.player_id; END""",
    """CREATE TRIGGER matches_bump_upd AFTER UPDATE ON matches WHEN OLD.notified IS NEW.notified AND OLD.enrich_tries IS NEW.enrich_tries AND OLD.stratz_tries IS NEW.stratz_tries AND OLD.stratz_next_ts IS NEW.stratz_next_ts BEGIN UPDATE players SET data_ver = data_ver + 1 WHERE id = NEW.player_id; END""",
]


def make_v2(path: str, stamp: int = 2) -> sqlite3.Connection:
    """Создать пустую базу версии 2 и вернуть открытое соединение (вызывающий наполняет и закрывает)."""
    conn = sqlite3.connect(path)
    for statement in V2_STATEMENTS:
        conn.execute(statement)
    conn.execute(f"PRAGMA user_version = {stamp}")
    conn.commit()
    return conn


def add_player(conn, chat_id, account_id, name, anchor_mmr=None, anchor_ts=0, created_ts=0, **extra) -> int:
    conn.execute("INSERT OR IGNORE INTO chats (chat_id) VALUES (?)", (chat_id,))
    columns = ["chat_id", "account_id", "display_name", "anchor_mmr", "anchor_ts", "created_ts", *extra]
    values = [chat_id, account_id, name, anchor_mmr, anchor_ts, created_ts, *extra.values()]
    cur = conn.execute(
        f"INSERT INTO players ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})", values)
    return cur.lastrowid


def add_match(conn, player_id, match_id, start_time, win=True, **extra) -> None:
    columns = ["player_id", "match_id", "start_time", "player_slot", "radiant_win", "lobby_type", *extra]
    values = [player_id, match_id, start_time, 0, 1 if win else 0, 7, *extra.values()]
    conn.execute(f"INSERT INTO matches ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})", values)


def make_v0(path: str) -> sqlite3.Connection:
    """Самая старая база: только исходные таблицы, версия не проставлена (до колонок notified, data_ver и прочих)."""
    from mmrbot.migrations import _m001_base_tables
    conn = sqlite3.connect(path)
    _m001_base_tables(conn)
    conn.commit()
    return conn
