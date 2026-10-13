from mmrbot.ranks import rank_emoji, rank_label


def test_herald_one():
    assert rank_label(11) == "Herald 1"


def test_herald_five():
    assert rank_label(15) == "Herald 5"


def test_legend_five():
    assert rank_label(55) == "Legend 5"


def test_divine_five():
    assert rank_label(75) == "Divine 5"


def test_ancient_three():
    assert rank_label(63) == "Ancient 3"


def test_immortal_no_leaderboard():
    assert rank_label(80) == "Immortal"


def test_immortal_ignores_star_digit():
    # Immortal реально всегда 80, но не должны падать на 8x
    assert rank_label(81) == "Immortal"


def test_immortal_with_leaderboard_rank():
    assert rank_label(80, leaderboard_rank=123) == "Immortal #123"


def test_none_is_uncalibrated():
    assert rank_label(None) == "Без ранга"


def test_zero_is_uncalibrated():
    assert rank_label(0) == "Без ранга"


# --- rank_emoji ---------------------------------------------------------

def test_emoji_immortal():
    assert rank_emoji(80) == "🔱"


def test_emoji_divine():
    assert rank_emoji(75) == "💎"


def test_emoji_ancient():
    assert rank_emoji(63) == "🟣"


def test_emoji_none_is_empty():
    assert rank_emoji(None) == ""
    assert rank_emoji(0) == ""


def test_mmr_rank_mismatch_detects_drift():
    from mmrbot.ranks import mmr_rank_mismatch, rank_mmr_range
    assert rank_mmr_range(None) is None and rank_mmr_range(0) is None
    assert mmr_rank_mismatch(None, 55) is False and mmr_rank_mismatch(3200, None) is False
    assert mmr_rank_mismatch(3300, 52) is False        # Legend 2 ≈ 3234–3388
    assert mmr_rank_mismatch(4500, 52) is True         # оценка ушла на пол-медали вверх
    assert mmr_rank_mismatch(2000, 52) is True
    assert mmr_rank_mismatch(5900, 81) is False        # Immortal — только нижняя граница
    assert mmr_rank_mismatch(4000, 81) is True


def test_average_rank_tier_all_immortal():
    from mmrbot.ranks import average_rank_tier
    assert average_rank_tier([80] * 10) == 80


def test_average_rank_tier_mixed_and_skips_uncalibrated():
    from mmrbot.ranks import average_rank_tier
    assert average_rank_tier([75, 75, None, 0]) == 75
    assert average_rank_tier([71, 75]) == 73
    assert average_rank_tier([75, 80, 80]) == 80
    assert average_rank_tier([None, 0]) is None


def test_suggest_step_fits_medal_middle():
    from mmrbot.ranks import suggest_step
    # старт 3000, +40 побед в балансе при шаге 25 → оценка 4000; середина Legend 5 (3696–3850) ≈ 3773 → шаг ≈ 20
    assert suggest_step(3000, 0, 25 * 40, 25, 55) == 20
    assert suggest_step(3000, 0, 25 * 5, 25, 55) is None        # мало игр — не подсказываем
    assert suggest_step(None, 0, 1000, 25, 55) is None          # MMR не задан
    assert suggest_step(3000, 0, 1000, 25, None) is None        # медали нет
    assert suggest_step(3000, 0, 25 * 40, 25, 80) is None or 10 <= suggest_step(3000, 0, 25 * 40, 25, 80) <= 60
    assert suggest_step(1000, 0, 25 * 10, 25, 80) is None       # нужен шаг больше 60 — это не про шаг
    assert suggest_step(3773 - 25 * 40, 0, 25 * 40, 25, 55) is None  # текущий шаг и так подходит


def test_player_card_drift_warning_suggests_step():
    from mmrbot import card_data as cd
    from mmrbot.tracker import PlayerSummary
    s = PlayerSummary(display_name="Вася", account_id=1, rank="Legend 5", anchor_mmr=3000, current_mmr=4000,
                      mmr_delta=1000, games_total=60, wins_total=50, losses_total=10, winrate=0.83, kda_ratio=3,
                      avg_kills=1, avg_deaths=1, avg_assists=1, games_today=0, wins_today=0, losses_today=0,
                      delta_today=0, rank_tier=55, mmr_drift=True, mmr_step=25, anchor_games=60)
    warning = cd.player_card(s)["warnings"][0]
    assert "/setmmr" in warning and "шаг ±20 (/setstep 20)" in warning
