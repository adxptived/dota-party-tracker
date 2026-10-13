import pytest

from mmrbot.plus_levels import plus_level, plus_tier


@pytest.mark.parametrize("xp,level", [
    (0, 0), (49, 0), (50, 1), (349, 1), (350, 2), (1850, 5), (1851, 5), (2750, 6), (8750, 11), (10450, 12),
    (20450, 17), (22950, 18), (40050, 24), (46850, 25), (64050, 29), (72049, 29), (72050, 30), (999999, 30),
])
def test_plus_level_from_xp(xp, level):
    assert plus_level(xp) == level


@pytest.mark.parametrize("bad", [None, True, "5000", -5, float("nan")])
def test_plus_level_unknown_xp_is_none(bad):
    assert plus_level(bad) is None


@pytest.mark.parametrize("level,tier", [
    (0, None), (1, "Bronze"), (5, "Bronze"), (6, "Silver"), (11, "Silver"), (12, "Gold"), (17, "Gold"),
    (18, "Platinum"), (24, "Platinum"), (25, "Master"), (29, "Master"), (30, "Grandmaster"), (None, None),
])
def test_plus_tier(level, tier):
    assert plus_tier(level) == tier
