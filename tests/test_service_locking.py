import asyncio
import threading
import time

from mmrbot import service


def _spy(monkeypatch):
    state = {"running": 0, "max": 0}
    guard = threading.Lock()

    def fake_build(storage, od, chat_id, now, refresh, stratz, fast=False):
        with guard:
            state["running"] += 1
            state["max"] = max(state["max"], state["running"])
        time.sleep(0.05)
        with guard:
            state["running"] -= 1
        return []

    monkeypatch.setattr(service, "build_leaderboard", fake_build)
    return state


def test_same_chat_refreshes_are_serialized(monkeypatch):
    state = _spy(monkeypatch)

    async def go():
        await asyncio.gather(*(service.gather_summaries(None, None, 1) for _ in range(3)))

    asyncio.run(go())
    assert state["max"] == 1


def test_different_chats_run_in_parallel(monkeypatch):
    state = _spy(monkeypatch)

    async def go():
        await asyncio.gather(service.gather_summaries(None, None, 1), service.gather_summaries(None, None, 2))

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
