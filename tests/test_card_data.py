from mmrbot import card_data as cd
from mmrbot.cards import LOSS, MUTED, WIN
from mmrbot.tracker import PlayerSummary


def _summary(name="Вася", **extra):
    base = dict(
        display_name=name, account_id=1, rank="Legend 5", anchor_mmr=5000, current_mmr=5420, mmr_delta=420,
        games_total=56, wins_total=35, losses_total=21, winrate=0.625, kda_ratio=3.1, avg_kills=8, avg_deaths=5,
        avg_assists=11, games_today=3, wins_today=2, losses_today=1, delta_today=25, rank_tier=55,
        avatar="https://avatars.steamstatic.com/a.jpg", form_long=[True, False, True], anchor_games=56,
        top_heroes=[{"hero_id": 12, "games": 12, "winrate": 0.7}],
    )
    base.update(extra)
    return PlayerSummary(**base)


def test_full_rows_show_mmr_delta_wl_form_and_top_hero():
    (row,) = cd.summary_rows([_summary()], today=False)
    assert row["name"] == "Вася" and row["big"] == "≈5420" and row["rank_tier"] == 55 and row["rank_text"] == "Legend 5"
    assert row["sub"] == "+420 за 56 игр" and row["sub_color"] == WIN
    assert (row["wins"], row["losses"]) == (35, 21) and row["form"] == [True, False, True]
    assert row["hero_id"] == 12 and row["hero_note"] == "×12" and row["avatar"].startswith("https://")


def test_today_rows_use_today_numbers():
    (row,) = cd.summary_rows([_summary(delta_today=-25, wins_today=1, losses_today=2)], today=True)
    assert row["big"] == "≈5420" and row["sub"] == "−25 сегодня" and row["sub_color"] == LOSS
    assert (row["wins"], row["losses"]) == (1, 2)
    (idle,) = cd.summary_rows([_summary(games_today=0, wins_today=0, losses_today=0, delta_today=0)], today=True)
    assert idle["sub"] == "сегодня игр не было" and idle["sub_color"] == MUTED


def test_player_without_mmr_or_games_is_still_a_row():
    (row,) = cd.summary_rows([_summary(current_mmr=None, anchor_mmr=None, games_total=0, wins_total=0, losses_total=0,
                                       anchor_games=0, top_heroes=[], form_long=[], rank_tier=None, rank="Без ранга",
                                       history_closed=True)], today=False)
    assert row["big"] == "—" and row["sub"] == "история закрыта" and row["hero_id"] is None and row["form"] == []


def test_period_rows_use_delta_as_big_number_and_join_player_info():
    rows = [{"name": "Вася", "games": 12, "wins": 8, "losses": 4, "delta": 100, "winrate": 0.66, "kda": 3.25},
            {"name": "Петя", "games": 0, "wins": 0, "losses": 0, "delta": 0, "winrate": 0.0, "kda": 0.0}]
    info = {"Вася": {"avatar": "u", "rank_tier": 74, "rank_text": "Divine 4", "mmr": 6000}}
    out = cd.period_rows(rows, info)
    assert out[0]["big"] == "+100" and out[0]["big_color"] == WIN and out[0]["sub"] == "12 игр · KDA 3.25"
    assert out[0]["avatar"] == "u" and out[0]["rank_tier"] == 74 and out[0]["rank_text"] == "Divine 4"
    assert out[1]["big"] == "0" and out[1]["sub"] == "игр не было" and out[1]["rank_tier"] is None


def test_party_tiles_today_week_leader_and_streak():
    summaries = [_summary("А", games_today=3, wins_today=2, losses_today=1, delta_today=25),
                 _summary("Б", games_today=1, wins_today=0, losses_today=1, delta_today=-25)]
    week = [{"name": "А", "games": 9, "wins": 6, "losses": 3, "delta": 75, "winrate": .66, "kda": 3},
            {"name": "Б", "games": 3, "wins": 1, "losses": 2, "delta": -25, "winrate": .33, "kda": 2}]
    tiles = cd.party_tiles(summaries, week)
    labels = [t["label"] for t in tiles]
    assert labels == ["Сегодня", "За неделю", "Лидер недели"]
    assert tiles[0]["value"] == "4 игры" and "2–2" in tiles[0]["sub"] and tiles[0]["color"] == MUTED
    assert tiles[1]["value"] == "12 игр" and "7–5" in tiles[1]["sub"]
    assert tiles[2]["value"] == "А" and "+75" in tiles[2]["sub"]


def test_party_tiles_for_idle_party():
    tiles = cd.party_tiles([_summary(games_today=0, wins_today=0, losses_today=0, delta_today=0)], [])
    assert tiles[0]["value"] == "игр нет" and tiles[1]["value"] == "игр нет"
    assert len(tiles) == 2  # лидера недели нет — плитки нет


def test_records_and_awards_items_keep_only_pulse_records():
    week_records = {"records": [
        {"key": "gpm", "title": "Макс. GPM", "text": "812 GPM", "player": "Вася", "match": {"hero_id": 12}},
        {"key": "tower_damage", "title": "Макс. урон по строениям", "text": "9k", "player": "Петя", "match": {"hero_id": 1}},
        {"key": "imp", "title": "Лучший IMP", "text": "IMP +64", "player": "Ира", "match": {"hero_id": 35}},
    ]}
    items = cd.record_items(week_records)
    assert [i["label"] for i in items] == ["Макс. GPM", "Лучший IMP"]
    assert items[0] == {"label": "Макс. GPM", "value": "812 GPM", "player": "Вася", "hero_id": 12}
    assert cd.record_items({}) == []
    awards = cd.award_items([{"key": "x", "emoji": "🏅", "title": "Больше всех играл", "player": "Вася", "detail": "31 игра"}])
    assert awards == [{"title": "Больше всех играл", "player": "Вася", "detail": "31 игра"}]


def test_leader_caption_full_and_period():
    s = [_summary("Вася"), _summary("Петя", current_mmr=4000)]
    week = [{"name": "Вася", "games": 9, "wins": 6, "losses": 3, "delta": 75, "winrate": .66, "kda": 3}]
    assert cd.leader_caption(s, "stats") == "🏆 <b>Рейтинг</b> · Лидер: <b>Вася</b> ≈5420"  # дельта недели — в плитке
    assert "сегодня" in cd.leader_caption(s, "today")
    assert cd.leader_caption([], "stats") == "🏆 <b>Рейтинг</b>"
    rows = [{"name": "Вася", "games": 12, "wins": 8, "losses": 4, "delta": 100, "winrate": .66, "kda": 3.25}]
    assert cd.period_caption(rows, "week") == "🗓️ <b>За неделю</b> · Лидер: <b>Вася</b> +100 (8–4)"
    assert cd.period_caption([{"name": "Вася", "games": 0, "wins": 0, "losses": 0, "delta": 0, "winrate": 0, "kda": 0}],
                             "month") == "📆 <b>За месяц</b> · игр не было"


def test_names_are_escaped_in_captions():
    s = [_summary("<b>&")]
    assert "&lt;b&gt;&amp;" in cd.leader_caption(s, "stats")


# --- карточка игрока ---------------------------------------------------------------------------

def _full_summary(**extra):
    base = dict(
        steam_name="shinoame_steam", avg_perf=0.73, streak_type="W", streak_len=4, avg_gpm_window=540.0,
        avg_net_worth_window=18200.0, avg_hero_damage_window=21050.0, detail_games=40, avg_duration_min=36.4,
        solo=(20, 12), party=(36, 23), best_hour=(21, 0.7), worst_hour=(3, 0.3), last_game={
            "hero_id": 12, "kills": 20, "deaths": 2, "assists": 10, "kda": 15.0, "won": True},
        lobby_rank=55, skill={"gold_per_min": 0.8, "xp_per_min": 0.6, "hero_damage_per_min": 0.3, "kills_per_min": 0.5},
        top_heroes=[{"hero_id": 12, "games": 12, "wins": 8, "winrate": 8 / 12}], longest_win_streak=7, hero_pool=23,
        recent_games=[{"hero_id": 12, "won": True, "kills": 9, "deaths": 1, "assists": 14, "duration": 2280,
                       "start_time": 1_700_000_000, "delta": 25, "double_down": False}],
    )
    base.update(extra)
    return _summary(**base)


def test_player_card_has_header_tiles_charts_and_blocks():
    card = cd.player_card(_full_summary(), {"size": 5, "power_rank": 2}, [25, 0, 25, 50], "заметка")
    assert card["name"] == "Вася" and card["mmr_text"] == "≈5420" and card["mmr_delta"] == 420
    assert card["delta_note"] == "за 56 игр" and card["perf"] == 73 and card["streak"] == ("W", 4)
    assert [t["label"] for t in card["tiles"]] == ["Результат", "KDA", "GPM", "Урон по героям", "Средняя игра"]
    assert card["tiles"][0]["value"] == "35–21" and card["tiles"][2]["value"] == "540" and card["tiles"][3]["value"] == "21.1k"
    assert card["tiles"][2]["sub"] == "по 40 из 56"
    assert card["series"] == [5025, 5000, 5025, 5050] and "последние 4 игры" in card["series_label"]
    assert card["split"] == [{"label": "Соло", "wins": 12, "losses": 8}, {"label": "В группе", "wins": 23, "losses": 13}]
    assert "hours" not in card and "skills" not in card  # «лучший час» по трём играм и перцентили навыков убраны
    assert [label for label, *_ in card["facts"]] == ["Лучшая серия", "Пул героев", "Средняя игра"]
    assert card["facts"][0][1] == "7 побед" and card["facts"][1][1] == "23 героя" and card["facts"][2][1] == "36 мин"
    assert card["heroes"][0]["name"] and card["last_game"]["kda"] == 15.0 and card["last_game"]["won"] is True
    (game,) = card["recent"]
    assert game["won"] and game["delta"] == 25 and game["minutes"] == 38 and game["when"] == "14.11" and card["recent_mmr"]
    assert card["lobby_rank"] == 55 and card["lobby_text"] == "Legend 5"
    assert card["standing"] == "#2 из 5 в чате по силе" and card["note"] == "заметка" and card["warnings"] == []


def test_player_card_warnings_and_missing_data():
    card = cd.player_card(_full_summary(mmr_drift=True, history_closed=True, current_mmr=None, anchor_mmr=None,
                                        avg_perf=None, avg_gpm_window=None, best_hour=None, last_game=None,
                                        skill={}, lobby_rank=None, solo=(0, 0), party=(0, 0), top_heroes=[],
                                        streak_len=0), None, [3, -3])
    assert any("расходится" in w for w in card["warnings"]) and any("закрыта" in w for w in card["warnings"])
    assert card["mmr_text"] == "≈ ?" and card["perf"] is None and card["streak"] is None
    assert card["tiles"][2]["value"] == "—" and card["series"] == [3, -3] and "±MMR" in card["series_label"]
    assert not card["split"] and "last_game" not in card
    assert "standing" not in card and "lobby_rank" not in card


def test_player_card_partial_note_counts_each_metric_separately():
    card = cd.player_card(_full_summary(detail_games=40, damage_games=56))
    tiles = {t["label"]: t for t in card["tiles"]}
    assert tiles["GPM"]["sub"] == "по 40 из 56" and tiles["Урон по героям"]["sub"] is None  # урон известен по всем


def test_player_card_recent_hides_mmr_without_anchor():
    card = cd.player_card(_full_summary(anchor_mmr=None))
    assert card["recent"] and card["recent_mmr"] is False


def test_player_card_without_games_is_just_header_and_notice():
    card = cd.player_card(_summary(games_total=0, wins_total=0, losses_total=0, anchor_games=0))
    assert "tiles" not in card and any("пока нет" in w for w in card["warnings"]) and card["mmr_delta"] is None


def test_player_caption():
    text = cd.player_caption(_full_summary())
    assert text == "🪪 <b>Вася</b> · Legend 5 · ≈5420 (+420)"  # одна строка: игры, W–L и KDA — на самой карточке
    assert "\n" not in cd.player_caption(_summary(games_total=0, current_mmr=None))
    assert "&lt;b&gt;" in cd.player_caption(_summary(display_name="<b>"))


def test_rating_rows_carry_streak_from_three_games():
    (hot,) = cd.summary_rows([_summary(streak_type="W", streak_len=4)], today=False)
    (calm,) = cd.summary_rows([_summary(streak_type="L", streak_len=2)], today=False)
    assert hot["streak"] == ("W", 4) and calm["streak"] is None


def test_player_card_last_game_details_and_hero_kda():
    last = {"hero_id": 12, "kills": 20, "deaths": 2, "assists": 10, "kda": 15.0, "won": True,
            "start_time": 1_700_000_000, "duration": 2280, "gpm": 640.4, "hero_damage": 31250}
    heroes = [{"hero_id": 12, "games": 12, "wins": 8, "winrate": 8 / 12, "kda": 4.13}]
    card = cd.player_card(_full_summary(last_game=last, top_heroes=heroes), tz="Europe/Moscow")
    assert card["last_game"]["when"] == "15.11 01:13"
    assert card["last_game"]["stats"] == [("Время", "38 мин"), ("GPM", "640"), ("Урон", "31.2k")]
    assert card["heroes"][0]["kda"] == 4.13
    bare = cd.player_card(_full_summary())  # старая запись без подробностей — блок как раньше
    assert bare["last_game"]["stats"] == [] and bare["last_game"]["when"] is None and bare["heroes"][0]["kda"] is None


def test_player_card_last_tile_is_position_then_role_then_duration():
    tile = cd.player_card(_full_summary(main_position=(5, 34, 49), role_style="саппорт / роумер"))["tiles"][-1]
    assert tile == {"label": "Позиция", "value": "Pos 5", "sub": "Саппорт · 69% игр"}
    tile = cd.player_card(_full_summary(role_style="саппорт / роумер"))["tiles"][-1]
    assert (tile["label"], tile["value"]) == ("Роль", "Саппорт")
    assert cd.player_card(_full_summary())["tiles"][-1]["label"] == "Средняя игра"


def test_match_list_rows_number_buttons_delta_and_extras():
    matches = [
        {"match_id": 2, "start_time": 1_700_000_000, "player_slot": 0, "radiant_win": True, "hero_id": 11, "kills": 10,
         "deaths": 5, "assists": 12, "duration": 2468, "position": 2, "gpm": 536.4, "last_hits": 295, "double_down": 1},
        {"match_id": 1, "start_time": 1_699_990_000, "player_slot": 128, "radiant_win": True, "hero_id": 1},
    ]
    rows = cd.match_list_rows(matches, 0, 25, "UTC", current=2)
    assert [r["n"] for r in rows] == [1, 2] and rows[1]["current"] and not rows[0]["current"]
    assert rows[0]["delta"] == 50 and rows[0]["double_down"] and rows[1]["delta"] == -25 and not rows[1]["won"]
    assert rows[0]["extra"] == "P2 · 536 GPM · 295 крипов" and rows[0]["minutes"] == 41 and rows[1]["extra"] is None
    assert cd.match_list_rows(matches, 0, 25, show_delta=False)[0]["delta"] is None
    text = cd.match_list_text("<Вася>", rows, 0, 2)
    assert "&lt;Вася&gt;" in text and "1. 🏆 Shadow Fiend 10/5/12 · +50 ×2" in text and "2. 💀" in text
    assert "пока нет" in cd.match_list_text("Вася", [], 0, 0)
