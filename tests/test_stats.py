import pytest

from mmrbot.stats import (
    aggregate,
    current_streak,
    duration_stats,
    estimate_mmr_delta,
    is_ranked_lobby,
    is_win,
    solo_party_split,
    top_heroes,
    winrate_by_hour,
)


def make(slot, radiant_win, k=0, d=0, a=0):
    return {"player_slot": slot, "radiant_win": radiant_win, "kills": k, "deaths": d, "assists": a}


# --- is_win -------------------------------------------------------------

def test_radiant_player_wins_when_radiant_wins():
    assert is_win(player_slot=0, radiant_win=True) is True


def test_radiant_player_loses_when_dire_wins():
    assert is_win(player_slot=4, radiant_win=False) is False


def test_dire_player_wins_when_dire_wins():
    assert is_win(player_slot=128, radiant_win=False) is True


def test_dire_player_loses_when_radiant_wins():
    assert is_win(player_slot=132, radiant_win=True) is False


# --- is_ranked_lobby ----------------------------------------------------

def test_lobby_7_is_ranked():
    assert is_ranked_lobby(7) is True


def test_lobby_0_is_not_ranked():
    assert is_ranked_lobby(0) is False


def test_lobby_none_is_not_ranked():
    assert is_ranked_lobby(None) is False


# --- aggregate ----------------------------------------------------------

def test_aggregate_empty_is_all_zero_without_crash():
    agg = aggregate([])
    assert agg.games == 0
    assert agg.wins == 0
    assert agg.losses == 0
    assert agg.winrate == 0.0
    assert agg.avg_kills == 0.0
    assert agg.kda_ratio == 0.0


def test_aggregate_counts_wins_losses_and_kda():
    matches = [
        make(0, True, k=5, d=2, a=10),    # radiant win
        make(128, False, k=3, d=5, a=7),  # dire win
        make(1, False, k=1, d=8, a=2),    # radiant loss
    ]
    agg = aggregate(matches)
    assert agg.games == 3
    assert agg.wins == 2
    assert agg.losses == 1
    assert agg.winrate == pytest.approx(2 / 3)
    assert agg.avg_kills == pytest.approx(3.0)
    assert agg.avg_deaths == pytest.approx(5.0)
    assert agg.avg_assists == pytest.approx(19 / 3)
    assert agg.kda_ratio == pytest.approx((5 + 3 + 1 + 10 + 7 + 2) / (2 + 5 + 8))


def test_aggregate_kda_guards_zero_deaths():
    matches = [make(0, True, k=10, d=0, a=5)]
    agg = aggregate(matches)
    assert agg.kda_ratio == pytest.approx(15.0)  # (10+5)/max(0,1)


# --- estimate_mmr_delta -------------------------------------------------

def test_mmr_delta_positive():
    assert estimate_mmr_delta(wins=6, losses=4, step=25) == 50


def test_mmr_delta_negative():
    assert estimate_mmr_delta(wins=3, losses=7, step=25) == -100


def test_mmr_delta_custom_step():
    assert estimate_mmr_delta(wins=5, losses=0, step=30) == 150


def test_mmr_delta_zero_when_even():
    assert estimate_mmr_delta(wins=4, losses=4, step=25) == 0


# --- current_streak (матчи по возрастанию времени) ----------------------

def test_streak_empty():
    assert current_streak([]) == ("", 0)


def test_streak_single_win():
    assert current_streak([make(0, True)]) == ("W", 1)


def test_streak_breaks_on_last_result():
    # ...W, W, L  → текущая серия: 1 поражение
    assert current_streak([make(0, True), make(0, True), make(0, False)]) == ("L", 1)


def test_streak_counts_tail_wins():
    # L, W, W, W → 3 победы подряд
    matches = [make(0, False), make(0, True), make(128, False), make(0, True)]
    assert current_streak(matches) == ("W", 3)


# --- top_heroes ---------------------------------------------------------

def hmatch(hero_id, slot, radiant_win):
    m = make(slot, radiant_win)
    m["hero_id"] = hero_id
    return m


def test_top_heroes_empty():
    assert top_heroes([]) == []


def test_top_heroes_counts_and_sorts():
    matches = [
        hmatch(1, 0, True), hmatch(1, 0, False),   # hero 1: 2 игры, 1 победа
        hmatch(2, 0, True), hmatch(2, 128, False),  # hero 2: 2 игры, 2 победы
        hmatch(3, 0, False),                        # hero 3: 1 игра, 0 побед
    ]
    top = top_heroes(matches, k=3)
    assert [h["hero_id"] for h in top] == [2, 1, 3]  # по играм, тай-брейк по винрейту
    assert top[0]["games"] == 2 and top[0]["wins"] == 2
    assert top[1]["winrate"] == pytest.approx(0.5)


# --- winrate_by_hour ----------------------------------------------------

def test_winrate_by_hour_buckets_local_time():
    # 1790000000 → в МСК определённый час; проверяем, что бакетизация по локальному часу работает
    m1 = make(0, True)
    m1["start_time"] = 1790000000
    m2 = make(0, False)
    m2["start_time"] = 1790000000 + 3600  # +1 час
    by_hour = winrate_by_hour([m1, m2], "Europe/Moscow")
    total_games = sum(g for g, w in by_hour.values())
    assert total_games == 2
    assert len(by_hour) == 2  # два разных часа


# --- solo_party_split ---------------------------------------------------

def pmatch(party_size, slot, radiant_win):
    m = make(slot, radiant_win)
    m["party_size"] = party_size
    return m


def test_solo_party_split():
    matches = [
        pmatch(1, 0, True),    # solo win
        pmatch(1, 0, False),   # solo loss
        pmatch(3, 0, True),    # party win
    ]
    split = solo_party_split(matches)
    assert split["solo"] == (2, 1)   # (games, wins)
    assert split["party"] == (1, 1)


def test_solo_party_handles_missing_party_size():
    matches = [make(0, True)]  # без party_size → считаем solo
    split = solo_party_split(matches)
    assert split["solo"] == (1, 1)


# --- duration_stats -----------------------------------------------------

def test_duration_stats_empty():
    d = duration_stats([])
    assert d["avg_minutes"] == 0
    assert d["max_minutes"] == 0


def test_duration_stats_avg_and_max():
    matches = [{"duration": 1800}, {"duration": 3600}]  # 30 и 60 минут
    d = duration_stats(matches)
    assert d["avg_minutes"] == pytest.approx(45.0)
    assert d["max_minutes"] == pytest.approx(60.0)
