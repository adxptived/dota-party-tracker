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
    assert cd.leader_caption(s, week, "stats") == "🏆 <b>Рейтинг</b> · Лидер: <b>Вася</b> ≈5420 (+75 за неделю)"
    assert cd.leader_caption(s, [], "stats") == "🏆 <b>Рейтинг</b> · Лидер: <b>Вася</b> ≈5420 (+420 за 56 игр)"
    assert "сегодня" in cd.leader_caption(s, week, "today")
    assert cd.leader_caption([], [], "stats") == "🏆 <b>Рейтинг</b>"
    rows = [{"name": "Вася", "games": 12, "wins": 8, "losses": 4, "delta": 100, "winrate": .66, "kda": 3.25}]
    assert cd.period_caption(rows, "week") == "🗓️ <b>За неделю</b> · Лидер: <b>Вася</b> +100 (8–4)"
    assert cd.period_caption([{"name": "Вася", "games": 0, "wins": 0, "losses": 0, "delta": 0, "winrate": 0, "kda": 0}],
                             "month") == "📆 <b>За месяц</b> · игр не было"


def test_names_are_escaped_in_captions():
    s = [_summary("<b>&")]
    assert "&lt;b&gt;&amp;" in cd.leader_caption(s, [], "stats")
