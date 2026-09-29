import pytest

from mmrbot.stats import aggregate, estimate_mmr_delta, is_ranked_lobby, is_win


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
