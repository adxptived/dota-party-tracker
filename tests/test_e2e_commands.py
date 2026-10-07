"""Сквозная проверка ВСЕХ команд и кнопок бота на реальной БД.

Игрок — shinoame (account_id 1105542592), 7 последних ранкед-матчей — из скрина Dotabuff.
Сеть подменена фейками OpenDota/Stratz; хендлеры вызываются как их вызвал бы aiogram.
"""
import asyncio
import time

import pytest
from aiogram.filters import CommandObject

import mmrbot.bot as botmod
from mmrbot.storage import Storage

ACC = 1105542592
NOW = int(time.time())

# (match_id, часов назад, hero_id, K, D, A, победа, минут, position, imp)
GAMES = [
    (9100000007, 1, 12, 13, 3, 10, True, 33, 1, 21),    # Phantom Lancer
    (9100000006, 2, 1, 10, 1, 8, True, 33, 1, 30),      # Anti-Mage
    (9100000005, 14, 145, 3, 7, 16, True, 34, 1, 5),    # Kez
    (9100000004, 15, 49, 4, 6, 7, False, 30, 2, -8),    # Dragon Knight
    (9100000003, 24, 145, 10, 10, 11, False, 40, 1, 3),  # Kez
    (9100000002, 25, 145, 5, 6, 9, False, 39, 1, -2),   # Kez
    (9100000001, 26, 109, 10, 2, 12, True, 35, 1, 25),  # Terrorblade
]


class FakeOD:
    def refresh(self, account_id):
        return True

    def get_profile(self, account_id):
        return {"rank_tier": 80, "leaderboard_rank": None, "personaname": "shinoame"}

    def get_matches(self, account_id, limit=200):
        return [
            {"match_id": mid, "start_time": NOW - h * 3600, "player_slot": 0, "radiant_win": win,
             "lobby_type": 7, "kills": k, "deaths": d, "assists": a, "hero_id": hero,
             "duration": mins * 60, "party_size": 1, "average_rank": 80}
            for mid, h, hero, k, d, a, win, mins, _pos, _imp in GAMES
        ]

    def get_totals(self, account_id):
        return {"gpm": 600.0, "xpm": 700.0, "last_hits": 350.0}

    def get_lanes(self, account_id):
        return {1: (20, 12), 2: (5, 3)}

    def get_gpm_distribution(self, account_id):
        return {"median": 600, "best": 900}

    def get_match_player_stats(self, match_id, account_id, player_slot=None):
        return {"gpm": 650, "xpm": 720, "last_hits": 400, "denies": 12, "hero_damage": 30000,
                "tower_damage": 4000, "hero_healing": 0, "net_worth": 25000, "level": 24,
                "benchmarks": {"gold_per_min": 0.7, "xp_per_min": 0.6}}


class FakeStratz:
    def __init__(self):
        self.full_requests = []

    def get_matches(self, account_id, match_ids, hints=None):
        by_id = {g[0]: g for g in GAMES}
        return {
            mid: {"position": by_id[mid][8], "role": "CORE", "lane": "SAFE_LANE", "imp": by_id[mid][9],
                  "gpm": 640, "xpm": 700, "net_worth": 24000, "hero_damage": 28000,
                  "tower_damage": 3500, "hero_healing": 0, "last_hits": 380, "denies": 10, "level": 23}
            for mid in match_ids if mid in by_id
        }

    def get_match(self, match_id):
        self.full_requests.append(match_id)
        game = next((g for g in GAMES if g[0] == match_id), None)
        if game is None:
            return None
        mid, _h, hero, k, d, a, win, mins, pos, imp = game
        me = {"account_id": ACC, "name": "shinoame", "is_radiant": True, "hero_id": hero, "position": pos,
              "role": "CORE", "lane": "SAFE_LANE", "kills": k, "deaths": d, "assists": a, "imp": imp,
              "gpm": 640, "xpm": 700, "net_worth": 24000, "hero_damage": 28000, "tower_damage": 3500,
              "hero_healing": 0, "last_hits": 380, "denies": 10, "level": 23}
        enemy = dict(me, account_id=555, name="Враг", is_radiant=False, hero_id=2, position=1)
        return {"match_id": mid, "start_time": NOW, "duration": mins * 60, "radiant_win": win,
                "players": [me, enemy]}


class FakeChat:
    id = 100


class FakeMessage:
    def __init__(self):
        self.chat = FakeChat()
        self.sent = []  # (text, kwargs)

    async def answer(self, text, **kwargs):
        self.sent.append((text, kwargs))

    async def edit_text(self, text, **kwargs):
        self.sent.append((text, kwargs))

    async def answer_photo(self, photo, caption=None, **kwargs):
        assert photo.data[:8] == b"\x89PNG\r\n\x1a\n"
        self.sent.append((caption, dict(kwargs, photo=photo)))

    async def edit_reply_markup(self, reply_markup=None, **kwargs):
        self.markup_edits = getattr(self, "markup_edits", []) + [reply_markup]

    @property
    def photos(self):
        return [(t, kw) for t, kw in self.sent if "photo" in kw]

    @property
    def texts(self):
        return "\n".join(t for t, _ in self.sent)


class FakeCallback:
    def __init__(self, data):
        self.data = data
        self.message = FakeMessage()

    async def answer(self, *a, **k):
        pass


@pytest.fixture
def env(tmp_path):
    storage = Storage(str(tmp_path / "e2e.db"))
    storage.get_or_create_chat(100)
    storage.add_player(100, ACC, "shinoame", 5000, 0, 0)
    return storage, FakeOD(), FakeStratz()


def run(coro):
    return asyncio.run(coro)


def cmdobj(name, args=None):
    return CommandObject(command=name, args=args)


def call(handler, name, args, env, stratz=True):
    storage, od, stratz_client = env
    msg = FakeMessage()
    run(handler(msg, cmdobj(name, args), storage, od, stratz_client if stratz else None))
    return msg


def assert_ok(msg):
    text = msg.texts
    assert msg.sent, "бот ничего не ответил"
    assert "Traceback" not in text
    assert "Не удалось" not in text and "не удалось" not in text.lower().replace("не удалось определить", "")


# --- команды ------------------------------------------------------------

@pytest.mark.parametrize("args", [None, "сегодня"])
def test_stats(env, args):
    msg = call(botmod.cmd_stats, "stats", args, env)
    assert_ok(msg)
    assert "shinoame" in msg.texts


def test_compare_and_together(env):
    storage, od, sz = env
    for handler in (botmod.cmd_compare, botmod.cmd_together):
        msg = FakeMessage()
        run(handler(msg, storage, od, sz))
        assert_ok(msg)


def test_heroes_party_board(env):
    msg = call(botmod.cmd_heroes, "heroes", None, env)
    assert_ok(msg)
    assert len(msg.photos) == 1 and "Любимые герои" in msg.photos[0][0]  # картинкой, текст — по кнопке
    assert "Kez" in _text_button(msg, env).texts


@pytest.mark.parametrize("args", ["shinoame", "@shinoame", "@Shinoame месяц", "shinoame неделя", "день shinoame"])
def test_heroes_player_with_positions(env, args):
    msg = call(botmod.cmd_heroes, "heroes", args, env)
    assert_ok(msg)
    assert len(msg.photos) == 1 and "Герои: shinoame" in msg.photos[0][0]
    text = _text_button(msg, env).texts
    assert "Герои: shinoame" in text
    assert "Позиции: shinoame" in text and "Pos 1" in text
    if "неделя" not in args and "день" not in args:
        assert "Kez" in text and "Phantom Lancer" in text


def test_heroes_player_period_filters(env):
    msg = call(botmod.cmd_heroes, "heroes", "shinoame день", env)
    assert len(msg.photos) == 1
    day = _text_button(msg, env).texts
    assert "Phantom Lancer" in day and "Terrorblade" not in day  # TB — 26 часов назад


def test_roles_card_is_photo_with_period_and_text_buttons(env):
    msg = call(botmod.cmd_roles, "roles", "shinoame", env)
    assert_ok(msg)
    caption, kw = msg.photos[0]
    assert "Позиции: shinoame" in caption
    data = {b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row}
    assert {"rp:1105542592:day", "rp:1105542592:all", "hp:1105542592:all", f"tx:rp:{ACC}:all"} <= data
    text = _text_button(msg, env).texts
    assert "Позиции: shinoame" in text and "Pos 1" in text


@pytest.mark.parametrize("args", ["Kez", "kez месяц", "Anti-Mage", "am"])
def test_heroes_hero_view(env, args):
    msg = call(botmod.cmd_heroes, "heroes", args, env)
    assert_ok(msg)
    assert "shinoame" in msg.texts


def test_hero_card_text_button_gives_text_report(env):
    msg = call(botmod.cmd_heroes, "heroes", "kez месяц", env)
    caption, kw = msg.photos[0]
    assert "Герой: Kez" in caption and "за месяц" in caption
    data = {b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row}
    assert any(d.startswith("tx:hero:") and d.endswith(":month") for d in data)
    text = _text_button(msg, env).texts
    assert "Герой: Kez" in text and "shinoame" in text


def test_hero_card_image_failure_falls_back_to_text(env, monkeypatch):
    import mmrbot.service as service

    def broken(*a, **k):
        raise RuntimeError("рендер упал")

    for name in ("render_hero_image", "render_player_heroes_image", "render_party_heroes_image"):
        monkeypatch.setattr(service, name, broken)
    for args in ("kez", "shinoame", None):
        msg = call(botmod.cmd_heroes, "heroes", args, env)
        assert_ok(msg)
        assert not msg.photos and "Kez" in msg.texts


def test_heroes_unknown_name(env):
    msg = call(botmod.cmd_heroes, "heroes", "абракадабра", env)
    assert "Не нашёл" in msg.texts


def _text_button(msg, env, stratz=True):
    """Нажать «📝 Текстом» под картинкой матча → сообщение, куда ушёл текст."""
    storage, od, sz = env
    markup = msg.photos[-1][1]["reply_markup"]
    data = next(b.callback_data for row in markup.inline_keyboard for b in row
                if (b.callback_data or "").startswith("tx:"))
    cb = FakeCallback(data)
    cb.message.reply_markup = markup  # Telegram отдаёт кнопки сообщения, под которым нажали
    run(botmod.on_callback(cb, storage, od, sz if stratz else None))
    assert cb.message.markup_edits and not any(  # кнопку «Текстом» под фото убрали — второй раз не жмут
        (b.callback_data or "").startswith("tx:") for row in cb.message.markup_edits[-1].inline_keyboard for b in row)
    return cb.message


@pytest.mark.parametrize("args", [None, "последний", "@shinoame", "shinoame последний"])
def test_match_latest(env, args):
    msg = call(botmod.cmd_match, "match", args, env)
    assert_ok(msg)
    assert len(msg.photos) == 1  # картинка матча, текстом — по кнопке
    caption = msg.photos[0][0]
    assert "9100000007" in caption and "Phantom Lancer" in caption and "13/3/10" in caption
    text = _text_button(msg, env).texts
    assert "Radiant" in text and "Dire" in text and "GPM 640" in text


def test_match_by_id_any_match_without_stratz_cache(env):
    msg = call(botmod.cmd_match, "match", "9100000005", env)
    assert_ok(msg)
    assert msg.photos and "Kez" in msg.texts and "3/7/16" in msg.texts


def test_match_unknown_id(env):
    msg = call(botmod.cmd_match, "match", "9999999999", env)
    assert "не найден в Stratz" in msg.texts and not msg.photos


def test_match_by_id_for_stranger_works_when_chat_has_no_players(tmp_path):
    storage = Storage(str(tmp_path / "empty.db"))
    env = (storage, FakeOD(), FakeStratz())
    msg = FakeMessage()
    run(botmod.cmd_match(msg, cmdobj("match", "9100000006"), *env))
    assert msg.photos and "9100000006" in msg.texts
    text = _text_button(msg, env).texts
    assert "Anti-Mage" in text and "Враг" in text  # матч чужой пати — всё равно показан


def test_match_latest_falls_back_to_cache_without_stratz(env):
    msg = call(botmod.cmd_match, "match", None, env, stratz=False)
    assert_ok(msg)
    assert msg.photos and "Phantom Lancer" in msg.texts and "13/3/10" in msg.texts
    text = _text_button(msg, env, stratz=False).texts
    assert "Phantom Lancer" in text and "13/3/10" in text and "Stratz" not in text  # текст из кэша БД


def test_match_image_failure_falls_back_to_text(env, monkeypatch):
    import mmrbot.service as service

    def broken(*a, **k):
        raise RuntimeError("рендер упал")

    monkeypatch.setattr(service, "render_match_image", broken)
    msg = call(botmod.cmd_match, "match", None, env)
    assert_ok(msg)
    assert not msg.photos and "Radiant" in msg.texts and "13/3/10" in msg.texts


def test_match_photo_send_failure_falls_back_to_text(env):
    class NoPhoto(FakeMessage):
        async def answer_photo(self, *a, **k):
            raise RuntimeError("Telegram не принял фото")

    storage, od, sz = env
    msg = NoPhoto()
    run(botmod.cmd_match(msg, cmdobj("match", None), storage, od, sz))
    assert "Radiant" in msg.texts and "13/3/10" in msg.texts


def test_match_without_stratz_and_id_asks_for_key(env):
    msg = call(botmod.cmd_match, "match", "9100000005", env, stratz=False)
    assert "Stratz" in msg.texts


@pytest.mark.parametrize("args", [None, "shinoame", "@shinoame"])
def test_player_card(env, args):
    msg = call(botmod.cmd_player, "player", args, env)
    assert_ok(msg)
    if args:
        assert "shinoame" in msg.texts
    else:
        assert any(kw.get("reply_markup") for _, kw in msg.sent)  # выбор игрока кнопками


def test_list_help_menu(env):
    storage, od, sz = env
    msg = FakeMessage()
    run(botmod.cmd_list(msg, storage))
    assert "shinoame" in msg.texts and "1105542592" in msg.texts
    msg = FakeMessage()
    run(botmod.cmd_help(msg))
    assert "/match" in msg.texts and "/heroes" in msg.texts and "/hero " not in msg.texts
    msg = FakeMessage()
    run(botmod.cmd_menu(msg))
    assert msg.sent[0][1]["reply_markup"] is not None


def test_add_by_dotabuff_link_and_steam_vanity(tmp_path, monkeypatch):
    storage = Storage(str(tmp_path / "add.db"))
    msg = FakeMessage()
    run(botmod.cmd_add(msg, cmdobj("add", "https://ru.dotabuff.com/players/1105542592 shinoame 5000"),
                       storage, FakeOD(), FakeStratz()))
    assert "shinoame добавлен" in msg.texts
    assert storage.get_player(100, "shinoame").account_id == ACC

    monkeypatch.setattr(botmod, "resolve_account_id", lambda text: 4242)
    msg = FakeMessage()
    run(botmod.cmd_add(msg, cmdobj("add", "https://steamcommunity.com/id/some_name Вася"),
                       storage, FakeOD(), FakeStratz()))
    assert "Вася добавлен" in msg.texts


def test_setmmr_setstep_settime_remove(env):
    storage, od, sz = env
    for handler, args, needle in (
        (botmod.cmd_setmmr, "shinoame 5300", "5300"),
        (botmod.cmd_setstep, "30", "30"),
        (botmod.cmd_settime, "11", "11:00"),
        (botmod.cmd_remove, "shinoame", "Удалить игрока shinoame?"),  # удаление — только через подтверждение
    ):
        msg = FakeMessage()
        run(handler(msg, cmdobj("x", args), storage))
        assert needle in msg.texts
    assert storage.get_player(100, "shinoame") is not None
    confirm = FakeCallback(f"pp:rmyes:{ACC}")
    run(botmod.on_callback(confirm, storage, od, sz))
    assert "удалён" in confirm.message.texts and storage.get_player(100, "shinoame") is None


# --- кнопки -------------------------------------------------------------

@pytest.mark.parametrize("data", [
    "m:menu", "m:help", "m:list", "m:stats", "m:today", "m:week", "m:month", "m:compare", "m:together",
    "m:match", "m:heroes", "m:player",
    "pp:heroes:1105542592", "pp:player:1105542592",
    "hp:1105542592:day", "hp:1105542592:week", "hp:1105542592:month", "hp:1105542592:all",
])
def test_every_button_works(env, data):
    storage, od, sz = env
    cb = FakeCallback(data)
    run(botmod.on_callback(cb, storage, od, sz))
    assert_ok(cb.message)


def test_menu_week_button_shows_period_card_and_text_on_demand(env):
    storage, od, sz = env
    cb = FakeCallback("m:week")
    run(botmod.on_callback(cb, storage, od, sz))
    (caption, kw), = cb.message.photos  # неделя — картинкой, под ней вкладки периодов и «Текстом»
    assert "За неделю" in caption and "shinoame" in caption
    data = {b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row}
    assert {"m:stats", "m:today", "m:week", "m:month", "tx:stats:week"} <= data
    text_cb = FakeCallback("tx:stats:week")
    text_cb.message.reply_markup = kw["reply_markup"]
    run(botmod.on_callback(text_cb, storage, od, sz))
    assert "Статистика за неделю" in text_cb.message.texts  # прежний текстовый отчёт


class DeletableMessage(FakeMessage):
    def __init__(self):
        super().__init__()
        self.deleted = False
        self.statuses = []

    async def answer(self, text, **kwargs):
        self.sent.append((text, kwargs))
        sent = DeletableMessage()
        self.statuses.append(sent)
        return sent

    async def delete(self):
        self.deleted = True


class PhotoCallbackMessage(DeletableMessage):
    """Сообщение-фото, под которым нажата кнопка периода: картинка должна смениться через edit_media."""

    def __init__(self):
        super().__init__()
        self.photo = [object()]
        self.media_edits = []

    async def edit_media(self, media, reply_markup=None, **kw):
        self.media_edits.append((media, reply_markup))


@pytest.mark.parametrize("data", ["hp:1105542592:week", "rp:1105542592:week"])
def test_period_buttons_edit_photo_in_place(env, data):
    storage, od, sz = env
    cb = FakeCallback(data)
    cb.message = PhotoCallbackMessage()
    run(botmod.on_callback(cb, storage, od, sz))
    (media, markup), = cb.message.media_edits
    assert "за неделю" in media.caption
    assert any(b.text.startswith("• Неделя") for row in markup.inline_keyboard for b in row)
    assert not cb.message.deleted and not cb.message.sent  # ни нового сообщения, ни удаления


def test_all_menu_buttons_have_handlers():
    from mmrbot.keyboards import CATEGORIES, category_menu, main_menu
    markups = [main_menu()] + [category_menu(key) for key in CATEGORIES]
    actions = {b.callback_data for m in markups for row in m.inline_keyboard for b in row}
    assert "m:roles" not in actions and {"m:heroes", "m:match", "m:stats"} <= actions


class HiddenOD(FakeOD):
    """Как у реального shinoame: профиль виден, а матчей OpenDota не отдаёт (данные скрыты)."""

    def get_matches(self, account_id, limit=200):
        return []


def test_hidden_match_data_gives_clear_hint(tmp_path):
    storage = Storage(str(tmp_path / "hidden.db"))
    storage.get_or_create_chat(100)
    storage.add_player(100, ACC, "shinoame", 5000, 0, 0)
    msg = FakeMessage()
    run(botmod.cmd_match(msg, cmdobj("x", None), storage, HiddenOD(), FakeStratz()))
    assert "Выставлять публичные данные" in msg.texts
    msg = FakeMessage()  # герои: на картинке пометка, полная подсказка — в тексте по кнопке
    env = (storage, HiddenOD(), FakeStratz())
    run(botmod.cmd_heroes(msg, cmdobj("x", "shinoame"), *env))
    assert msg.photos and "Выставлять публичные данные" in _text_button(msg, env).texts
    # /stats и /player при этом не падают
    for handler in (botmod.cmd_stats, botmod.cmd_player):
        msg = FakeMessage()
        run(handler(msg, cmdobj("x", "shinoame"), storage, HiddenOD(), FakeStratz()))
        assert msg.sent and "Traceback" not in msg.texts


def test_menu_button_replaces_menu_message_with_report_card(env):
    storage, od, sz = env
    cb = FakeCallback("m:week")
    cb.message = DeletableMessage()
    run(botmod.on_callback(cb, storage, od, sz))
    assert cb.message.deleted and not cb.message.statuses  # меню заменено карточкой, лишних сообщений нет
    (caption, kw), = cb.message.photos
    data = {b.callback_data for row in kw["reply_markup"].inline_keyboard for b in row}  # под отчётом «В меню» / «Закрыть»
    assert {"m:menu", "x:close"} <= data and {"m:stats", "m:today", "m:week", "m:month"} <= data  # + вкладки периодов


def test_category_button_opens_submenu(env):
    storage, od, sz = env
    cb = FakeCallback("m:c:stats")
    cb.message = DeletableMessage()
    run(botmod.on_callback(cb, storage, od, sz))
    assert not cb.message.deleted and not cb.message.statuses  # подменю правит то же сообщение
    markup = cb.message.sent[-1][1]["reply_markup"]
    data = {b.callback_data for row in markup.inline_keyboard for b in row}
    assert {"m:stats", "m:week", "m:menu"} <= data


def test_close_button_deletes_message(env):
    storage, od, sz = env
    cb = FakeCallback("x:close")
    cb.message = DeletableMessage()
    run(botmod.on_callback(cb, storage, od, sz))
    assert cb.message.deleted and not cb.message.sent


