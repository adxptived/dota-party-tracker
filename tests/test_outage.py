"""«OpenDota лёг»: бот отвечает из БД быстро и честно, фон молчит, после оживления данные обновляются.

Клиент — настоящий OpenDota (с предохранителем) поверх сессии, которая падает по ConnectTimeout; сеть не трогаем.
Слой 1 (сервис, трекер, планировщик) работает без aiogram-хендлеров; слой 2 (хендлеры и кнопки из
test_e2e_commands) пропускается, если aiogram-фильтров нет.
"""
import asyncio
import logging
import time

import pytest
import requests

import mmrbot.service as service
from mmrbot import scheduler as sched
from mmrbot.health import ProviderHealth
from mmrbot.opendota import OpenDota
from mmrbot.storage import Storage
from mmrbot.stratz import Stratz

NOW = int(time.time())
NOTE = "OpenDota недоступен с"


class Clock:
    """Фейковые часы предохранителя: «оживление» — сдвиг времени, а не sleep."""

    def __init__(self):
        self.now = 1000.0

    def mono(self):
        return self.now

    def wall(self):
        return time.time() + (self.now - 1000.0)


class FlakySession:
    """GET/POST падают по connect timeout, пока down=True; потом отдают данные. Считает обращения."""

    def __init__(self, down=True, matches=None):
        self.down = down
        self.matches = matches or []
        self.gets = 0
        self.posts = 0

    def get(self, url, params=None, timeout=None, headers=None):
        self.gets += 1
        if self.down:
            raise requests.exceptions.ConnectTimeout("connect timeout")
        resp = requests.Response()
        resp.status_code = 200
        if url.endswith("/matches") or url.endswith("/recentMatches"):
            resp._content = _json(self.matches)
        elif "/players/" in url:
            resp._content = _json({"rank_tier": 80, "profile": {"personaname": "Вася"}})
        else:
            resp._content = _json([])
        return resp

    @property
    def attempts(self):
        """Все обращения к сети (GET и POST /refresh): предохранитель считает любую пробу."""
        return self.gets + self.posts

    def post(self, url, timeout=None, headers=None):
        self.posts += 1
        if self.down:
            raise requests.exceptions.ConnectTimeout("connect timeout")
        resp = requests.Response()
        resp.status_code = 200
        return resp


def _json(payload):
    import json
    return json.dumps(payload).encode()


def _match(match_id, hours_ago, hero=2, win=True):
    return {"match_id": match_id, "start_time": NOW - hours_ago * 3600, "player_slot": 0, "radiant_win": win,
            "lobby_type": 7, "kills": 5, "deaths": 3, "assists": 8, "hero_id": hero, "duration": 1800}


def _seed(storage, names=("Вася",)):
    """Игроки с историей: обновлялись 15 минут назад (старше FRESH_ENOUGH — команда захочет в сеть)."""
    storage.get_or_create_chat(100)
    players = []
    for n, name in enumerate(names):
        player = storage.add_player(100, 1 + n, name, 5000, 0, 0)
        storage.add_matches(player.id, [_match(100 * (n + 1) + i, i + 1, win=bool(i % 2)) for i in range(4)])
        storage.touch_player(player.id, NOW - 900)
        storage.mark_notified(player.id)
        players.append(player)
    return players


def _client(session, clock=None):
    clock = clock or Clock()
    health = ProviderHealth("OpenDota", clock=clock.mono, wall=clock.wall)
    return OpenDota(session=session, min_interval=0, health=health), clock


@pytest.fixture
def store(tmp_path):
    return Storage(str(tmp_path / "outage.db"))


def run(coro):
    return asyncio.run(coro)


# --- слой 1: сервис ---------------------------------------------------------------------

def _all_boards(store, od):
    """Каждый отчёт сервиса → (имя, текст). Графику и картинке матча — подпись."""
    out = [
        ("stats", run(service.render_board(store, od, 100))),
        ("today", run(service.render_board(store, od, 100, today_only=True))),
        ("period", run(service.render_period_board(store, od, 100, "week"))),
        ("records", run(service.render_records_board(store, od, 100, "week"))),
        ("together", run(service.render_together_board(store, od, 100))),
        ("compare", run(service.render_compare_board(store, od, 100))),
        ("heroes", run(service.render_heroes_board(store, od, 100))),
        ("player", run(service.render_player_board(store, od, 100, "Вася"))),
        ("player_heroes", run(service.render_player_heroes_board(store, od, 100, "Вася", "all"))),
        ("roles", run(service.render_roles_board(store, od, 100, "Вася"))),
        ("hero", run(service.render_hero_board(store, od, 100, "Axe", "all"))),
        ("match_text", run(service.render_match_board(store, od, 100, None, None))),
    ]
    graph = run(service.render_graph_board(store, od, 100, "all"))
    assert graph is not None and graph[0][:4] == b"\x89PNG"
    out.append(("graph_caption", graph[1]))
    board = run(service.match_board(store, od, 100, None, None))
    out.append(("match_caption", board.caption or board.text))
    return out


def test_every_report_answers_from_db_with_note_and_one_network_attempt(store):
    _seed(store)
    session = FlakySession(down=True)
    od, _ = _client(session)
    started = time.monotonic()
    boards = _all_boards(store, od)
    assert time.monotonic() - started < 5          # никто не ждёт сетевых таймаутов
    for name, text in boards:
        assert "Не удалось" not in text and "не удалось" not in text.lower(), name
        assert "Traceback" not in text, name
        assert NOTE in text and "показаны данные на" in text, name   # причина названа, а не «OpenDota не ответил»
        assert text.count("⚠️") <= 2, name
    assert session.gets == 1                        # ровно одна попытка за всю паузу предохранителя
    assert session.posts == 0


def test_reports_show_real_data_not_empty_placeholders(store):
    _seed(store)
    od, _ = _client(FlakySession(down=True))
    boards = dict(_all_boards(store, od))
    assert "Вася" in boards["stats"] and "Вася" in boards["player"] and "Axe" in boards["hero"]
    assert "5/3/8" in boards["match_text"]


def test_parallel_refresh_of_many_players_makes_at_most_one_attempt_each_then_none(store):
    names = ("А", "Б", "В", "Г")
    _seed(store, names)
    session = FlakySession(down=True)
    od, _ = _client(session)
    run(service.render_board(store, od, 100))
    first_wave = session.gets
    assert 1 <= first_wave <= len(names)            # игроки идут параллельно: до первого отказа успевают все
    run(service.render_board(store, od, 100))
    run(service.render_compare_board(store, od, 100))
    assert session.gets == first_wave               # дальше, пока пауза, в сеть не ходят


def test_outage_log_is_short_without_tracebacks(store, caplog):
    _seed(store, ("А", "Б", "В", "Г"))
    od, _ = _client(FlakySession(down=True))
    with caplog.at_level(logging.DEBUG):
        _all_boards(store, od)
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [r.name for r in warnings].count("mmrbot.health") == 1      # одна строка о падении
    assert len(warnings) <= 3
    assert all(r.exc_info is None for r in caplog.records) and "Traceback" not in caplog.text


def test_after_revival_data_updates_and_note_disappears(store):
    _seed(store)
    session = FlakySession(down=True, matches=[_match(900, 0), _match(100, 1)])
    od, clock = _client(session)
    assert NOTE in run(service.render_board(store, od, 100))
    gets_down = session.gets
    clock.now += 61                                 # пауза кончилась
    session.down = False
    storage_player = store.get_player(100, "Вася")
    store.touch_player(storage_player.id, NOW - 900)  # данные снова «старые» — команда идёт в сеть
    text = run(service.render_board(store, od, 100))
    assert session.gets > gets_down                 # пробная попытка прошла
    assert od.health.status()["state"] == "up"
    assert NOTE not in text
    assert 900 in {m["match_id"] for m in store.get_matches(storage_player.id)}   # новая игра подтянута


# --- слой 1: трекер и фон -----------------------------------------------------------------

def test_background_tracker_jobs_are_silent_and_make_no_requests_during_pause(store, caplog):
    from mmrbot.tracker import (
        backfill_opendota, backfill_stratz, detect_new_games, detect_steam_changes, finish_refresh,
    )
    _seed(store)
    session = FlakySession(down=True)
    od, _ = _client(session)
    # Stratz тоже лежит
    class DownStratzSession:
        posts = 0

        def post(self, *a, **kw):
            DownStratzSession.posts += 1
            raise requests.exceptions.ConnectTimeout("connect timeout")

    stratz = Stratz("k", session=DownStratzSession(), min_interval=0, retry_sleep=0)
    chat = store.get_or_create_chat(100)
    with caplog.at_level(logging.DEBUG):
        detect_new_games(store, od, chat, NOW, stratz)          # одна попытка пробы — и пауза
        attempts_after_probe = session.attempts
        detect_new_games(store, od, chat, NOW + 1000, stratz)
        backfill_opendota(store, od)
        finish_refresh(store, od, 100)
        assert detect_steam_changes(store, od) == []
        backfill_stratz(store, stratz)
    assert session.attempts == attempts_after_probe == 1    # всё остальное — без обращений к сети
    assert DownStratzSession.posts <= 1
    assert all(r.exc_info is None for r in caplog.records) and "Traceback" not in caplog.text


class _Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)


def _scheduler_jobs(store, od, stratz=None, bot=None):
    scheduler = sched.setup_scheduler(bot or _Bot(), store, od, stratz=stratz)
    return scheduler, {job.func.__name__: job.func for job in scheduler.get_jobs()}


def test_scheduler_jobs_survive_outage_without_tracebacks(store, caplog):
    _seed(store)
    session = FlakySession(down=True)
    od, _ = _client(session)
    stratz = Stratz("k", session=type("S", (), {"post": lambda *a, **k: (_ for _ in ()).throw(
        requests.exceptions.ConnectTimeout("x"))})(), min_interval=0, retry_sleep=0)
    bot = _Bot()
    scheduler, jobs = _scheduler_jobs(store, od, stratz, bot)
    with caplog.at_level(logging.DEBUG):
        for name in ("game_watch", "opendota_backfill", "stratz_backfill", "steam_watch", "heroes_refresh"):
            run(jobs[name]())                        # ни одна задача не падает
            run(jobs[name]())                        # и повторный тик в паузу тоже
    assert session.attempts <= 1
    assert all(r.exc_info is None for r in caplog.records) and "Traceback" not in caplog.text
    assert any(j.id == "heroes_retry" for j in scheduler.get_jobs())


def test_digest_is_sent_from_db_with_outage_note(store):
    players = _seed(store)
    od, _ = _client(FlakySession(down=True))
    bot = _Bot()
    chat = store.get_or_create_chat(100)
    run(sched.send_digest(bot, store, od, chat, "2026-10-08"))
    assert bot.sent and NOTE in "\n".join(bot.sent)
    assert store.get_or_create_chat(100).last_digest_date == "2026-10-08"
    assert players


# --- слой 2: хендлеры и кнопки (харнесс test_e2e_commands; нужен настоящий aiogram) ---------

DATA_BUTTONS = ["m:stats", "m:today", "m:week", "m:month", "m:compare", "m:together", "m:match", "m:heroes",
                "pp:heroes:1105542592", "pp:player:1105542592",
                "hp:1105542592:day", "hp:1105542592:week", "hp:1105542592:month", "hp:1105542592:all"]
STATIC_BUTTONS = ["m:menu", "m:help", "m:list", "m:player"]


@pytest.fixture
def e2e():
    pytest.importorskip("aiogram.filters")
    from tests import test_e2e_commands as e2e_mod
    return e2e_mod


@pytest.fixture
def outage_env(tmp_path, e2e):
    storage = Storage(str(tmp_path / "e2e-outage.db"))
    storage.get_or_create_chat(100)
    player = storage.add_player(100, e2e.ACC, "shinoame", 5000, 0, 0)
    storage.add_matches(player.id, [
        {"match_id": mid, "start_time": NOW - h * 3600, "player_slot": 0, "radiant_win": win, "lobby_type": 7,
         "kills": k, "deaths": d, "assists": a, "hero_id": hero, "duration": mins * 60, "party_size": 1,
         "average_rank": 80, "position": pos, "imp": imp}
        for mid, h, hero, k, d, a, win, mins, pos, imp in e2e.GAMES
    ])
    storage.touch_player(player.id, NOW - 900)
    storage.mark_notified(player.id)
    session = FlakySession(down=True)
    od, _ = _client(session)
    return storage, od, e2e.FakeStratz(), session


def test_every_command_answers_from_db_while_opendota_is_down(e2e, outage_env):
    import mmrbot.bot as botmod
    storage, od, stratz, session = outage_env
    for handler, name, args in (
        (botmod.cmd_stats, "stats", None), (botmod.cmd_stats, "stats", "сегодня"),
        (botmod.cmd_heroes, "heroes", None), (botmod.cmd_heroes, "heroes", "shinoame"),
        (botmod.cmd_heroes, "heroes", "Kez"), (botmod.cmd_match, "match", None),
        (botmod.cmd_player, "player", "shinoame"),
    ):
        msg = e2e.FakeMessage()
        run(handler(msg, e2e.cmdobj(name, args), storage, od, stratz))
        e2e.assert_ok(msg)
    for handler in (botmod.cmd_compare, botmod.cmd_together):
        msg = e2e.FakeMessage()
        run(handler(msg, storage, od, stratz))
        e2e.assert_ok(msg)
    assert session.gets <= 1


def test_stats_and_match_carry_outage_note(e2e, outage_env):
    import mmrbot.bot as botmod
    storage, od, stratz, _ = outage_env
    for handler, name in ((botmod.cmd_stats, "stats"), (botmod.cmd_match, "match")):
        msg = e2e.FakeMessage()
        run(handler(msg, e2e.cmdobj(name, None), storage, od, stratz))
        assert NOTE in msg.texts, name


@pytest.mark.parametrize("data", DATA_BUTTONS + STATIC_BUTTONS)
def test_every_button_works_while_opendota_is_down(e2e, outage_env, data):
    import mmrbot.bot as botmod
    storage, od, stratz, session = outage_env
    cb = e2e.FakeCallback(data)
    run(botmod.on_callback(cb, storage, od, stratz))
    e2e.assert_ok(cb.message)
    assert session.gets <= 1


@pytest.mark.parametrize("data", ["m:stats", "m:week", "m:compare", "m:together", "m:match", "pp:player:1105542592"])
def test_data_buttons_carry_outage_note(e2e, outage_env, data):
    import mmrbot.bot as botmod
    storage, od, stratz, _ = outage_env
    cb = e2e.FakeCallback(data)
    run(botmod.on_callback(cb, storage, od, stratz))
    assert NOTE in cb.message.texts


def test_match_text_button_works_while_opendota_is_down(e2e, outage_env):
    import mmrbot.bot as botmod
    storage, od, stratz, _ = outage_env
    msg = e2e.FakeMessage()
    run(botmod.cmd_match(msg, e2e.cmdobj("match", None), storage, od, stratz))
    text = e2e._text_button(msg, (storage, od, stratz)).texts
    assert "Radiant" in text and "13/3/10" in text
