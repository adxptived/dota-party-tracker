"""Ежедневная сводка: скользящие 24 часа до отправки (без недельных данных), текст, карточка, картинка."""
import asyncio
import io
import time

import pytest
from PIL import Image

from mmrbot import card_data as cd
from mmrbot import service
from mmrbot.cards import WIDTH, signed
from mmrbot.formatting import render_daily
from mmrbot.storage import Storage
from mmrbot.tracker import build_daily_report, build_player_summary

NOW = 1_000_000
HOUR, DAY = 3600, 86_400


def m(match_id, start, win=True, hero=1, k=5, d=3, a=7, dur=2400, **extra):
    return {"match_id": match_id, "start_time": start, "player_slot": 0, "radiant_win": win, "lobby_type": 7,
            "kills": k, "deaths": d, "assists": a, "hero_id": hero, "duration": dur, **extra}


@pytest.fixture
def store(tmp_path):
    st = Storage(str(tmp_path / "daily.db"))
    st.get_or_create_chat(100)
    return st


def _party(store):
    return store.add_player(100, 1, "Вася", 5000, 0, 0), store.add_player(100, 2, "Петя", 5000, 0, 0)


def _details(store, player_id, match_id, imp=None, **fields):
    """Обогащённые поля матча — так они попадают в БД в бою (OpenDota-детали и Stratz IMP)."""
    store.update_match_details(player_id, match_id, fields, None)
    if imp is not None:
        store.update_match_stratz(player_id, match_id, {"imp": imp})


def _seed(store):
    """Вася: 4 игры за сутки (серия побед 3) + две «старые»; Петя: общая игра + рекордная, но недельной давности."""
    a, b = _party(store)
    store.add_matches(a.id, [
        m(1, NOW - 2 * HOUR, True, hero=1, k=12, d=1, a=10),
        m(2, NOW - 5 * HOUR, True, hero=1),
        m(7, NOW - 8 * HOUR, True, hero=2),
        m(3, NOW - 23 * HOUR, False, hero=2),
        m(4, NOW - 26 * HOUR, True),   # вне окна: старше 24 ч
        m(5, NOW - 3 * DAY, True),     # вне окна: это уже «неделя»
    ])
    _details(store, a.id, 1, net_worth=21000, gpm=650, xpm=700, hero_damage=30000, tower_damage=4000, imp=12)
    store.add_matches(b.id, [
        m(1, NOW - 2 * HOUR, True, hero=1),
        m(6, NOW - 4 * DAY, False, k=30, d=0, a=7),  # рекорд недели — в сводку суток попасть не должен
    ])
    return a, b


# --- данные: окно ровно 24 часа ---------------------------------------------------------------

def test_daily_report_counts_only_the_last_24_hours(store):
    _seed(store)
    report = build_daily_report(store, 100, NOW)
    assert (report["since"], report["until"]) == (NOW - DAY, NOW)
    rows = {r["name"]: r for r in report["rows"]}
    step = report["step"]
    assert (rows["Вася"]["games"], rows["Вася"]["wins"], rows["Вася"]["losses"]) == (4, 3, 1)
    assert rows["Вася"]["delta"] == 2 * step and rows["Петя"]["games"] == 1
    assert report["totals"]["games"] == 5 and report["totals"]["wins"] == 4 and report["totals"]["delta"] == 3 * step


def test_daily_window_edge_is_exactly_24_hours_before_the_message(store):
    a, _ = _party(store)
    store.add_matches(a.id, [m(1, NOW - DAY, True), m(2, NOW - DAY - 1, True)])
    rows = {r["name"]: r for r in build_daily_report(store, 100, NOW)["rows"]}
    assert rows["Вася"]["games"] == 1


def test_daily_report_highlights_come_from_the_last_24_hours_only(store):
    _seed(store)
    report = build_daily_report(store, 100, NOW)
    assert report["hero"] == {"hero_id": 1, "games": 3, "wins": 3}
    assert report["streak"] == ("Вася", 3)
    assert report["shared"]["games"] == 1 and report["shared"]["wins"] == 1
    kills = next(r for r in report["records"] if r["key"] == "kills")
    assert kills["player"] == "Вася" and kills["value"] == 12  # не 30 убийств Пети из прошлой недели
    best = report["best_game"]
    assert best["player"] == "Вася" and best["match"]["match_id"] == 1  # безсмертная игра Пети была 4 дня назад
    assert (best["kills"], best["deaths"], best["assists"], best["kda"], best["won"]) == (12, 1, 10, 22, True)
    assert "awards" not in report


def test_daily_report_player_details_for_the_card(store):
    _seed(store)
    report = build_daily_report(store, 100, NOW)
    step = report["step"]
    row = next(r for r in report["rows"] if r["name"] == "Вася")
    assert row["series"] == [-step, 0, step, 2 * step]
    assert row["hero"]["hero_id"] == 1 and row["hero"]["games"] == 2
    assert row["minutes"] == 160 and report["totals"]["minutes"] == 200 and report["totals"]["avg_minutes"] == 40
    first = row["timeline"][0]
    assert (first["start"], first["end"], first["won"]) == (NOW - 23 * HOUR, NOW - 23 * HOUR + 2400, False)
    assert [g["start"] for g in row["timeline"]] == sorted(g["start"] for g in row["timeline"])
    assert report["first_start"] == NOW - 23 * HOUR and report["last_end"] == NOW - 2 * HOUR + 2400


def test_daily_timeline_assumes_a_typical_length_when_duration_is_unknown(store):
    a, _ = _party(store)
    store.add_matches(a.id, [m(1, NOW - HOUR, True, dur=None)])
    row = next(r for r in build_daily_report(store, 100, NOW)["rows"] if r["name"] == "Вася")
    assert row["timeline"][0]["end"] - row["timeline"][0]["start"] == 2400 and row["minutes"] == 0


def test_daily_report_for_a_quiet_day(store):
    a, _ = _party(store)
    store.add_matches(a.id, [m(1, NOW - 2 * DAY)])
    report = build_daily_report(store, 100, NOW)
    assert report["totals"]["games"] == 0 and report["hero"] is None and report["streak"] is None
    assert report["records"] == [] and report["best_game"] is None and report["first_start"] is None
    assert all(r["games"] == 0 and r["timeline"] == [] for r in report["rows"])
    text = render_daily(report)
    assert "не было" in text and "24 час" in text


# --- текст --------------------------------------------------------------------------------------

def test_daily_text_is_about_the_last_24_hours_and_has_no_week_blocks(store):
    _seed(store)
    report = build_daily_report(store, 100, NOW)
    info = {"Вася": {"mmr": 5050, "rank_text": "Legend 5"}}
    text = render_daily(report, info)
    assert "Ежедневная сводка" in text and "24 час" in text and "→" in text
    assert "Лидер суток: <b>Вася</b>" in text and "Герой суток" in text and "Anti-Mage" in text
    assert "Лучшая серия" in text and "3 победы подряд" in text and "Вместе: 1 игра" in text
    assert "≈5050" in text and "Legend 5" in text
    assert "Рекорды суток" in text and "12 убийств" in text and "30 убийств" not in text
    assert "недел" not in text.lower()


def test_daily_text_escapes_names_and_lists_idle_players(store):
    a = store.add_player(100, 1, "<b>Вася&", 5000, 0, 0)
    store.add_player(100, 2, "Коля", 5000, 0, 0)
    store.add_matches(a.id, [m(1, NOW - HOUR, True)])
    text = render_daily(build_daily_report(store, 100, NOW))
    assert "&lt;b&gt;Вася&amp;" in text and "<b>Вася&" not in text
    assert "Не играли: Коля" in text


# --- карточка-картинка: что показать -------------------------------------------------------------

def test_daily_card_view_banner_tiles_rows_and_timeline(store):
    _seed(store)
    report = build_daily_report(store, 100, NOW)
    info = {"Вася": {"avatar": "u", "rank_tier": 55, "rank_text": "Legend 5", "mmr": 5050}}
    view = cd.daily_card(report, info)
    assert view["title"] == "Ежедневная сводка" and view["badge"][0] == "24 ЧАСА" and "→" in view["window"]
    assert view["big"]["value"] == signed(report["totals"]["delta"]) and "5 игр" in view["big"]["sub"]
    labels = [t["label"] for t in view["tiles"]]
    assert 3 <= len(labels) <= 4 and labels[0] == "Игр за 24 часа" and "Лидер суток" in labels
    vasya = next(r for r in view["rows"] if r["name"] == "Вася")
    assert vasya["avatar"] == "u" and vasya["rank_tier"] == 55 and vasya["rank_text"] == "Legend 5 · ≈5050"
    assert vasya["big"] == signed(2 * report["step"]) and (vasya["wins"], vasya["losses"]) == (3, 1)
    assert vasya["series"][0] == 0 and vasya["series"][-1] == 2 * report["step"]
    assert vasya["hero_id"] == 1 and vasya["hero_note"] == "×2" and "4 игры" in vasya["sub"]
    assert view["rows"][0]["name"] == "Вася"  # лидер суток — первым
    lanes = view["timeline"]["lanes"]
    assert [lane["name"] for lane in lanes] == [r["name"] for r in view["rows"] if r["games"]]
    assert len(lanes[0]["games"]) == 4 and view["timeline"]["since"] == NOW - DAY and view["timeline"]["until"] == NOW
    ticks = view["timeline"]["ticks"]
    assert 7 <= len(ticks) <= 9 and all(label.endswith(":00") and int(label[:2]) % 3 == 0 for _, label in ticks)


def test_daily_card_view_records_awards_and_idle_rows(store):
    _seed(store)
    store.add_player(100, 3, "Коля", 5000, 0, 0)
    view = cd.daily_card(build_daily_report(store, 100, NOW), {})
    first = view["records"][0]
    assert first["label"] == "Герой суток" and first["hero_id"] == 1 and "3 игры" in first["player"]
    assert 2 <= len(view["records"]) <= 7 and all("смерт" not in r["label"].lower() for r in view["records"])
    assert "awards" not in view
    best = view["best_game"]
    assert best["player"] == "Вася" and best["hero_id"] == 1 and best["won"] is True
    assert best["kills"] == 12 and best["deaths"] == 1 and best["assists"] == 10 and best["kda"] == "22.0"
    assert best["stats"]  # плитки: нетворс, GPM/XPM, урон, IMP, длительность — те, что известны
    idle = next(r for r in view["rows"] if r["name"] == "Коля")
    assert idle["games"] == 0 and idle["big"] == "0" and idle["sub"] == "не играл" and idle["series"] == []
    assert view["rows"][-1]["name"] == "Коля" and [lane["name"] for lane in view["timeline"]["lanes"]] == ["Вася", "Петя"]


def test_daily_caption_names_the_leader_and_the_window(store):
    _seed(store)
    caption = cd.daily_caption(build_daily_report(store, 100, NOW))
    assert "Ежедневная сводка" in caption and "5 игр" in caption and "Лидер суток: <b>Вася</b>" in caption
    assert "24" in caption and "недел" not in caption.lower()
    quiet = cd.daily_caption({"rows": [], "totals": {"games": 0}})
    assert "Ежедневная сводка" in quiet and "не было" in quiet


# --- картинка --------------------------------------------------------------------------------------

def _png(data: bytes) -> Image.Image:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(data)).convert("RGB")


def test_daily_image_is_full_width_and_grows_with_content(store):
    from mmrbot.daily_image import render_daily_image
    _seed(store)
    full = _png(render_daily_image(cd.daily_card(build_daily_report(store, 100, NOW), {})))
    assert full.width == WIDTH and full.height > 900
    bare = {"rows": [], "totals": {"games": 0, "wins": 0, "losses": 0, "delta": 0, "minutes": 0, "avg_minutes": 0},
            "since": NOW - DAY, "until": NOW, "tz": "Europe/Moscow", "step": 25, "hero": None, "streak": None,
            "shared": {"games": 0}, "records": [], "best_game": None, "first_start": None, "last_end": None}
    small = _png(render_daily_image(cd.daily_card(bare, {})))
    assert small.width == WIDTH and small.height < full.height


def test_daily_image_survives_junk_icons_avatars_and_a_stale_note(store):
    from mmrbot.daily_image import render_daily_image
    _seed(store)
    view = cd.daily_card(build_daily_report(store, 100, NOW), {"Вася": {"avatar": "u"}})
    view["note"] = "OpenDota недоступен с 10:00 — показаны данные на 09:50."
    assert _png(render_daily_image(view, icons={1: b"junk"}, avatars={"u": b"junk"})).width == WIDTH


# --- сервис: сводка в чат -----------------------------------------------------------------------------

def _fake_summaries(monkeypatch):
    async def gather(storage, od, chat_id, *a, **k):
        chat = storage.get_or_create_chat(chat_id)
        return [build_player_summary(storage, chat, p, NOW) for p in storage.list_players(chat_id)]

    monkeypatch.setattr(service, "gather_summaries", gather)


def _fresh(store):
    for player in store.list_players(100):
        store.touch_player(player.id, int(time.time()))  # данные «свежие» — без пометки об устаревании


def test_daily_board_has_png_text_and_24h_caption(store, monkeypatch):
    _seed(store)
    _fresh(store)
    _fake_summaries(monkeypatch)
    board = asyncio.run(service.daily_board(store, None, 100, now=NOW))
    assert board.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert "Ежедневная сводка" in board.caption and "Ежедневная сводка" in board.text
    assert "недел" not in (board.text + board.caption).lower()
    assert asyncio.run(service.daily_board(store, None, 100, image=False, now=NOW)).png is None

    def broken(*a, **k):
        raise RuntimeError("рендер упал")

    monkeypatch.setattr(service, "render_daily_image", broken)
    fallback = asyncio.run(service.daily_board(store, None, 100, now=NOW))
    assert fallback.png is None and "Ежедневная сводка" in fallback.text


def test_daily_board_for_a_quiet_day_is_text_only(store, monkeypatch):
    a, _ = _party(store)
    store.add_matches(a.id, [m(1, NOW - 3 * DAY)])
    _fresh(store)
    _fake_summaries(monkeypatch)
    board = asyncio.run(service.daily_board(store, None, 100, now=NOW))
    assert board.png is None and "не было" in board.text


def test_digest_mode_of_stats_board_is_the_daily_board(store, monkeypatch):
    seen = {}

    async def fake_daily(storage, od, chat_id, stratz=None, image=None, now=None):
        seen["args"] = (chat_id, stratz, image)
        return "board"

    monkeypatch.setattr(service, "daily_board", fake_daily)
    assert asyncio.run(service.stats_board(store, None, 100, "digest", "STRATZ", image=False)) == "board"
    assert seen["args"] == (100, "STRATZ", False)


# --- лучшая игра суток -------------------------------------------------------------------------------

BUILD = {"items": [1, 2, 3], "item_times": [600, 1200, 1800], "neutral_item": 4, "shard": True, "shard_time": 1450,
         "scepter": True, "scepter_time": 2100}


def test_best_game_tie_goes_to_the_bigger_net_worth(store):
    a, b = _party(store)
    store.add_matches(a.id, [m(1, NOW - HOUR, k=10, d=2, a=10)])
    store.add_matches(b.id, [m(2, NOW - 2 * HOUR, k=10, d=2, a=10)])
    _details(store, a.id, 1, net_worth=15000)
    _details(store, b.id, 2, net_worth=19000)
    assert build_daily_report(store, 100, NOW)["best_game"]["player"] == "Петя"


def test_no_best_game_without_a_meaningful_one(store):
    a, _ = _party(store)
    store.add_matches(a.id, [m(1, NOW - HOUR, k=1, d=0, a=2)])
    assert build_daily_report(store, 100, NOW)["best_game"] is None
    assert cd.daily_card(build_daily_report(store, 100, NOW), {})["best_game"] is None


def test_daily_text_has_best_game_with_stats_build_and_no_awards(store, monkeypatch):
    from mmrbot import items
    monkeypatch.setattr(items, "ITEM_SLUGS", {1: "blink", 2: "black_king_bar", 3: "aghanims_scepter_x", 4: "trusty_shovel"})
    _seed(store)
    report = build_daily_report(store, 100, NOW)
    report["best_game"]["build"] = BUILD
    text = render_daily(report)
    assert "Лучшая игра суток" in text and "12/1/10" in text and "KDA 22.00" in text
    assert "Нетворс 21.0k" in text and "GPM / XPM 650 / 700" in text and "IMP +12" in text
    assert "Blink 10:00 → Black King Bar 20:00" in text and "Шард 24:10" in text and "Скипетр 35:00" in text
    assert "Награды" not in text and "Лучшие показатели" not in text
    assert "🛒" not in render_daily(build_daily_report(store, 100, NOW))  # билд неизвестен — строки нет


def test_daily_image_with_best_game_is_taller_and_draws_the_build(store):
    from mmrbot.daily_image import render_daily_image
    _seed(store)
    report = build_daily_report(store, 100, NOW)
    plain = _png(render_daily_image(cd.daily_card(report, {})))
    report["best_game"]["build"] = BUILD
    full = _png(render_daily_image(cd.daily_card(report, {}), item_icons={1: b"junk"}))
    assert full.width == WIDTH and full.height > plain.height


def test_daily_board_attaches_the_build_of_the_best_game():
    class Od:
        def get_match_builds(self, match_id):
            return {1: dict(BUILD, bought={})}
    report = {"best_game": {"match": {"match_id": 1, "hero_id": 1}}}
    asyncio.run(service._attach_best_build(Od(), report))
    assert report["best_game"]["build"]["shard"] is True and "bought" not in report["best_game"]["build"]

    class Broken:
        def get_match_builds(self, match_id):
            raise RuntimeError("down")
    report = {"best_game": {"match": {"match_id": 1, "hero_id": 1}}}
    asyncio.run(service._attach_best_build(Broken(), report))
    assert "build" not in report["best_game"]
    asyncio.run(service._attach_best_build(None, report))
