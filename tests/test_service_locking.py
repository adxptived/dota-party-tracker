import asyncio
import threading
import time

from mmrbot import service


class _Store:
    """Хранилище-пустышка: refresh_for смотрит, есть ли ни разу не загруженные игроки."""

    def list_players(self, chat_id):
        return []


def _spy(monkeypatch):
    state = {"running": 0, "max": 0}
    guard = threading.Lock()

    def fake_refresh(storage, od, chat_id, now, stratz=None, players=None, fast=False, max_age=None):
        with guard:
            state["running"] += 1
            state["max"] = max(state["max"], state["running"])
        time.sleep(0.05)
        with guard:
            state["running"] -= 1
        return []

    monkeypatch.setattr(service, "refresh_chat", fake_refresh)  # обновление идёт под локом чата
    monkeypatch.setattr(service, "build_leaderboard", lambda *a, **kw: [])  # сборка сводок — из БД
    return state


def test_same_chat_refreshes_are_serialized(monkeypatch):
    state = _spy(monkeypatch)

    async def go():
        await asyncio.gather(*(service.gather_summaries(_Store(), None, 1) for _ in range(3)))

    asyncio.run(go())
    assert state["max"] == 1


def test_different_chats_run_in_parallel(monkeypatch):
    state = _spy(monkeypatch)

    async def go():
        await asyncio.gather(service.gather_summaries(_Store(), None, 1), service.gather_summaries(_Store(), None, 2))

    asyncio.run(go())
    assert state["max"] == 2


def test_match_board_escapes_names_in_empty_message(tmp_path):
    from mmrbot.storage import Storage

    store = Storage(str(tmp_path / "e.db"))
    store.add_player(100, 1, "<b>Вася", 5000, 0, 0)  # матчей нет
    text = asyncio.run(service.render_match_board(store, _NoRefresh(), 100, None, None))
    assert "<b>Вася" not in text and "&lt;b&gt;Вася" in text


def test_latest_match_does_not_wait_for_slow_refresh(tmp_path, monkeypatch):
    """OpenDota тормозит — «последний матч» отвечает из БД через MATCH_REFRESH_WAIT, обновление идёт фоном."""
    from mmrbot.storage import Storage

    store = Storage(str(tmp_path / "s.db"))
    player = store.add_player(100, 1, "Вася", 5000, 0, 0)
    store.add_matches(player.id, [{"match_id": 77, "start_time": 1_700_000_000, "player_slot": 0,
                                      "radiant_win": True, "lobby_type": 7, "kills": 9, "deaths": 2,
                                      "assists": 4, "hero_id": 2, "duration": 1800}])
    finished = []

    async def slow_refresh(*a, **k):
        await asyncio.sleep(0.5)
        finished.append(True)

    monkeypatch.setattr(service, "refresh_only", slow_refresh)
    monkeypatch.setattr(service, "MATCH_REFRESH_WAIT", 0.05)

    async def go():
        started = time.monotonic()
        board = await service.match_board(store, None, 100, None, None, image=False)
        elapsed = time.monotonic() - started
        await asyncio.sleep(0.6)  # фоновое обновление не отменено — доходит до конца
        return board, elapsed

    board, elapsed = asyncio.run(go())
    assert elapsed < 0.4 and "9/2/4" in board.text
    assert finished == [True]


class _NoRefresh:
    pass


# --- A4: бюджет ожидания обновления для всех команд ---------------------------------------

def _seeded_store(tmp_path):
    """Игрок с историей и якорем MMR: хватает и для рейтинга, и для карточки, и для графика."""
    import time as _t
    from mmrbot.storage import Storage

    store = Storage(str(tmp_path / "b.db"))
    store.get_or_create_chat(100)
    player = store.add_player(100, 1, "Вася", 5000, 0, 0)
    now = int(_t.time())
    store.add_matches(player.id, [
        {"match_id": 70 + i, "start_time": now - 3600 * (i + 1), "player_slot": 0, "radiant_win": bool(i % 2),
         "lobby_type": 7, "kills": 5, "deaths": 3, "assists": 8, "hero_id": 2, "duration": 1800}
        for i in range(4)
    ])
    return store


def _slow_refresh(monkeypatch, finished, delay=0.5, budget=0.05):
    async def slow(*a, **k):
        await asyncio.sleep(delay)
        finished.append(True)

    monkeypatch.setattr(service, "refresh_only", slow)
    monkeypatch.setattr(service, "COMMAND_REFRESH_WAIT", budget)


def _assert_fast_and_background_completes(coro_factory, finished, check):
    async def go():
        started = time.monotonic()
        result = await coro_factory()
        elapsed = time.monotonic() - started
        await asyncio.sleep(0.6)  # фоновое обновление не отменено — доходит до конца
        return result, elapsed

    result, elapsed = asyncio.run(go())
    assert elapsed < 0.4, f"команда ждала обновление {elapsed:.2f} с"
    check(result)
    assert finished == [True]


def test_render_board_answers_within_budget_from_db(tmp_path, monkeypatch):
    store, finished = _seeded_store(tmp_path), []
    _slow_refresh(monkeypatch, finished)
    _assert_fast_and_background_completes(
        lambda: service.render_board(store, None, 100), finished, lambda text: "Вася" in text)


def test_render_player_board_answers_within_budget_from_db(tmp_path, monkeypatch):
    store, finished = _seeded_store(tmp_path), []
    _slow_refresh(monkeypatch, finished)
    _assert_fast_and_background_completes(
        lambda: service.render_player_board(store, None, 100, "Вася"), finished, lambda text: "Вася" in text)


def test_render_graph_board_answers_within_budget_from_db(tmp_path, monkeypatch):
    from mmrbot.charts import warmup
    warmup()  # как при старте бота: холодный рендер matplotlib (~0.6 с) — не время ожидания обновления
    store, finished = _seeded_store(tmp_path), []
    _slow_refresh(monkeypatch, finished)
    _assert_fast_and_background_completes(
        lambda: service.render_graph_board(store, None, 100, "all"), finished,
        lambda result: result is not None and result[0][:4] == b"\x89PNG")


def test_other_commands_also_use_the_budget(tmp_path, monkeypatch):
    store, finished = _seeded_store(tmp_path), []
    _slow_refresh(monkeypatch, finished, delay=0.3)

    async def go():
        started = time.monotonic()
        await service.render_period_board(store, None, 100, "week")
        await service.render_records_board(store, None, 100, "week")
        await service.render_together_board(store, None, 100)
        await service.render_player_heroes_board(store, None, 100, "Вася", "all")
        await service.render_roles_board(store, None, 100, "Вася")
        await service.render_hero_board(store, None, 100, "Axe", "all")
        await service.render_heroes_board(store, None, 100)
        await service.render_compare_board(store, None, 100)
        return time.monotonic() - started

    assert asyncio.run(go()) < 1.0   # 8 команд по бюджету 0.05 с, а не по 0.3 с обновления каждая


def test_refresh_within_budget_is_awaited_and_errors_propagate(tmp_path, monkeypatch):
    done = []

    async def quick(*a, **k):
        done.append(True)

    monkeypatch.setattr(service, "refresh_only", quick)
    assert asyncio.run(service.refresh_with_budget(None, None, 1, budget=1.0)) is True
    assert done == [True]

    async def broken(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "refresh_only", broken)
    try:
        asyncio.run(service.refresh_with_budget(None, None, 1, budget=1.0))
        assert False, "ошибка обновления должна подняться"
    except RuntimeError:
        pass


def test_refresh_over_budget_returns_false_and_keeps_running(monkeypatch):
    finished = []
    _slow_refresh(monkeypatch, finished, delay=0.2, budget=0.02)

    async def go():
        ok = await service.refresh_with_budget(None, None, 1)
        await asyncio.sleep(0.3)
        return ok

    assert asyncio.run(go()) is False and finished == [True]


def test_zero_budget_never_waits(monkeypatch):
    finished = []
    _slow_refresh(monkeypatch, finished, delay=0.2, budget=0.0)

    async def go():
        started = time.monotonic()
        await service.refresh_with_budget(None, None, 1)
        elapsed = time.monotonic() - started
        await asyncio.sleep(0.3)
        return elapsed

    assert asyncio.run(go()) < 0.1 and finished == [True]


# --- B1: «достаточно свежие» данные — из БД без сети; медленное догоняется фоном -----------

class _CountingOD:
    """Фейковый клиент: считает обращения; get_matches можно замедлить."""

    def __init__(self, delay=0.0):
        self.delay = delay
        self.match_calls = 0
        self.profile_calls = 0

    def refresh(self, account_id):
        return True

    def get_profile(self, account_id):
        self.profile_calls += 1
        return {"rank_tier": 80, "leaderboard_rank": None, "personaname": "Вася"}

    def get_matches(self, account_id, limit=200):
        time.sleep(self.delay)
        self.match_calls += 1
        return []

    def get_match_player_stats(self, match_id, account_id, player_slot=None):
        return None


def _aged_store(tmp_path, minutes_ago):
    store = _seeded_store(tmp_path)
    player = store.get_player(100, "Вася")
    store.touch_player(player.id, int(time.time()) - minutes_ago * 60)
    return store


def test_fresh_enough_data_is_served_without_touching_the_network(tmp_path):
    store, od = _aged_store(tmp_path, 8), _CountingOD()   # 8 мин < FRESH_ENOUGH (10) — но дольше старого кулдауна в 3
    for render in (service.render_board, service.render_compare_board, service.render_heroes_board,
                   service.render_together_board):
        text = asyncio.run(render(store, od, 100))
        assert "OpenDota не ответил" not in text and "недоступен" not in text
    assert (od.match_calls, od.profile_calls) == (0, 0)


def test_stale_data_for_stats_waits_for_refresh_within_budget(tmp_path):
    store, od = _aged_store(tmp_path, 15), _CountingOD(delay=0.3)

    async def go():
        started = time.monotonic()
        await service.render_board(store, od, 100)
        return time.monotonic() - started

    assert asyncio.run(go()) >= 0.3 and od.match_calls == 1   # рейтинг ждёт свежую игру


def test_stale_data_for_heroes_is_answered_at_once_and_refreshed_in_background(tmp_path):
    store, od = _aged_store(tmp_path, 15), _CountingOD(delay=0.3)

    async def go():
        started = time.monotonic()
        texts = [
            await service.render_heroes_board(store, od, 100),
            await service.render_player_heroes_board(store, od, 100, "Вася", "all"),
            await service.render_roles_board(store, od, 100, "Вася"),
            await service.render_hero_board(store, od, 100, "Axe", "all"),
        ]
        elapsed = time.monotonic() - started
        await asyncio.sleep(0.6)  # фон доезжает
        return texts, elapsed

    texts, elapsed = asyncio.run(go())
    assert elapsed < 0.25 and all(texts)          # новые 1–2 игры картину героев не меняют — не ждём
    assert od.match_calls >= 1                    # но обновление запущено и дошло


def test_never_loaded_player_always_waits_for_first_load(tmp_path):
    from mmrbot.storage import Storage
    store = Storage(str(tmp_path / "new.db"))
    store.get_or_create_chat(100)
    store.add_player(100, 1, "Вася", 5000, 0, 0)   # updated_ts is None
    od = _CountingOD(delay=0.2)
    asyncio.run(service.render_player_heroes_board(store, od, 100, "Вася", "all"))
    assert od.match_calls == 1                     # пустой экран вместо данных — хуже короткого ожидания


def test_fresh_enough_boundary_is_ten_minutes():
    from mmrbot.tracker import FRESH_ENOUGH, REFRESH_COOLDOWN
    assert FRESH_ENOUGH == 600 and FRESH_ENOUGH > REFRESH_COOLDOWN
