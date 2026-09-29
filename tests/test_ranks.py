from mmrbot.ranks import rank_label


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
