from mmrbot.formatting import format_delta, render_leaderboard
from mmrbot.tracker import PlayerSummary


def summary(**kw):
    base = dict(
        display_name="Вася",
        account_id=42,
        rank="Divine 5",
        anchor_mmr=5000,
        current_mmr=5050,
        mmr_delta=50,
        games_total=4,
        wins_total=3,
        losses_total=1,
        winrate=0.75,
        kda_ratio=4.2,
        avg_kills=8.0,
        avg_deaths=4.0,
        avg_assists=7.0,
        games_today=2,
        wins_today=2,
        losses_today=0,
        delta_today=50,
    )
    base.update(kw)
    return PlayerSummary(**base)


# --- format_delta -------------------------------------------------------

def test_format_delta_positive():
    assert format_delta(50) == "+50"


def test_format_delta_negative():
    assert format_delta(-100) == "-100"


def test_format_delta_zero():
    assert format_delta(0) == "0"


# --- render_leaderboard -------------------------------------------------

def test_leaderboard_empty_gives_hint():
    text = render_leaderboard([])
    assert "/add" in text


def test_leaderboard_shows_name_rank_mmr_and_estimate_marker():
    text = render_leaderboard([summary()])
    assert "Вася" in text
    assert "Divine 5" in text
    assert "5050" in text
    assert "+50" in text
    assert "≈" in text  # оценка помечена
    assert "75%" in text


def test_leaderboard_orders_and_numbers_players():
    text = render_leaderboard([summary(display_name="A"), summary(display_name="B")])
    assert text.index("A") < text.index("B")
    assert "1." in text and "2." in text


def test_leaderboard_negative_delta_shows_minus():
    text = render_leaderboard([summary(current_mmr=4900, mmr_delta=-100)])
    assert "-100" in text
    assert "4900" in text


def test_today_view_marks_no_games():
    text = render_leaderboard([summary(games_today=0, wins_today=0, losses_today=0, delta_today=0)], today_only=True)
    assert "Вася" in text
    # без игр сегодня — не показываем ложную дельту, а пишем про отсутствие игр
    assert "без игр" in text.lower()


def test_player_without_anchor_mmr_shows_question_not_crash():
    text = render_leaderboard([summary(anchor_mmr=None, current_mmr=None, mmr_delta=25)])
    assert "Вася" in text
    assert "+25" in text
