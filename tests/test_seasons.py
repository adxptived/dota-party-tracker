"""Сезоны соревнования: хранение, расчёт итогов, зал славы, автозавершение и команды."""
import asyncio
import time

import pytest
from aiogram.filters import CommandObject

import mmrbot.bot as botmod
from mmrbot import commands as cmd
from mmrbot import scheduler as sched
from mmrbot import seasons, service
from mmrbot.storage import Storage
from mmrbot.tracker import close_season

DAY = 86_400
T0 = 1_780_000_000


@pytest.fixture
def store(tmp_path):
    storage = Storage(str(tmp_path / "s.db"))
    storage.get_or_create_chat(1)
    return storage


def game(match_id, start, win=True):
    return {"match_id": match_id, "start_time": start, "player_slot": 0, "radiant_win": win, "lobby_type": 7,
            "hero_id": 1, "kills": 5, "deaths": 3, "assists": 7, "duration": 1800}


def seed_two_players(store, season_start):
    """Вася выиграл все 4 игры сезона, Петя проиграл все 4; до начала сезона у Пети 10 побед — они не в счёт."""
    vasya = store.add_player(1, 10, "Вася", None, 0, 0)
    petya = store.add_player(1, 20, "Петя", None, 0, 0)
    store.add_matches(vasya.id, [game(100 + i, season_start + i * 3600, True) for i in range(4)])
    store.add_matches(petya.id, [game(200 + i, season_start + i * 3600, False) for i in range(4)]
                      + [game(300 + i, season_start - (i + 1) * 3600, True) for i in range(10)])


# --- разбор аргументов команды ------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("", ("show", None)), ("start", ("start", 30)), ("старт", ("start", 30)), ("start 60", ("start", 60)),
    ("начать 14", ("start", 14)), ("end", ("end", None)), ("конец", ("end", None)), ("stop", ("end", None)),
    ("start 3", ("error", None)), ("start 999", ("error", None)), ("start abc", ("error", None)),
    ("что-то", ("error", None)),
])
def test_parse_season_args(text, expected):
    assert cmd.parse_season_args(text) == expected


# --- хранилище ----------------------------------------------------------------------------

def test_one_active_season_per_chat_and_numbers_grow(store):
    first = store.start_season(1, T0, 30)
    assert (first.number, first.start_ts, first.planned_end_ts, first.end_ts) == (1, T0, T0 + 30 * DAY, None)
    assert store.start_season(1, T0 + 5, 30) is None                       # уже идёт
    assert store.current_season(1).id == first.id and store.current_season(2) is None
    finished, nxt = store.finish_season(first.id, T0 + 31 * DAY, "Вася", [{"player": "Вася", "points": 9, "golds": 3}], renew=True)
    assert finished and nxt.number == 2 and nxt.start_ts == T0 + 31 * DAY and nxt.length_days == 30
    assert store.current_season(1).id == nxt.id
    done = store.list_seasons(1)
    assert [s.number for s in done] == [1] and done[0].champion == "Вася" and done[0].table[0]["points"] == 9


def test_finish_is_idempotent_and_can_skip_renewal(store):
    season = store.start_season(1, T0, 14, renew=True)
    assert store.finish_season(season.id, T0 + 15 * DAY, None, [], renew=False) == (True, None)
    assert store.finish_season(season.id, T0 + 16 * DAY, "Кто-то", [], renew=True) == (False, None)  # второй раз — ничего
    assert store.current_season(1) is None and store.list_seasons(1)[0].champion is None
    assert store.list_seasons(1)[0].end_ts == T0 + 15 * DAY


def test_due_seasons_and_chat_migration(store):
    store.get_or_create_chat(2)
    a = store.start_season(1, T0, 7)
    store.start_season(2, T0, 30)
    assert [s.id for s in store.due_seasons(T0 + 8 * DAY)] == [a.id]
    assert store.due_seasons(T0 + DAY) == []
    store.set_chat_active(1, False)
    assert store.due_seasons(T0 + 8 * DAY) == []  # бота из чата убрали — сезон не трогаем
    store.set_chat_active(1, True)
    assert store.migrate_chat(1, -100500)
    assert store.current_season(-100500).id == a.id and store.current_season(1) is None


# --- чистые функции -----------------------------------------------------------------------

def test_dates_and_countdown(store):
    season = store.start_season(1, T0, 30)
    assert not seasons.is_due(season, T0 + 30 * DAY - 1) and seasons.is_due(season, T0 + 30 * DAY)
    assert seasons.days_left(season, T0) == 30 and seasons.days_left(season, T0 + 29 * DAY + 1) == 1
    assert seasons.days_left(season, T0 + 40 * DAY) == 0


def _done(number, table, champion):
    return type("S", (), {"number": number, "table": table, "champion": champion, "start_ts": T0, "end_ts": T0 + DAY})()


def test_hall_counts_titles_and_podium_places():
    rows = lambda *names: [{"player": n, "points": 10 - i, "golds": 1} for i, n in enumerate(names)]  # noqa: E731
    hall = seasons.hall_rows([
        _done(1, rows("Вася", "Петя", "Коля"), "Вася"),
        _done(2, rows("Петя", "Вася", "Коля"), "Петя"),
        _done(3, rows("Вася", "Коля"), "Вася"),
        _done(4, [{"player": "А", "points": 5, "golds": 1}, {"player": "Б", "points": 5, "golds": 1}], None),  # ничья — чемпиона нет
    ])
    by_name = {r["player"]: r for r in hall}
    assert (by_name["Вася"]["titles"], by_name["Вася"]["silver"], by_name["Вася"]["bronze"]) == (2, 1, 0)
    assert (by_name["Петя"]["titles"], by_name["Петя"]["silver"]) == (1, 1)
    assert by_name["Коля"]["bronze"] == 2 and by_name["Коля"]["silver"] == 1
    assert [r["player"] for r in hall][:2] == ["Вася", "Петя"]  # по числу титулов
    assert "А" not in by_name or by_name["А"]["titles"] == 0


def test_hall_text_is_empty_state_and_list():
    assert "пока пусто" in seasons.render_hall([], "UTC").lower()
    text = seasons.render_hall([_done(1, [{"player": "Вася", "points": 9, "golds": 3}], "Вася")], "UTC")
    assert "Сезон 1" in text and "Вася" in text and "🏆" in text


# --- итоги сезона ---------------------------------------------------------------------------

def test_close_season_counts_only_games_since_start_and_picks_champion(store):
    season = store.start_season(1, T0, 30)
    seed_two_players(store, T0)
    result = close_season(store, 1, season, T0 + 30 * DAY, renew=True)
    assert result["champion"]["player"] == "Вася" and result["next"].number == 2
    assert [r["player"] for r in result["table"]][:2] == ["Вася", "Петя"]
    saved = store.list_seasons(1)[0]
    assert saved.champion == "Вася" and saved.table[0]["player"] == "Вася"
    assert close_season(store, 1, season, T0 + 31 * DAY, renew=True) is None  # второй раз — уже закрыт


def test_close_season_without_games_or_players_has_no_champion(store):
    season = store.start_season(1, T0, 7)
    result = close_season(store, 1, season, T0 + 8 * DAY, renew=False)
    assert result["champion"] is None and result["next"] is None and result["table"] == []
    assert store.list_seasons(1)[0].champion is None


# --- доски ----------------------------------------------------------------------------------

def test_season_board_shows_countdown_and_card(store):
    now = int(time.time())
    store.start_season(1, now - 3 * DAY, 30)
    seed_two_players(store, now - 3 * DAY)
    board = asyncio.run(service.season_board(store, None, 1, image=True))
    assert board.png and "Сезон 1" in board.text and "осталось 27" in board.text and "Вася" in board.text
    assert "Сезон 1" in board.caption
    assert asyncio.run(service.season_board(store, None, 2)) is None  # сезона нет


def test_season_end_board_announces_champion_and_next(store):
    season = store.start_season(1, T0, 30)
    seed_two_players(store, T0)
    result = close_season(store, 1, season, T0 + 30 * DAY, renew=True)
    board = asyncio.run(service.season_end_board(store, 1, result, image=True))
    assert "Сезон 1" in board.text and "Чемпион" in board.text and "Вася" in board.text and "Сезон 2" in board.text
    assert board.png and "Вася" in board.caption


# --- автозавершение ----------------------------------------------------------------------------

class Bot:
    def __init__(self):
        self.photos, self.messages = [], []

    async def send_photo(self, chat_id, photo, caption=None, **kw):
        self.photos.append((chat_id, caption))

    async def send_message(self, chat_id, text, **kw):
        self.messages.append((chat_id, text))


def test_due_season_is_closed_announced_and_renewed(store):
    store.start_season(1, T0, 30)
    seed_two_players(store, T0)
    bot = Bot()
    closed = asyncio.run(sched.close_due_seasons(bot, store, None, T0 + 30 * DAY + 60))
    assert closed == 1
    sent = bot.photos[0][1] if bot.photos else bot.messages[0][1]
    assert "Вася" in sent and "Сезон 1" in sent
    assert store.current_season(1).number == 2 and store.list_seasons(1)[0].champion == "Вася"
    assert asyncio.run(sched.close_due_seasons(bot, store, None, T0 + 30 * DAY + 120)) == 0  # повторно не объявляем


def test_job_is_registered_and_failed_send_does_not_reopen_season(store):
    jobs = {j.func.__name__ for j in sched.setup_scheduler(Bot(), store, None).get_jobs()}
    assert "season_watch" in jobs

    class Broken(Bot):
        async def send_photo(self, *a, **kw):
            raise RuntimeError("сеть")

        async def send_message(self, *a, **kw):
            raise RuntimeError("сеть")

    store.start_season(1, T0, 30)
    asyncio.run(sched.close_due_seasons(Broken(), store, None, T0 + 31 * DAY))
    assert store.list_seasons(1)[0].end_ts is not None  # итоги сохранены и в зале славы, даже если чат не получил сообщение


# --- команды ---------------------------------------------------------------------------------------

class Message:
    def __init__(self):
        self.chat = type("Chat", (), {"id": 1, "type": "group"})()
        self.from_user = None
        self.photo = None
        self.bot = type("Bot", (), {"send_chat_action": staticmethod(lambda *a, **k: asyncio.sleep(0))})()
        self.texts, self.photos = [], []

    async def answer(self, text, **kwargs):
        self.texts.append(text)

    async def answer_photo(self, photo, caption=None, **kwargs):
        self.photos.append(caption)


def run(coro_fn, store, args):
    message = Message()
    asyncio.run(coro_fn(message, CommandObject(command="x", args=args), store, None))
    return message


def test_season_command_start_show_end(store, monkeypatch):
    store.set_chat_admin_only(1, False)
    seed_two_players(store, int(time.time()) - DAY)
    started = run(botmod.cmd_season, store, "start 14")
    assert store.current_season(1).length_days == 14 and any("Сезон 1" in t for t in started.texts)
    again = run(botmod.cmd_season, store, "start 14")
    assert "уже идёт" in again.texts[0]
    shown = run(botmod.cmd_season, store, "")
    assert shown.photos or any("Сезон 1" in t for t in shown.texts)
    ended = run(botmod.cmd_season, store, "end")
    assert store.current_season(1) is None and store.list_seasons(1)[0].number == 1
    assert ended.photos or any("Сезон 1" in t for t in ended.texts)
    nothing = run(botmod.cmd_season, store, "")
    assert "/season start" in nothing.texts[0]
    assert "нет" in run(botmod.cmd_season, store, "end").texts[0].lower()
    assert "Не понял" in run(botmod.cmd_season, store, "start 3").texts[0]


def test_season_start_and_end_are_for_admins(store, monkeypatch):
    async def deny(*a, **kw):
        return False

    monkeypatch.setattr(botmod, "may_manage", deny)
    message = run(botmod.cmd_season, store, "start 30")
    assert store.current_season(1) is None and message.texts
    store.start_season(1, T0, 30)
    run(botmod.cmd_season, store, "end")
    assert store.current_season(1) is not None  # не админ завершить не может
    assert run(botmod.cmd_season, store, "").texts or run(botmod.cmd_season, store, "").photos  # смотреть можно всем


def test_hall_command(store):
    assert "пока пусто" in run(botmod.cmd_hall, store, None).texts[0].lower()
    season = store.start_season(1, T0, 30)
    seed_two_players(store, T0)
    close_season(store, 1, season, T0 + 30 * DAY, renew=False)
    text = run(botmod.cmd_hall, store, None).texts[0]
    assert "Вася" in text and "Сезон 1" in text
