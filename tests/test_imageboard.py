"""Слой картинок: кнопка «📝 Текстом» (tx:), фоллбек в текст, правка картинки на месте."""
import asyncio

import pytest

from mmrbot.boards import ImageBoard, MatchBoard, build_png, fit_caption
from mmrbot.keyboards import (match_photo_buttons, nav_menu, text_button, with_text_button, without_text_button)


def _flat(markup):
    return [b for row in markup.inline_keyboard for b in row]


def _data(markup):
    return [b.callback_data for b in _flat(markup)]


# --- кнопки -------------------------------------------------------------------------------------

def test_text_button_format_and_size_limit():
    button = text_button("match", 7812345678, 1105542592)
    assert button.callback_data == "tx:match:7812345678:1105542592" and "Текстом" in button.text
    assert text_button("stats", "week").callback_data == "tx:stats:week"
    with pytest.raises(ValueError):
        text_button("x", "я" * 40)  # >64 байт — Telegram отклонит кнопку


def test_with_text_button_goes_before_nav_row():
    markup = with_text_button(nav_menu(), "stats", "week")
    rows = markup.inline_keyboard
    assert rows[0][0].callback_data == "tx:stats:week"
    assert [b.callback_data for b in rows[-1]] == [b.callback_data for b in nav_menu().inline_keyboard[-1]]  # навигация последняя
    assert with_text_button(None, "stats", "week").inline_keyboard[0][0].callback_data == "tx:stats:week"


def test_without_text_button_strips_tx_and_legacy_mt_and_empty_rows():
    markup = with_text_button(nav_menu(), "stats", "week")
    stripped = without_text_button(markup)
    assert not any(d.startswith(("tx:", "mt:")) for d in _data(stripped) if d)
    assert len(stripped.inline_keyboard) == len(nav_menu().inline_keyboard)
    legacy = match_photo_buttons(5, None)
    legacy.inline_keyboard[0][0].callback_data = "mt:5:0"
    assert not any((d or "").startswith("mt:") for d in _data(without_text_button(legacy)))
    assert without_text_button(None) is None


def test_match_photo_buttons_use_tx_callback():
    buttons = _flat(match_photo_buttons(7812345678, 1105542592))
    assert buttons[0].callback_data == "tx:match:7812345678:1105542592"
    assert _flat(match_photo_buttons(5, None))[0].callback_data == "tx:match:5:0"
    assert not any((b.callback_data or "").startswith("tx:") for b in _flat(match_photo_buttons(5, None, text_shown=True)))


# --- модели и подпись ---------------------------------------------------------------------------

def test_match_board_is_an_image_board_with_ids():
    board = MatchBoard("текст", match_id=5, focus=7)
    assert isinstance(board, ImageBoard) and board.png is None and board.match_id == 5 and board.focus == 7


def test_build_png_swallows_render_errors(caplog):
    assert build_png("тест", lambda: b"PNG") == b"PNG"

    def boom():
        raise RuntimeError("нет шрифта")

    assert build_png("тест", boom) is None
    assert "Не удалось нарисовать тест" in caplog.text


def test_fit_caption_trims_whole_lines():
    short = "a\nb"
    assert fit_caption(short) == short
    long = "\n".join(f"строка {i}" for i in range(300))
    out = fit_caption(long, 1024)
    assert len(out) <= 1024 and out.startswith("строка 0") and not out.endswith("\n")
    assert len(fit_caption("x" * 5000, 100)) <= 100


# --- хендлеры ------------------------------------------------------------------------------------

@pytest.fixture
def e2e():
    pytest.importorskip("aiogram.filters")
    from tests import test_e2e_commands as mod
    return mod


def run(coro):
    return asyncio.run(coro)


class PhotoMessage:
    """Сообщение-фото с кнопкой периода: умеет edit_media (можно заставить падать)."""

    def __init__(self, e2e, fail_edit=False, fail_photo=False):
        self.chat = e2e.FakeChat()
        self.photo = [object()]
        self.sent, self.media_edits, self.deleted = [], [], False
        self.fail_edit, self.fail_photo = fail_edit, fail_photo

    async def edit_media(self, media, reply_markup=None, **kw):
        if self.fail_edit:
            raise RuntimeError("message can't be edited")
        self.media_edits.append((media, reply_markup))

    async def answer_photo(self, photo, caption=None, **kw):
        if self.fail_photo:
            raise RuntimeError("PHOTO_INVALID_DIMENSIONS")
        self.sent.append(("photo", caption, kw.get("reply_markup")))

    async def answer(self, text, **kw):
        self.sent.append(("text", text, kw.get("reply_markup")))

    async def delete(self):
        self.deleted = True


def _board(png=b"\x89PNG\r\n\x1a\nxx"):
    return ImageBoard("полный ТЕКСТ", png=png, caption="короткая подпись")


def test_reply_image_sends_photo_with_caption_and_markup(e2e):
    import mmrbot.bot as botmod
    msg = e2e.FakeMessage()
    markup = nav_menu()
    run(botmod._reply_image(msg, _board(), markup))
    (caption, kw), = msg.photos
    assert caption == "короткая подпись" and kw["reply_markup"] is markup and kw["parse_mode"] == "HTML"


def test_reply_image_without_png_sends_text(e2e):
    import mmrbot.bot as botmod
    msg = e2e.FakeMessage()
    run(botmod._reply_image(msg, _board(png=None), nav_menu()))
    assert not msg.photos and "полный ТЕКСТ" in msg.texts


def test_reply_image_telegram_rejects_photo_falls_back_to_text(e2e):
    import mmrbot.bot as botmod
    msg = PhotoMessage(e2e, fail_photo=True)
    run(botmod._reply_image(msg, _board(), nav_menu()))
    assert msg.sent == [("text", "полный ТЕКСТ", msg.sent[0][2])]


def test_reply_image_edit_replaces_media_in_place(e2e):
    import mmrbot.bot as botmod
    msg = PhotoMessage(e2e)
    run(botmod._reply_image(msg, _board(), nav_menu(), edit=True))
    assert len(msg.media_edits) == 1 and not msg.sent and not msg.deleted


def test_reply_image_edit_failure_sends_new_photo_and_removes_old(e2e):
    import mmrbot.bot as botmod
    msg = PhotoMessage(e2e, fail_edit=True)
    run(botmod._reply_image(msg, _board(), nav_menu(), edit=True))
    assert [s[0] for s in msg.sent] == ["photo"] and msg.deleted


def test_reply_image_edit_not_modified_is_silent(e2e):
    import mmrbot.bot as botmod
    msg = PhotoMessage(e2e)

    async def same(media, reply_markup=None, **kw):
        raise RuntimeError("Bad Request: message is not modified")

    msg.edit_media = same
    run(botmod._reply_image(msg, _board(), nav_menu(), edit=True))
    assert not msg.sent and not msg.deleted


def test_text_view_button_sends_text_and_removes_button(e2e):
    import mmrbot.bot as botmod
    storage, od, sz = _env_for_match(e2e)
    cb = e2e.FakeCallback("tx:match:9100000007:%d" % e2e.ACC)
    cb.message.reply_markup = match_photo_buttons(9100000007, e2e.ACC)
    run(botmod.on_callback(cb, storage, od, sz))
    assert "Radiant" in cb.message.texts
    assert not any((d or "").startswith("tx:") for d in _data(cb.message.markup_edits[-1]))


def test_legacy_mt_button_still_works(e2e):
    import mmrbot.bot as botmod
    storage, od, sz = _env_for_match(e2e)
    cb = e2e.FakeCallback("mt:9100000007:%d" % e2e.ACC)
    cb.message.reply_markup = match_photo_buttons(9100000007, e2e.ACC)
    run(botmod.on_callback(cb, storage, od, sz))
    assert "Radiant" in cb.message.texts


def test_unknown_text_view_is_ignored(e2e):
    import mmrbot.bot as botmod
    storage, od, sz = _env_for_match(e2e)
    cb = e2e.FakeCallback("tx:nonsense:1")
    run(botmod.on_callback(cb, storage, od, sz))
    assert not cb.message.sent


def _env_for_match(e2e):
    import tempfile
    from pathlib import Path
    from mmrbot.storage import Storage
    tmp = Path(tempfile.mkdtemp())
    storage = Storage(str(tmp / "t.db"))
    storage.get_or_create_chat(100)
    storage.add_player(100, e2e.ACC, "shinoame", 5000, 0, 0)
    return storage, e2e.FakeOD(), e2e.FakeStratz()


def test_alert_buttons_open_whole_match_and_dotabuff():
    from mmrbot.keyboards import alert_buttons
    buttons = _flat(alert_buttons(7812345678))
    assert buttons[0].callback_data == "mx:7812345678" and "матч" in buttons[0].text.lower()
    assert buttons[1].url == "https://www.dotabuff.com/matches/7812345678"


def test_whole_match_button_sends_match_picture(e2e):
    import mmrbot.bot as botmod
    storage, od, sz = _env_for_match(e2e)
    cb = e2e.FakeCallback("mx:9100000007")
    run(botmod.on_callback(cb, storage, od, sz))
    assert len(cb.message.photos) == 1
    run(botmod.on_callback(e2e.FakeCallback("mx:abc"), storage, od, sz))  # мусор в данных — молча игнорируем


def test_period_tab_under_a_card_swaps_the_picture_in_place(e2e):
    import mmrbot.bot as botmod
    storage, od, sz = _env_for_match(e2e)
    msg = PhotoMessage(e2e)
    msg.reply_markup = None
    cb = e2e.FakeCallback("m:month")
    cb.message = msg
    run(botmod.on_callback(cb, storage, od, sz))
    assert len(msg.media_edits) == 1 and not msg.sent and not msg.deleted  # edit_media, без новых сообщений и «Считаю…»
    markup = msg.media_edits[0][1]
    assert {"m:stats", "m:today", "m:week", "m:month"} <= {b.callback_data for b in _flat(markup)}


def test_stats_card_failure_falls_back_to_text(e2e, monkeypatch):
    import mmrbot.bot as botmod
    from mmrbot import service
    storage, od, sz = _env_for_match(e2e)

    def boom(*a, **kw):
        raise RuntimeError("нет шрифта")

    monkeypatch.setattr(service, "render_stats_image", boom)
    msg = e2e.FakeMessage()
    run(botmod.cmd_stats(msg, e2e.cmdobj("stats", None), storage, od, sz))
    assert not msg.photos and "Рейтинг" in msg.texts and "shinoame" in msg.texts


def test_stats_command_sends_card_with_tabs_and_text_button(e2e):
    import mmrbot.bot as botmod
    storage, od, sz = _env_for_match(e2e)
    msg = e2e.FakeMessage()
    run(botmod.cmd_stats(msg, e2e.cmdobj("stats", None), storage, od, sz))
    (caption, kw), = msg.photos
    assert "Рейтинг" in caption and "shinoame" in caption
    data = {b.callback_data for b in _flat(kw["reply_markup"])}
    assert {"m:stats", "m:today", "m:week", "m:month", "tx:stats:stats", "m:menu"} <= data
    msg_today = e2e.FakeMessage()
    run(botmod.cmd_stats(msg_today, e2e.cmdobj("stats", "сегодня"), storage, od, sz))
    assert "tx:stats:today" in {b.callback_data for b in _flat(msg_today.photos[0][1]["reply_markup"])}
