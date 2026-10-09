"""SQLite-хранилище: чаты, игроки, засчитанные ранкед-матчи.

Аккаунт Steam (`accounts`: ранг, ник, «обновлён») и его матчи (`matches`) хранятся один раз, сколько бы чатов
его ни отслеживало; `players` — участие аккаунта в чате (ник, стартовый MMR, привязка к Telegram). Методы
принимают id игрока чата и сами находят его аккаунт.

Соединение открывается на каждый вызов (объём операций крошечный, конкуренция низкая),
что снимает проблему «SQLite objects can only be used in the same thread» с aiogram.
Матчи хранятся в сыром виде (player_slot/radiant_win), чтобы stats.aggregate оставался
единственным источником истины для расчёта побед/поражений.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from bisect import bisect_left
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from mmrbot.migrations import LATEST_VERSION, migrate

DEFAULT_DIGEST_HOUR = 10
DEFAULT_MMR_STEP = 25
DEFAULT_TZ = "Europe/Moscow"
DEFAULT_MAX_PLAYERS = 16
# Номер схемы (PRAGMA user_version) — номер последней миграции из mmrbot/migrations.py.
SCHEMA_VERSION = LATEST_VERSION


@dataclass
class Chat:
    chat_id: int
    digest_hour: int
    mmr_step: int
    tz: str
    last_digest_date: Optional[str] = None  # ISO-дата последнего отправленного дайджеста
    notify_steam: bool = True  # оповещать о смене ника/аватарки Steam
    notify_games: bool = True  # оповещать о новых играх и достижениях
    notify_weekly: bool = True  # недельная сводка
    last_weekly: Optional[str] = None  # ключ ISO-недели последней отправленной сводки
    notify_start: bool = True  # оповещать, когда игрок зашёл в Dota 2 (Steam Web API)
    tag_mmr: bool = False  # ставить участникам тег с MMR (нужно право админа «управлять тегами»)
    notify_digest: bool = True  # ежедневная сводка
    admin_only: bool = True  # в группе настройки и удаление игроков — только админам чата
    active: bool = True  # False — бота убрали из чата: не опрашиваем и не пишем, данные храним
    prefer_text: bool = False  # отчёты текстом вместо картинок (настройка чата «🖼 Отчёты»)


@dataclass
class Player:
    id: int
    chat_id: int
    account_id: int
    display_name: str
    anchor_mmr: Optional[int]
    anchor_ts: int
    created_ts: int
    last_rank_tier: Optional[int]
    last_leaderboard_rank: Optional[int]
    updated_ts: Optional[int]
    steam_name: Optional[str] = None  # последний известный ник в Steam (для оповещений о смене)
    steam_avatar: Optional[str] = None
    profile_ts: Optional[int] = None  # когда последний раз получили профиль (ранг) из OpenDota
    history_ts: Optional[int] = None  # когда последний раз сверяли историю глубоко (список на 200 матчей)
    fh_unavailable: bool = False  # OpenDota: история матчей игрока закрыта — цифры могут быть неполными
    ingame_since: Optional[int] = None  # когда зашёл в Dota 2 (по Steam); None — не в игре
    ingame_misses: int = 0  # опросов подряд без Dota (гасит дребезг статуса)
    lineups_ts: Optional[int] = None  # когда история аккаунта целиком перечитана вместе с составами команд
    tg_user_id: Optional[int] = None  # Telegram-аккаунт игрока (командой /me) — для тега участника
    last_tag: Optional[str] = None  # тег, который бот поставил в последний раз


class _Connection(sqlite3.Connection):
    """`with conn:` дополнительно закрывает соединение (стандартное только коммитит) — без утечек дескрипторов."""

    def __exit__(self, exc_type, exc, tb):
        try:
            return super().__exit__(exc_type, exc, tb)
        finally:
            self.close()


class Storage:
    MATCH_CACHE_ROWS = 30_000  # строк матчей в памяти суммарно (≈ 60–70 МБ): хватает пати на 16 игроков по ~1800 игр

    def __init__(
        self, db_path: str, default_digest_hour: int = DEFAULT_DIGEST_HOUR,
        default_mmr_step: int = DEFAULT_MMR_STEP, default_tz: str = DEFAULT_TZ,
        max_players: int = DEFAULT_MAX_PLAYERS,
    ):
        self.db_path = db_path
        self.max_players = max_players  # предел игроков на чат (MAX_PLAYERS): каждый тратит общий лимит OpenDota
        # Значения для новых чатов (из .env: DEFAULT_DIGEST_HOUR / DEFAULT_MMR_STEP / DEFAULT_TZ).
        self.default_digest_hour = default_digest_hour
        self.default_mmr_step = default_mmr_step
        self.default_tz = default_tz
        # B3: история матчей аккаунта в памяти по «версии данных» accounts.data_ver (её двигают триггеры на matches).
        self._matches_cache: OrderedDict = OrderedDict()
        self._matches_cache_lock = threading.Lock()
        migrate(db_path)  # схема: нумерованные миграции (mmrbot/migrations.py)

    def _conn(self) -> sqlite3.Connection:
        # timeout: фоновые джобы и хендлеры пишут из разных потоков — ждём блокировку, а не падаем.
        conn = sqlite3.connect(self.db_path, timeout=30, factory=_Connection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA synchronous = NORMAL")  # в WAL безопасно и заметно быстрее записи
        return conn

    # --- chats ----------------------------------------------------------

    def get_or_create_chat(self, chat_id: int) -> Chat:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO chats (chat_id, digest_hour, mmr_step, tz) VALUES (?, ?, ?, ?)",
                    (chat_id, self.default_digest_hour, self.default_mmr_step, self.default_tz),
                )
                row = conn.execute("SELECT * FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
            return self._chat_from_row(row)

    @staticmethod
    def _chat_from_row(row: sqlite3.Row) -> Chat:
        return Chat(
            chat_id=row["chat_id"],
            digest_hour=row["digest_hour"],
            mmr_step=row["mmr_step"],
            tz=row["tz"],
            last_digest_date=row["last_digest_date"],
            notify_steam=bool(row["notify_steam"]),
            notify_games=bool(row["notify_games"]),
            notify_weekly=bool(row["notify_weekly"]),
            last_weekly=row["last_weekly"],
            notify_start=bool(row["notify_start"]),
            tag_mmr=bool(row["tag_mmr"]),
            notify_digest=bool(row["notify_digest"]),
            admin_only=bool(row["admin_only"]),
            active=bool(row["active"]),
            prefer_text=bool(row["prefer_text"]),
        )

    def _set_chat_flag(self, chat_id: int, column: str, enabled: bool) -> None:
        assert column in {"notify_digest", "admin_only", "active", "prefer_text"}
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE chats SET {column} = ? WHERE chat_id = ?", (1 if enabled else 0, chat_id))

    def set_chat_notify_digest(self, chat_id: int, enabled: bool) -> None:
        self._set_chat_flag(chat_id, "notify_digest", enabled)

    def set_chat_admin_only(self, chat_id: int, enabled: bool) -> None:
        self._set_chat_flag(chat_id, "admin_only", enabled)

    def set_chat_prefer_text(self, chat_id: int, enabled: bool) -> None:
        self._set_chat_flag(chat_id, "prefer_text", enabled)

    def set_chat_active(self, chat_id: int, active: bool) -> None:
        """Бота убрали из чата (False) или вернули (True). Строку чата без нужды не создаём."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE chats SET active = ? WHERE chat_id = ? AND active != ?",
                (1 if active else 0, chat_id, 1 if active else 0),
            )

    def migrate_chat(self, old_chat_id: int, new_chat_id: int) -> bool:
        """Группа стала супергруппой: Telegram меняет chat_id. Переносим настройки и игроков на новый id.

        Вернуть True, если было что переносить. Если под новым id уже есть чат (пользователи успели
        что-то написать), его настройки заменяются перенесёнными, а его игроки остаются; игрок с тем же
        аккаунтом, что у переносимого, уступает место переносимому — у того история.
        """
        if old_chat_id == new_chat_id:
            return False
        with self._conn() as conn:
            if conn.execute("SELECT 1 FROM chats WHERE chat_id = ?", (old_chat_id,)).fetchone() is None:
                return False
            clash = conn.execute(
                "SELECT id FROM players WHERE chat_id = ? AND account_id IN "
                "(SELECT account_id FROM players WHERE chat_id = ?)",
                (new_chat_id, old_chat_id),
            ).fetchall()
            for row in clash:  # история аккаунта общая и остаётся у переносимого игрока
                self._delete_player_data(conn, row["id"])
                conn.execute("DELETE FROM players WHERE id = ?", (row["id"],))
            conn.execute("DELETE FROM chats WHERE chat_id = ?", (new_chat_id,))
            conn.execute("UPDATE chats SET chat_id = ?, active = 1 WHERE chat_id = ?", (new_chat_id, old_chat_id))
            conn.execute("UPDATE players SET chat_id = ? WHERE chat_id = ?", (new_chat_id, old_chat_id))
        return True

    def set_chat_notify_games(self, chat_id: int, enabled: bool) -> None:
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute("UPDATE chats SET notify_games = ? WHERE chat_id = ?", (1 if enabled else 0, chat_id))

    def set_chat_notify_start(self, chat_id: int, enabled: bool) -> None:
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute("UPDATE chats SET notify_start = ? WHERE chat_id = ?", (1 if enabled else 0, chat_id))

    def set_chat_tag_mmr(self, chat_id: int, enabled: bool) -> None:
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute("UPDATE chats SET tag_mmr = ? WHERE chat_id = ?", (1 if enabled else 0, chat_id))

    def link_user(self, chat_id: int, player_id: int, user_id: int) -> None:
        """Привязать Telegram-аккаунт к игроку: в чате аккаунт — один игрок, у игрока — один аккаунт."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE players SET tg_user_id = NULL, last_tag = NULL "
                "WHERE chat_id = ? AND (tg_user_id = ? OR id = ?)",
                (chat_id, user_id, player_id),
            )
            conn.execute("UPDATE players SET tg_user_id = ? WHERE id = ?", (user_id, player_id))

    def unlink_user(self, chat_id: int, user_id: int) -> Optional[Player]:
        """Отвязать аккаунт; вернуть игрока, к которому он был привязан (None — привязки не было)."""
        with self._conn() as conn:
            row = conn.execute(
                f"{self._PLAYER_SELECT} WHERE p.chat_id = ? AND p.tg_user_id = ?", (chat_id, user_id)
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE players SET tg_user_id = NULL, last_tag = NULL WHERE id = ?", (row["id"],))
            return self._player_from_row(row)

    def set_player_tag(self, player_id: int, tag: Optional[str]) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE players SET last_tag = ? WHERE id = ?", (tag, player_id))

    def set_player_presence(self, player_id: int, since: Optional[int], misses: int) -> None:
        with self._conn() as conn:
            conn.execute(
                f"UPDATE accounts SET ingame_since = ?, ingame_misses = ? WHERE account_id = {self._ACCOUNT_OF}",
                (since, misses, player_id),
            )

    def set_chat_notify_weekly(self, chat_id: int, enabled: bool) -> None:
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute("UPDATE chats SET notify_weekly = ? WHERE chat_id = ?", (1 if enabled else 0, chat_id))

    def set_last_weekly(self, chat_id: int, key: str) -> None:
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute("UPDATE chats SET last_weekly = ? WHERE chat_id = ?", (key, chat_id))

    def set_chat_tz(self, chat_id: int, tz: str) -> None:
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute("UPDATE chats SET tz = ? WHERE chat_id = ?", (tz, chat_id))

    def set_chat_notify_steam(self, chat_id: int, enabled: bool) -> None:
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute("UPDATE chats SET notify_steam = ? WHERE chat_id = ?", (1 if enabled else 0, chat_id))

    def set_chat_step(self, chat_id: int, step: int) -> None:
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute("UPDATE chats SET mmr_step = ? WHERE chat_id = ?", (step, chat_id))

    def set_chat_digest_hour(self, chat_id: int, hour: int) -> None:
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute("UPDATE chats SET digest_hour = ? WHERE chat_id = ?", (hour, chat_id))

    def set_last_digest_date(self, chat_id: int, date_str: str) -> None:
        self.get_or_create_chat(chat_id)
        with self._conn() as conn:
            conn.execute("UPDATE chats SET last_digest_date = ? WHERE chat_id = ?", (date_str, chat_id))

    def list_chats(self, include_inactive: bool = False) -> list[Chat]:
        """Чаты, где бот работает. Чаты, откуда его убрали, — только с include_inactive=True."""
        query = "SELECT * FROM chats" if include_inactive else "SELECT * FROM chats WHERE active = 1"
        with self._conn() as conn:
            rows = conn.execute(query).fetchall()
        return [self._chat_from_row(r) for r in rows]

    def count_players(self, chat_id: int) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM players WHERE chat_id = ?", (chat_id,)).fetchone()[0]

    # --- players --------------------------------------------------------

    # Игрок чата вместе с состоянием его аккаунта Steam (ранг, ник, «обновлён» — общие для всех чатов).
    _PLAYER_SELECT = (
        "SELECT p.id, p.chat_id, p.account_id, p.display_name, p.anchor_mmr, p.anchor_ts, p.created_ts, "
        "p.tg_user_id, p.last_tag, a.last_rank_tier, a.last_leaderboard_rank, a.updated_ts, a.steam_name, "
        "a.steam_avatar, a.profile_ts, a.history_ts, a.fh_unavailable, a.ingame_since, a.ingame_misses, a.lineups_ts "
        "FROM players p JOIN accounts a ON a.account_id = p.account_id"
    )
    # Аккаунт игрока — для запросов к матчам по id игрока чата.
    _ACCOUNT_OF = "(SELECT account_id FROM players WHERE id = ?)"

    def _player_from_row(self, row: sqlite3.Row) -> Player:
        return Player(
            id=row["id"],
            chat_id=row["chat_id"],
            account_id=row["account_id"],
            display_name=row["display_name"],
            anchor_mmr=row["anchor_mmr"],
            anchor_ts=row["anchor_ts"],
            created_ts=row["created_ts"],
            last_rank_tier=row["last_rank_tier"],
            last_leaderboard_rank=row["last_leaderboard_rank"],
            updated_ts=row["updated_ts"],
            steam_name=row["steam_name"],
            steam_avatar=row["steam_avatar"],
            profile_ts=row["profile_ts"],
            history_ts=row["history_ts"],
            fh_unavailable=bool(row["fh_unavailable"]),
            ingame_since=row["ingame_since"],
            ingame_misses=row["ingame_misses"] or 0,
            lineups_ts=row["lineups_ts"],
            tg_user_id=row["tg_user_id"],
            last_tag=row["last_tag"],
        )

    def update_player_steam(self, player_id: int, name: Optional[str], avatar: Optional[str]) -> dict:
        """Сохранить ник/аватарку Steam аккаунта игрока; вернуть изменения относительно прошлых значений.

        Первое заполнение (раньше значения не было) изменением не считается. Пустые значения
        не затирают сохранённые. Значения общие для аккаунта: повторный вызов для того же аккаунта
        из другого чата изменений уже не увидит — вызывающий опрашивает аккаунт один раз.
        """
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT account_id, steam_name, steam_avatar FROM accounts WHERE account_id = {self._ACCOUNT_OF}",
                (player_id,),
            ).fetchone()
            if row is None:
                return {}
            old_name, old_avatar = row["steam_name"], row["steam_avatar"]
            changes: dict = {}
            if name and old_name is not None and name != old_name:
                changes["name"] = (old_name, name)
            if avatar and old_avatar is not None and avatar != old_avatar:
                changes["avatar"] = True
            conn.execute(
                "UPDATE accounts SET steam_name = ?, steam_avatar = ? WHERE account_id = ?",
                (name or old_name, avatar or old_avatar, row["account_id"]),
            )
        return changes

    def add_player(
        self,
        chat_id: int,
        account_id: int,
        display_name: str,
        anchor_mmr: Optional[int],
        anchor_ts: int,
        created_ts: int,
    ) -> Player:
        """Добавить игрока в чат. Аккаунт, который уже отслеживает другой чат, приходит со всей своей историей."""
        if self.nick_taken(chat_id, display_name):  # «Вася» и «вася» — один ник: команды находят игрока без учёта регистра
            raise ValueError(f"Ник «{display_name}» в этом чате уже занят (регистр не важен) — выберите другой.")
        with self._conn() as conn:
            try:
                cur = conn.execute(
                    "INSERT INTO players (chat_id, account_id, display_name, anchor_mmr, anchor_ts, created_ts) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (chat_id, account_id, display_name, anchor_mmr, anchor_ts, created_ts),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Этот аккаунт уже добавлен в этот чат.") from exc
            conn.execute("INSERT OR IGNORE INTO accounts (account_id) VALUES (?)", (account_id,))
            if anchor_mmr is not None:
                conn.execute(
                    "INSERT INTO mmr_anchors (player_id, ts, mmr) VALUES (?, ?, ?)", (cur.lastrowid, anchor_ts, anchor_mmr)
                )
            row = conn.execute(f"{self._PLAYER_SELECT} WHERE p.id = ?", (cur.lastrowid,)).fetchone()
            return self._player_from_row(row)

    def nick_taken(self, chat_id: int, name: str) -> bool:
        """Есть ли в чате игрок с таким ником (без учёта регистра; SQLite lower() кириллицу не трогает)."""
        wanted = (name or "").strip().lower()
        return any(p.display_name.lower() == wanted for p in self.list_players(chat_id))

    def get_player(self, chat_id: int, key: str) -> Optional[Player]:
        # Регистронезависимое сравнение делаем в Python: SQLite lower() не трогает кириллицу.
        key = (key or "").strip()
        key_lower = key.lower()
        players = self.list_players(chat_id)
        for player in players:
            if player.display_name.lower() == key_lower:
                return player
        # str.isdigit() шире int() (unicode-цифры), поэтому int() под защитой.
        try:
            account_id = int(key)
        except ValueError:
            return None
        for player in players:
            if player.account_id == account_id:
                return player
        return None

    def get_player_by_account_id(self, chat_id: int, account_id: int) -> Optional[Player]:
        """Точный поиск по account_id (без неоднозначности имён) — для внутренней перечитки."""
        for player in self.list_players(chat_id):
            if player.account_id == account_id:
                return player
        return None

    def get_player_by_id(self, player_id: int) -> Optional[Player]:
        with self._conn() as conn:
            row = conn.execute(f"{self._PLAYER_SELECT} WHERE p.id = ?", (player_id,)).fetchone()
        return self._player_from_row(row) if row else None

    def list_players(self, chat_id: int) -> list[Player]:
        with self._conn() as conn:
            rows = conn.execute(f"{self._PLAYER_SELECT} WHERE p.chat_id = ? ORDER BY p.id", (chat_id,)).fetchall()
        return [self._player_from_row(r) for r in rows]

    def chats_of_account(self, account_id: int) -> list[int]:
        """Чаты (в т.ч. приостановленные), где отслеживается аккаунт."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT chat_id FROM players WHERE account_id = ? ORDER BY chat_id", (account_id,)
            ).fetchall()
        return [r["chat_id"] for r in rows]

    @staticmethod
    def _delete_player_rows(conn: sqlite3.Connection, player_id: int, account_id: int) -> None:
        """Убрать игрока чата; историю и состояние аккаунта — только если его больше никто не отслеживает."""
        Storage._delete_player_data(conn, player_id)
        conn.execute("DELETE FROM players WHERE id = ?", (player_id,))
        if conn.execute("SELECT 1 FROM players WHERE account_id = ? LIMIT 1", (account_id,)).fetchone() is None:
            conn.execute("DELETE FROM matches WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM accounts WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM match_lineups WHERE match_id NOT IN (SELECT match_id FROM matches)")

    # Таблицы с данными игрока чата (ключ player_id): чистятся вместе с игроком.
    _PLAYER_TABLES = ("pending_notices", "mmr_anchors")

    @staticmethod
    def _delete_player_data(conn: sqlite3.Connection, player_id: int) -> None:
        for table in Storage._PLAYER_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE player_id = ?", (player_id,))

    def remove_player(self, chat_id: int, key: str) -> bool:
        player = self.get_player(chat_id, key)
        if player is None:
            return False
        with self._conn() as conn:
            self._delete_player_rows(conn, player.id, player.account_id)
        with self._matches_cache_lock:
            if not self.chats_of_account(player.account_id):
                self._matches_cache.pop(player.account_id, None)
        return True

    def set_player_anchor(self, player_id: int, anchor_mmr: int, anchor_ts: int) -> None:
        """Задать MMR игрока на момент anchor_ts: запись добавляется в журнал правок, прежние остаются."""
        with self._conn() as conn:
            if conn.execute("SELECT 1 FROM players WHERE id = ?", (player_id,)).fetchone() is None:
                return
            conn.execute(
                "UPDATE players SET anchor_mmr = ?, anchor_ts = ?, rev = rev + 1 WHERE id = ?",
                (anchor_mmr, anchor_ts, player_id),
            )
            conn.execute("INSERT INTO mmr_anchors (player_id, ts, mmr) VALUES (?, ?, ?)", (player_id, anchor_ts, anchor_mmr))

    def get_anchors(self, player_id: int) -> list[tuple[int, int]]:
        """Журнал заданий MMR игрока по времени: [(когда, MMR)]. Пусто — MMR не задавали."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT ts, mmr FROM mmr_anchors WHERE player_id = ? ORDER BY ts, id", (player_id,)
            ).fetchall()
        return [(r["ts"], r["mmr"]) for r in rows]

    def update_player_rank(
        self, player_id: int, rank_tier: Optional[int], leaderboard_rank: Optional[int], updated_ts: int
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE accounts SET last_rank_tier = ?, last_leaderboard_rank = ?, updated_ts = ? "
                f"WHERE account_id = {self._ACCOUNT_OF}",
                (rank_tier, leaderboard_rank, updated_ts, player_id),
            )

    def set_player_rank(
        self, player_id: int, rank_tier: Optional[int], leaderboard_rank: Optional[int], profile_ts: int,
        fh_unavailable: Optional[bool] = None,
    ) -> None:
        """Сохранить ранг из профиля, не трогая updated_ts (тот отмечает успешную сверку матчей).

        fh_unavailable=None — профиль признака не дал (сбой), прежнее значение не трогаем.
        """
        with self._conn() as conn:
            conn.execute(
                "UPDATE accounts SET last_rank_tier = ?, last_leaderboard_rank = ?, profile_ts = ? "
                f"WHERE account_id = {self._ACCOUNT_OF}",
                (rank_tier, leaderboard_rank, profile_ts, player_id),
            )
            if fh_unavailable is not None:
                conn.execute(
                    f"UPDATE accounts SET fh_unavailable = ? WHERE account_id = {self._ACCOUNT_OF}",
                    (1 if fh_unavailable else 0, player_id),
                )

    def touch_player(self, player_id: int, updated_ts: int, deep: bool = False) -> None:
        """Отметить успешную сверку матчей аккаунта (deep — сверяли глубоко, списком на 200 матчей)."""
        with self._conn() as conn:
            if deep:
                conn.execute(
                    f"UPDATE accounts SET updated_ts = ?, history_ts = ? WHERE account_id = {self._ACCOUNT_OF}",
                    (updated_ts, updated_ts, player_id),
                )
            else:
                conn.execute(
                    f"UPDATE accounts SET updated_ts = ? WHERE account_id = {self._ACCOUNT_OF}", (updated_ts, player_id)
                )

    # --- matches --------------------------------------------------------

    # Поля, которые OpenDota может отдать позже (матч ещё не разобран) — дозаполняем при повторной выдаче.
    _FILL_FIELDS = (
        "hero_id", "duration", "party_size", "average_rank",
        "gpm", "xpm", "last_hits", "hero_damage", "tower_damage", "hero_healing", "leaver_status",
    )

    def add_matches(self, player_id: int, matches: list[dict]) -> int:
        """Вставить матчи аккаунта игрока; вернуть число новых.

        Уже сохранённый матч не перезаписывается, но его пустые поля (размер пати, средний ранг,
        длительность, GPM и т.п.) дозаполняются: в первой выдаче OpenDota они часто ещё null.
        Новый матч ставится в очередь оповещения каждому чату, где отслеживается аккаунт.
        """
        if not matches:
            return 0
        columns = ("account_id", "match_id", "start_time", "player_slot", "radiant_win", "lobby_type",
                   "kills", "deaths", "assists") + self._FILL_FIELDS
        fill = ", ".join(f"{f} = COALESCE({f}, excluded.{f})" for f in self._FILL_FIELDS)
        # Уже известный матч трогаем, только если пришло что-то новое для пустого поля: пустая запись не двигает data_ver.
        fills_something = " OR ".join(f"({f} IS NULL AND excluded.{f} IS NOT NULL)" for f in self._FILL_FIELDS)
        with self._conn() as conn:
            row = conn.execute("SELECT account_id FROM players WHERE id = ?", (player_id,)).fetchone()
            if row is None:
                return 0
            account_id = row["account_id"]
            known = {r[0] for r in conn.execute("SELECT match_id FROM matches WHERE account_id = ?", (account_id,))}
            rows = [
                (
                    account_id,
                    m["match_id"],
                    m["start_time"],
                    m["player_slot"],
                    1 if m["radiant_win"] else 0,
                    m.get("lobby_type"),
                    m.get("kills", 0) or 0,
                    m.get("deaths", 0) or 0,
                    m.get("assists", 0) or 0,
                ) + tuple(m.get(f) for f in self._FILL_FIELDS)
                for m in matches
            ]
            conn.executemany(
                f"INSERT INTO matches ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))}) "
                f"ON CONFLICT(account_id, match_id) DO UPDATE SET {fill} WHERE {fills_something}",
                rows,
            )
            new_ids = sorted({m["match_id"] for m in matches} - known)
            self._save_lineups(conn, [(m["match_id"], m["lineup"]) for m in matches if m.get("lineup")])
            if new_ids:
                watchers = [r[0] for r in conn.execute("SELECT id FROM players WHERE account_id = ?", (account_id,))]
                conn.executemany(
                    "INSERT OR IGNORE INTO pending_notices (player_id, match_id) VALUES (?, ?)",
                    [(watcher, match_id) for watcher in watchers for match_id in new_ids],
                )
            return len(new_ids)

    def has_matches(self, player_id: int) -> bool:
        with self._conn() as conn:
            return conn.execute(
                f"SELECT 1 FROM matches WHERE account_id = {self._ACCOUNT_OF} LIMIT 1", (player_id,)
            ).fetchone() is not None

    def latest_match_time(self, player_id: int) -> Optional[int]:
        """start_time самого свежего сохранённого матча игрока (None — матчей нет)."""
        with self._conn() as conn:
            return conn.execute(
                f"SELECT MAX(start_time) FROM matches WHERE account_id = {self._ACCOUNT_OF}", (player_id,)
            ).fetchone()[0]

    def last_activity(self, chat_id: int) -> Optional[int]:
        """Время окончания самого свежего матча среди игроков чата (None — матчей нет)."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT MAX(m.start_time + COALESCE(m.duration, 0)) FROM matches m "
                "JOIN players p ON p.account_id = m.account_id WHERE p.chat_id = ?",
                (chat_id,),
            ).fetchone()[0]

    def data_version(self, chat_id: int) -> tuple:
        """Отпечаток данных чата (число матчей, самый свежий, ревизия): меняется, когда приходят новые игры или
        правятся данные игроков — заданный MMR, пометки матчей (дабл-даун), дозаполненные поля."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*), MAX(m.start_time) FROM matches m "
                "JOIN players p ON p.account_id = m.account_id WHERE p.chat_id = ?",
                (chat_id,),
            ).fetchone()
            rev = conn.execute(
                "SELECT COALESCE(SUM(p.rev + a.data_ver), 0) FROM players p JOIN accounts a ON a.account_id = p.account_id "
                "WHERE p.chat_id = ?", (chat_id,),
            ).fetchone()[0]
        return (row[0], row[1], rev)

    def get_latest_match(self, player_ids: list[int], match_id: Optional[int] = None) -> Optional[dict]:
        """Самый свежий матч среди игроков (или конкретный match_id) одним запросом, без выгрузки истории.

        В строке, кроме полей матча, — player_id: чей это матч из перечисленных игроков.
        """
        if not player_ids:
            return None
        query = (
            "SELECT m.*, p.id AS player_id FROM matches m JOIN players p ON p.account_id = m.account_id "
            f"WHERE p.id IN ({', '.join('?' * len(player_ids))})"
        )
        params: list = list(player_ids)
        if match_id is not None:
            query += " AND m.match_id = ?"
            params.append(match_id)
        query += " ORDER BY m.start_time DESC, p.id LIMIT 1"
        with self._conn() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    _DETAIL_FIELDS = (
        "gpm", "xpm", "last_hits", "denies", "hero_damage",
        "tower_damage", "hero_healing", "net_worth", "level", "leaver_status",
    )

    def update_match_details(self, player_id: int, match_id: int, details: dict, perf_score) -> None:
        """Записать обогащённые пер-матч поля + perf_score + benchmarks(JSON), пометить enriched=1.

        Пустое значение в ответе не затирает уже известное (например, GPM из списка матчей).
        """
        fields = self._DETAIL_FIELDS + ("party_size", "average_rank")
        assignments = ", ".join(f"{field} = COALESCE(?, {field})" for field in fields)
        bench_json = json.dumps(details.get("benchmarks") or {})
        params = [details.get(field) for field in fields]
        params += [perf_score, bench_json, player_id, match_id]
        with self._conn() as conn:
            self._save_lineups(conn, [(match_id, details.get("lineup"))])
            conn.execute(
                f"UPDATE matches SET {assignments}, perf_score = ?, bench_json = ?, enriched = 1 "
                f"WHERE account_id = {self._ACCOUNT_OF} AND match_id = ?",
                params,
            )

    def update_match_stratz(self, player_id: int, match_id: int, info: dict) -> None:
        """Записать данные Stratz: позиция/роль/лейн/IMP + дозаполнить пустые числовые поля."""
        fill = ", ".join(f"{f} = COALESCE({f}, ?)" for f in self._DETAIL_FIELDS + ("party_size",))
        params = [info.get("position"), info.get("role"), info.get("lane"), info.get("imp")]
        params += [info.get(f) for f in self._DETAIL_FIELDS + ("party_size",)]
        params += [player_id, match_id]
        with self._conn() as conn:
            self._save_lineups(conn, [(match_id, info.get("lineup"))])
            conn.execute(
                f"UPDATE matches SET position = ?, role = ?, lane = ?, imp = ?, stratz_done = 1, {fill} "
                f"WHERE account_id = {self._ACCOUNT_OF} AND match_id = ?",
                params,
            )

    # Пауза перед следующей попыткой после промаха: Stratz разбирает матч не сразу, а иногда — часами.
    STRATZ_BACKOFF = (300, 900, 2700, 7200, 21600, 43200, 86400)

    def get_match_ids_without_stratz(
        self, player_id: int, since_ts: int, limit: int = 20, max_tries: int = 8, now: Optional[int] = None
    ) -> list[int]:
        """Матчи, которых Stratz ещё не отдал (свежие первыми).

        После max_tries промахов сдаёмся; при заданном now матчи, чья пауза повтора ещё не вышла, пропускаем.
        """
        due = "" if now is None else "AND stratz_next_ts <= ? "
        params: list = [player_id, max_tries] + ([] if now is None else [now]) + [since_ts, limit]
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT match_id FROM matches WHERE account_id = {self._ACCOUNT_OF} "
                "AND (stratz_done = 0 OR party_size IS NULL) "
                f"AND stratz_tries < ? {due}AND start_time >= ? ORDER BY start_time DESC LIMIT ?",
                params,
            ).fetchall()
        return [r["match_id"] for r in rows]

    def mark_stratz_miss(self, player_id: int, match_ids: list[int], now: int = 0) -> None:
        """Stratz не вернул матч — копим попытки и откладываем следующую с растущей паузой."""
        with self._conn() as conn:
            for mid in match_ids:
                row = conn.execute(
                    f"SELECT stratz_tries FROM matches WHERE account_id = {self._ACCOUNT_OF} AND match_id = ?",
                    (player_id, mid),
                ).fetchone()
                if row is None:
                    continue
                tries = row["stratz_tries"]
                delay = self.STRATZ_BACKOFF[min(tries, len(self.STRATZ_BACKOFF) - 1)]
                conn.execute(
                    "UPDATE matches SET stratz_tries = stratz_tries + 1, stratz_next_ts = ? "
                    f"WHERE account_id = {self._ACCOUNT_OF} AND match_id = ?",
                    (now + delay, player_id, mid),
                )

    def get_unenriched_match_ids(
        self, player_id: int, since_ts: int, limit: int, max_tries: int = 3
    ) -> list[int]:
        """match_id матчей без обогащения (свежие первыми); после max_tries пустых ответов — сдаёмся."""
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT match_id FROM matches WHERE account_id = {self._ACCOUNT_OF} AND enriched = 0 "
                "AND enrich_tries < ? AND start_time >= ? ORDER BY start_time DESC LIMIT ?",
                (player_id, max_tries, since_ts, limit),
            ).fetchall()
        return [r["match_id"] for r in rows]

    def get_match_hints(self, player_id: int, match_ids: list[int]) -> dict[int, tuple[bool, Optional[int]]]:
        """{match_id: (за силы света?, hero_id)} — по ним Stratz находит игрока со скрытым профилем."""
        if not match_ids:
            return {}
        marks = ",".join("?" * len(match_ids))
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT match_id, player_slot, hero_id FROM matches WHERE account_id = {self._ACCOUNT_OF} "
                f"AND match_id IN ({marks})",
                [player_id, *match_ids],
            ).fetchall()
        return {r["match_id"]: (r["player_slot"] < 128, r["hero_id"]) for r in rows}

    def get_match_slot(self, player_id: int, match_id: int) -> Optional[int]:
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT player_slot FROM matches WHERE account_id = {self._ACCOUNT_OF} AND match_id = ?",
                (player_id, match_id),
            ).fetchone()
        return None if row is None else row["player_slot"]

    def set_double_down(self, player_id: int, match_id: int, enabled: Optional[bool] = None) -> Optional[bool]:
        """Пометить матч игрока как сыгранный с дабл-дауном (±2 шага MMR). enabled=None — переключить.

        Вернуть новое состояние; None — такого матча у игрока нет. Пометка — факт о матче аккаунта:
        она общая для всех чатов, где аккаунт отслеживается.
        """
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT double_down FROM matches WHERE account_id = {self._ACCOUNT_OF} AND match_id = ?",
                (player_id, match_id),
            ).fetchone()
            if row is None:
                return None
            value = (not row["double_down"]) if enabled is None else bool(enabled)
            if bool(row["double_down"]) != value:
                conn.execute(
                    f"UPDATE matches SET double_down = ? WHERE account_id = {self._ACCOUNT_OF} AND match_id = ?",
                    (1 if value else 0, player_id, match_id),
                )
            return value

    def get_match(self, player_id: int, match_id: int) -> Optional[dict]:
        """Строка матча игрока (None — нет такого)."""
        with self._conn() as conn:
            row = conn.execute(
                f"SELECT * FROM matches WHERE account_id = {self._ACCOUNT_OF} AND match_id = ?", (player_id, match_id)
            ).fetchone()
        return dict(row) if row else None

    # Матчи аккаунтов, которые отслеживает хотя бы один активный чат (аккаунт в двух чатах считается один раз).
    _ACTIVE_MATCHES = (
        "FROM matches m WHERE EXISTS (SELECT 1 FROM players p JOIN chats c ON c.chat_id = p.chat_id "
        "WHERE p.account_id = m.account_id AND c.active = 1) AND "
    )

    def backlog_counts(self, enrich_since: int, enrich_max_tries: int = 3, stratz_max_tries: int = 8) -> dict:
        """Размер очередей фоновой догрузки по аккаунтам активных чатов: детали матчей (OpenDota) и данные Stratz."""
        base = self._ACTIVE_MATCHES
        with self._conn() as conn:
            details = conn.execute(
                f"SELECT COUNT(*) {base}m.enriched = 0 AND m.enrich_tries < ? AND m.start_time >= ?",
                (enrich_max_tries, enrich_since),
            ).fetchone()[0]
            stratz = conn.execute(
                f"SELECT COUNT(*) {base}(m.stratz_done = 0 OR m.party_size IS NULL) AND m.stratz_tries < ?",
                (stratz_max_tries,),
            ).fetchone()[0]
        return {"details": details, "stratz": stratz}

    def player_update_times(self) -> list[Optional[int]]:
        """updated_ts (последняя успешная сверка матчей) всех игроков активных чатов; None — ещё не обновлялся."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT a.updated_ts FROM players p JOIN chats c ON c.chat_id = p.chat_id "
                "JOIN accounts a ON a.account_id = p.account_id WHERE c.active = 1"
            ).fetchall()
        return [r["updated_ts"] for r in rows]

    def mark_enrich_miss(self, player_id: int, match_id: int) -> None:
        """OpenDota не отдал детали матча — копим попытки, чтобы он не блокировал очередь."""
        with self._conn() as conn:
            conn.execute(
                f"UPDATE matches SET enrich_tries = enrich_tries + 1 WHERE account_id = {self._ACCOUNT_OF} "
                "AND match_id = ?",
                (player_id, match_id),
            )

    # --- составы команд ------------------------------------------------------------

    @staticmethod
    def _save_lineups(conn: sqlite3.Connection, lineups: list) -> None:
        """Сохранить составы: [(match_id, (герои света, герои тьмы))]. Более полный состав заменяет неполный."""
        rows = []
        for match_id, lineup in lineups:
            if not lineup:
                continue
            radiant = [int(h) for h in lineup[0] if h]
            dire = [int(h) for h in lineup[1] if h]
            if radiant and dire:
                rows.append((match_id, ",".join(map(str, radiant)), ",".join(map(str, dire))))
        if rows:
            conn.executemany(
                "INSERT INTO match_lineups (match_id, radiant, dire) VALUES (?, ?, ?) "
                "ON CONFLICT(match_id) DO UPDATE SET radiant = excluded.radiant, dire = excluded.dire "
                "WHERE length(excluded.radiant) + length(excluded.dire) > length(radiant) + length(dire)",
                rows,
            )

    def get_lineups(self, player_id: int, since_ts: Optional[int] = None) -> dict[int, tuple[tuple, tuple]]:
        """Составы матчей игрока: {match_id: (герои света, герои тьмы)}; матчей без известного состава в ответе нет."""
        query = (
            "SELECT l.match_id, l.radiant, l.dire FROM match_lineups l JOIN matches m ON m.match_id = l.match_id "
            f"WHERE m.account_id = {self._ACCOUNT_OF}"
        )
        params: list = [player_id]
        if since_ts is not None:
            query += " AND m.start_time >= ?"
            params.append(since_ts)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return {
            r["match_id"]: (tuple(int(h) for h in r["radiant"].split(",")), tuple(int(h) for h in r["dire"].split(",")))
            for r in rows
        }

    def lineups_synced_ts(self, player_id: int) -> Optional[int]:
        """Когда история аккаунта перечитана вместе с составами (из БД: объект игрока в руках вызывающего мог устареть)."""
        with self._conn() as conn:
            row = conn.execute(f"SELECT lineups_ts FROM accounts WHERE account_id = {self._ACCOUNT_OF}", (player_id,)).fetchone()
        return row["lineups_ts"] if row else None

    def mark_lineups_synced(self, player_id: int, ts: int) -> None:
        """История аккаунта целиком перечитана вместе с составами — повторять полную выгрузку не нужно."""
        with self._conn() as conn:
            conn.execute(f"UPDATE accounts SET lineups_ts = ? WHERE account_id = {self._ACCOUNT_OF}", (ts, player_id))

    # --- оповещения о матчах: очередь «игрок чата × матч» ----------------------

    def get_unnotified_matches(self, player_id: int, since_ts: int) -> list[dict]:
        """Матчи, о которых чату игрока ещё не сообщали и которые закончились не раньше since_ts.

        Возраст считаем от конца матча: длинная игра при задержке OpenDota иначе молча выпадала из окна.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT m.* FROM pending_notices n JOIN players p ON p.id = n.player_id "
                "JOIN matches m ON m.account_id = p.account_id AND m.match_id = n.match_id "
                "WHERE n.player_id = ? AND m.start_time + COALESCE(m.duration, 0) >= ? ORDER BY m.start_time",
                (player_id, since_ts),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_notified(self, player_id: int, keep: Optional[list[int]] = None) -> None:
        """Снять с очереди оповещения матчи игрока (в т.ч. старые — их не объявляем).

        keep — match_id, которые остаются в очереди: о них ещё предстоит сообщить
        (снимаются через mark_notified_matches после успешной отправки).
        """
        query = "DELETE FROM pending_notices WHERE player_id = ?"
        params: list = [player_id]
        if keep:
            query += f" AND match_id NOT IN ({', '.join('?' * len(keep))})"
            params += list(keep)
        with self._conn() as conn:
            conn.execute(query, params)

    def mark_notified_matches(self, pairs: list[tuple[int, int]]) -> None:
        """Снять с очереди оповещения конкретные матчи: [(player_id, match_id)]."""
        if not pairs:
            return
        with self._conn() as conn:
            conn.executemany("DELETE FROM pending_notices WHERE player_id = ? AND match_id = ?", pairs)

    def announced_match_ids(self, chat_id: int, match_ids: list[int]) -> set[int]:
        """Какие из match_ids уже объявлены в чате: матч есть у кого-то из его игроков и в очереди у того не стоит."""
        if not match_ids:
            return set()
        marks = ", ".join("?" * len(match_ids))
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT m.match_id FROM matches m JOIN players p ON p.account_id = m.account_id "
                f"WHERE p.chat_id = ? AND m.match_id IN ({marks}) AND NOT EXISTS "
                "(SELECT 1 FROM pending_notices n WHERE n.player_id = p.id AND n.match_id = m.match_id)",
                [chat_id, *match_ids],
            ).fetchall()
        return {r["match_id"] for r in rows}

    # --- соревнование: прежние лидеры --------------------------------------

    def get_contest_leaders(self, chat_id: int, period: str) -> dict[str, str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT key, leader FROM contest_leaders WHERE chat_id = ? AND period = ?", (chat_id, period)
            ).fetchall()
        return {r["key"]: r["leader"] for r in rows}

    def set_contest_leaders(self, chat_id: int, period: str, leaders: dict[str, str]) -> None:
        """Заменяет набор лидеров чата за период (номинации, которых больше нет, забываются)."""
        with self._conn() as conn:
            conn.execute("DELETE FROM contest_leaders WHERE chat_id = ? AND period = ?", (chat_id, period))
            conn.executemany(
                "INSERT INTO contest_leaders (chat_id, period, key, leader) VALUES (?, ?, ?, ?)",
                [(chat_id, period, key, leader) for key, leader in leaders.items()],
            )

    # --- история матчей: кэш в памяти по аккаунту ------------------------------

    # Аккаунт игрока, версия его матчей и версия собственных данных игрока чата (MMR, пометки матчей).
    _VERSION_OF = (
        "SELECT a.account_id, a.data_ver, p.rev FROM players p JOIN accounts a ON a.account_id = p.account_id "
        "WHERE p.id = ?"
    )

    def player_data_ver(self, player_id: int) -> int:
        """Версия данных игрока: растёт при любом изменении матчей его аккаунта и его данных в чате; 0 — игрока нет."""
        with self._conn() as conn:
            row = conn.execute(self._VERSION_OF, (player_id,)).fetchone()
        return row["data_ver"] + row["rev"] if row else 0

    def _warm_matches(self, player_id: int, since_ts: Optional[int]) -> Optional[list[dict]]:
        """Матчи из кэша, если он тёплый и актуален; иначе None (тогда дешевле лёгкий запрос, чем грузить всю историю)."""
        with self._conn() as conn:
            row = conn.execute(self._VERSION_OF, (player_id,)).fetchone()
        if row is None:
            return []
        with self._matches_cache_lock:
            cached = self._matches_cache.get(row["account_id"])
            if cached is None or cached[0] != row["data_ver"]:
                return None
            self._matches_cache.move_to_end(row["account_id"])
        _, rows, starts = cached
        return rows if since_ts is None else rows[bisect_left(starts, since_ts):]

    def _light_matches(self, player_id: int, columns: tuple, since_ts: Optional[int]) -> list[dict]:
        warm = self._warm_matches(player_id, since_ts)
        if warm is not None:
            return [{c: m[c] for c in columns} for m in warm]
        query = f"SELECT {', '.join(columns)} FROM matches WHERE account_id = {self._ACCOUNT_OF}"
        params: list = [player_id]
        if since_ts is not None:
            query += " AND start_time >= ?"
            params.append(since_ts)
        query += " ORDER BY start_time"
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_outcomes(self, player_id: int, since_ts: Optional[int] = None) -> list[dict]:
        """Лёгкая выборка исходов (время/длительность/слот/победа) — для графиков: из тёплого кэша матчей, иначе узким запросом."""
        return self._light_matches(
            player_id, ("start_time", "player_slot", "radiant_win", "duration", "double_down"), since_ts)

    def get_match_sides(self, player_id: int, since_ts: Optional[int] = None) -> list[dict]:
        """Лёгкая выборка для совместных игр: id матча, сторона, исход и размер пати."""
        return self._light_matches(
            player_id, ("match_id", "start_time", "player_slot", "radiant_win", "party_size"), since_ts)

    def get_matches(self, player_id: int, since_ts: Optional[int] = None) -> list[dict]:
        """Ранкед-история аккаунта игрока по времени. Строки берутся из кэша, пока accounts.data_ver не изменился.

        Кэш общий для всех чатов, где отслеживается аккаунт. Словари общие с кэшем — их нельзя менять;
        список — копия, его можно резать и сортировать.
        """
        with self._conn() as conn:
            row = conn.execute(self._VERSION_OF, (player_id,)).fetchone()
            if row is None:
                return []
            account_id, version = row["account_id"], row["data_ver"]  # версию читаем до строк: гонка даст лишь перезагрузку
            with self._matches_cache_lock:
                cached = self._matches_cache.get(account_id)
                if cached is not None and cached[0] == version:
                    self._matches_cache.move_to_end(account_id)
                else:
                    cached = None
            if cached is None:
                rows = [dict(r) for r in conn.execute(
                    "SELECT * FROM matches WHERE account_id = ? ORDER BY start_time", (account_id,)
                ).fetchall()]
                cached = (version, rows, [r["start_time"] for r in rows])
                self._remember_matches(account_id, cached)
        _, rows, starts = cached
        return list(rows) if since_ts is None else rows[bisect_left(starts, since_ts):]

    def _remember_matches(self, account_id: int, entry: tuple) -> None:
        with self._matches_cache_lock:
            self._matches_cache[account_id] = entry
            self._matches_cache.move_to_end(account_id)
            total = sum(len(v[1]) for v in self._matches_cache.values())
            while total > self.MATCH_CACHE_ROWS and len(self._matches_cache) > 1:
                _, dropped = self._matches_cache.popitem(last=False)
                total -= len(dropped[1])
