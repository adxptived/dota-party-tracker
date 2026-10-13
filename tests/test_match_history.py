"""Матчи игрока: список (`ml:`), карточка матча (`md:`) и кнопка «🎮 Весь матч» под текстовой карточкой."""
import asyncio

import pytest

from mmrbot.keyboards import match_card_buttons, match_list_buttons, match_photo_buttons, player_actions

ACC = 1105542592


def _flat(markup):
    return [b for row in markup.inline_keyboard for b in row]


def run(coro):
    return asyncio.run(coro)


def test_player_actions_has_matches_button():
    assert "pp:matches:42" in {b.callback_data for b in _flat(player_actions(42))}


def test_match_list_buttons_are_numbers_and_paging():
    markup = match_list_buttons(ACC, offset=0, count=10, total=25)
    first = _flat(markup)
    data = [b.callback_data for b in first]
    assert [b.text for b in first[:10]] == [str(n) for n in range(1, 11)]
    assert data[:10] == [f"mv:{ACC}:0:{n}" for n in range(1, 11)]
    assert [len(row) for row in markup.inline_keyboard[:2]] == [5, 5]  # цифры — по пять в ряд
    assert f"ml:{ACC}:10" in data and not any(d == f"ml:{ACC}:-10" for d in data)  # назад с первой страницы нет
    mid = {b.callback_data for b in _flat(match_list_buttons(ACC, offset=10, count=10, total=25))}
    assert {f"ml:{ACC}:0", f"ml:{ACC}:20"} <= mid
    last = {b.callback_data for b in _flat(match_list_buttons(ACC, offset=20, count=5, total=25))}
    assert f"ml:{ACC}:10" in last and f"ml:{ACC}:30" not in last and f"mv:{ACC}:20:6" not in last
    assert all(len((d or "").encode()) <= 64 for d in data)


def test_open_match_is_marked_and_has_list_text_and_dotabuff():
    buttons = _flat(match_list_buttons(ACC, offset=10, count=10, total=25, current=3, match_id=9100000007))
    assert buttons[2].text == "• 3" and buttons[0].text == "1"
    data = {b.callback_data for b in buttons}
    assert f"ml:{ACC}:10" in data and f"tx:match:9100000007:{ACC}" in data
    assert any(b.url == "https://www.dotabuff.com/matches/9100000007" for b in buttons)


def test_match_card_buttons_full_match_dotabuff_back():
    buttons = _flat(match_card_buttons(ACC, 9100000007, 10))
    data = [b.callback_data for b in buttons]
    assert f"mx:9100000007:{ACC}" in data and f"ml:{ACC}:10" in data
    assert any(b.url == "https://www.dotabuff.com/matches/9100000007" for b in buttons)


def test_text_card_gets_full_match_button():
    with_full = _flat(match_photo_buttons(9100000007, ACC, text_shown=True, full=True))
    assert f"mx:9100000007:{ACC}" in {b.callback_data for b in with_full}
    plain = _flat(match_photo_buttons(9100000007, ACC))
    assert not any((b.callback_data or "").startswith("mx:") for b in plain)


@pytest.fixture
def e2e():
    pytest.importorskip("aiogram.filters")
    from tests import test_e2e_commands as mod
    return mod


def _env(e2e, tmp_path):
    from mmrbot.storage import Storage
    storage = Storage(str(tmp_path / "t.db"))
    storage.get_or_create_chat(100)
    storage.add_player(100, e2e.ACC, "shinoame", 5000, 0, 0)
    player = storage.get_player(100, "shinoame")
    storage.add_matches(player.id, [
        {"match_id": mid, "start_time": e2e.NOW - h * 3600, "player_slot": 0, "radiant_win": win, "lobby_type": 7,
         "kills": k, "deaths": d, "assists": a, "hero_id": hero, "duration": mins * 60}
        for mid, h, hero, k, d, a, win, mins, _p, _i in e2e.GAMES
    ])
    return storage, e2e.FakeOD(), e2e.FakeStratz()


def test_matches_button_shows_picture_list_and_numbers_open_matches(e2e, tmp_path):
    import mmrbot.bot as botmod
    storage, od, sz = _env(e2e, tmp_path)

    cb = e2e.FakeCallback(f"pp:matches:{e2e.ACC}")
    run(botmod.on_callback(cb, storage, od, sz))
    (caption, kw), = cb.message.photos
    assert "shinoame" in caption and "1–7 из 7" in caption
    data = [b.callback_data for b in _flat(kw["reply_markup"])]
    assert data[:7] == [f"mv:{e2e.ACC}:0:{n}" for n in range(1, 8)]

    cb = e2e.FakeCallback(f"mv:{e2e.ACC}:0:1")  # «1» — самый свежий матч
    run(botmod.on_callback(cb, storage, od, sz))
    (_, kw), = cb.message.photos
    buttons = _flat(kw["reply_markup"])
    assert buttons[0].text == "• 1" and sz.full_requests == [9100000007]
    assert f"ml:{e2e.ACC}:0" in {b.callback_data for b in buttons}

    cb = e2e.FakeCallback(f"mv:{e2e.ACC}:0:3")  # переключились на третий
    run(botmod.on_callback(cb, storage, od, sz))
    assert sz.full_requests == [9100000007, 9100000005]
    cb = e2e.FakeCallback(f"mv:{e2e.ACC}:0:9")  # такого номера на странице нет
    run(botmod.on_callback(cb, storage, od, sz))
    assert sz.full_requests == [9100000007, 9100000005]


def test_old_match_card_buttons_still_work(e2e, tmp_path):
    import mmrbot.bot as botmod
    storage, od, sz = _env(e2e, tmp_path)

    cb = e2e.FakeCallback(f"md:{e2e.ACC}:9100000007:0")
    run(botmod.on_callback(cb, storage, od, sz))
    text, kwargs = cb.message.sent[-1]
    assert "9100000007" in text and "13/3/10" in text
    assert f"mx:9100000007:{e2e.ACC}" in {b.callback_data for b in _flat(kwargs["reply_markup"])}

    cb = e2e.FakeCallback(f"ml:{e2e.ACC}:0")
    run(botmod.on_callback(cb, storage, od, sz))
    assert cb.message.sent

    cb = e2e.FakeCallback(f"mx:9100000007:{e2e.ACC}")
    run(botmod.on_callback(cb, storage, od, sz))
    assert len(cb.message.photos) == 1
    assert sz.full_requests == [9100000007]


def test_garbage_match_callbacks_are_ignored(e2e, tmp_path):
    import mmrbot.bot as botmod
    storage, od, sz = _env(e2e, tmp_path)
    for data in ("md:abc:1:0", "md:1", f"ml:{e2e.ACC}:x", "ml:999:0", f"md:{e2e.ACC}:5:0", "mv:1", f"mv:{e2e.ACC}:0:x",
                 "mv:999:0:1", f"mv:{e2e.ACC}:0:0"):
        cb = e2e.FakeCallback(data)
        run(botmod.on_callback(cb, storage, od, sz))


# --- матч не нашёлся в Stratz — берём OpenDota ---------------------------------------------------

OD_MATCH = {
    "match_id": 9042274894, "start_time": 1760000000, "duration": 2100, "radiant_win": True,
    "players": [
        {"account_id": 555, "personaname": "Вася", "player_slot": 0, "hero_id": 1, "kills": 5, "deaths": 2,
         "assists": 9, "gold_per_min": 600, "xp_per_min": 700, "net_worth": 20000, "hero_damage": 25000,
         "tower_damage": 1500, "hero_healing": 0, "last_hits": 250, "denies": 8, "level": 25},
        {"account_id": None, "player_slot": 128, "hero_id": 2, "kills": 1, "deaths": 7, "assists": 3},
    ],
}


def test_opendota_match_converts_to_stratz_format():
    from mmrbot.opendota import match_from_opendota
    match = match_from_opendota(OD_MATCH)
    assert match["match_id"] == 9042274894 and match["radiant_win"] is True and match["duration"] == 2100
    me, enemy = match["players"]
    assert (me["account_id"], me["name"], me["is_radiant"], me["hero_id"]) == (555, "Вася", True, 1)
    assert (me["kills"], me["gpm"], me["xpm"], me["last_hits"], me["hero_damage"]) == (5, 600, 700, 250, 25000)
    assert enemy["is_radiant"] is False and enemy["account_id"] is None
    assert match_from_opendota({}) is None and match_from_opendota({"players": []}) is None


class _OnlyOD:
    def get_match(self, match_id):
        return OD_MATCH if match_id == 9042274894 else {}

    def get_match_builds(self, match_id):
        return {}


class _EmptyStratz:
    def get_match(self, match_id):
        return None


def test_match_falls_back_to_opendota_when_stratz_has_nothing(e2e, tmp_path):
    from mmrbot.service import match_board
    storage, _od, _sz = _env(e2e, tmp_path)
    board = run(match_board(storage, _OnlyOD(), 100, None, 9042274894, _EmptyStratz(), image=False))
    assert "не найден" not in board.text and "Вася" in board.text and "5/2/9" in board.text
    gone = run(match_board(storage, _OnlyOD(), 100, None, 1, _EmptyStratz(), image=False))
    assert "Stratz" in gone.text and "OpenDota" in gone.text


def test_match_works_with_opendota_alone(e2e, tmp_path):
    from mmrbot.service import match_board
    storage, _od, _sz = _env(e2e, tmp_path)
    board = run(match_board(storage, _OnlyOD(), 100, None, 9042274894, None, image=False))
    assert "Вася" in board.text


def test_match_list_image_renders_rows_and_empty_page(drawn):
    import io

    from PIL import Image

    from mmrbot.cards import WIDTH
    from mmrbot.match_list_image import render_match_list_image
    rows = [{"n": i, "hero_id": 11, "name": "Shadow Fiend", "won": i % 2 == 0, "kills": 1, "deaths": 2, "assists": 3,
             "delta": 25, "double_down": i == 2, "minutes": 40, "when": "12.10 21:50", "extra": "295 крипов",
             "current": i == 3} for i in range(1, 11)]
    full = Image.open(io.BytesIO(render_match_list_image("Матчи · Вася", "1–10 из 56", rows, {11: b"junk"})))
    empty = Image.open(io.BytesIO(render_match_list_image("Матчи · Вася", None, [])))
    assert full.width == empty.width == WIDTH and full.height > empty.height + 9 * 80
    texts = [t[0] for t in drawn]
    numbers = [texts[i - 1] for i, t in enumerate(texts) if t == "Shadow Fiend"]  # номер рисуется перед героем
    assert numbers == [str(n) for n in range(1, 11)]
    assert "12.10 21:50  ·  40 мин  ·  295 крипов" in texts
