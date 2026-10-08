import importlib

from mmrbot.service import TELEGRAM_LIMIT, split_message


def test_split_short_message_single_chunk():
    assert split_message("привет") == ["привет"]


def test_split_long_message_into_multiple_chunks():
    block = "X" * 1000
    text = "\n\n".join([block] * 10)  # ~10k символов
    chunks = split_message(text)
    assert len(chunks) > 1
    assert all(len(c) <= TELEGRAM_LIMIT for c in chunks)


def test_split_hard_splits_oversized_single_block():
    # Один блок без разделителей длиннее лимита должен быть порезан, а не уйти целиком.
    text = "X" * 5000
    chunks = split_message(text, limit=4096)
    assert len(chunks) >= 2
    assert all(len(c) <= 4096 for c in chunks)
    assert "".join(chunks) == text


def test_split_preserves_all_blocks():
    blocks = [f"block-{i}" * 200 for i in range(20)]
    text = "\n\n".join(blocks)
    chunks = split_message(text)
    rejoined = "\n\n".join(chunks)
    for b in blocks:
        assert b in rejoined


def test_glue_modules_import_without_token():
    # Импорт склейки не должен требовать BOT_TOKEN (load_config вызывается только в main()).
    for name in ("mmrbot.bot", "mmrbot.scheduler", "mmrbot.service", "mmrbot.__main__"):
        importlib.import_module(name)


# --- A3: причина «данные устарели» в отчётах и подписях --------------------------------

def _store_with_player(tmp_path, updated_minutes_ago=5):
    import time
    from mmrbot.storage import Storage
    store = Storage(str(tmp_path / "n.db"))
    store.get_or_create_chat(100)
    player = store.add_player(100, 1, "Вася", 5000, 0, 0)
    now = int(time.time())
    store.add_matches(player.id, [{"match_id": 1, "start_time": now - 3600, "player_slot": 0, "radiant_win": True,
                                   "lobby_type": 7, "kills": 5, "deaths": 3, "assists": 8, "hero_id": 2, "duration": 1800}])
    store.touch_player(player.id, now - updated_minutes_ago * 60)
    return store


class _OD:
    """OpenDota с предохранителем; в down-состоянии обновление ничего не делает (как в проде после A2)."""

    def __init__(self, down):
        from mmrbot.health import ProviderHealth
        self.health = ProviderHealth("OpenDota")
        if down:
            self.health.failure(RuntimeError("down"))


def test_reports_carry_outage_note_when_opendota_is_down(tmp_path):
    import asyncio

    import mmrbot.service as service
    store = _store_with_player(tmp_path)
    od = _OD(down=True)
    for render in (service.render_board, service.render_together_board, service.render_compare_board,
                   service.render_heroes_board):
        text = asyncio.run(render(store, od, 100))
        assert "OpenDota недоступен с" in text and "показаны данные на" in text, render.__name__
        assert text.count("⚠️") == 1  # одна строка, а не две (причина + «сохранённые данные»)


def test_graph_caption_carries_outage_note(tmp_path):
    import asyncio

    import mmrbot.service as service
    store = _store_with_player(tmp_path)
    png, caption = asyncio.run(service.render_graph_board(store, _OD(down=True), 100, "all"))
    assert "OpenDota недоступен с" in caption


def test_no_outage_note_when_opendota_is_alive(tmp_path):
    import asyncio

    import mmrbot.service as service
    store = _store_with_player(tmp_path)
    text = asyncio.run(service.render_board(store, _OD(down=False), 100))
    assert "недоступен" not in text


def test_latest_match_carries_outage_note_when_opendota_is_down(tmp_path):
    import asyncio

    import mmrbot.service as service
    store = _store_with_player(tmp_path)
    board = asyncio.run(service.match_board(store, _OD(down=True), 100, None, None, image=False))
    assert "5/3/8" in board.text and "OpenDota недоступен с" in board.text
    alive = asyncio.run(service.match_board(store, _OD(down=False), 100, None, None, image=False))
    assert "недоступен" not in alive.text


def test_match_by_id_has_no_outage_note(tmp_path):
    """Матч по id — про конкретную игру, а не про «свежесть» данных: пометка ни к чему."""
    import asyncio

    import mmrbot.service as service
    store = _store_with_player(tmp_path)
    board = asyncio.run(service.match_board(store, _OD(down=True), 100, "Вася", 1, image=False))
    assert "недоступен" not in board.text
