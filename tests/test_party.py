from mmrbot.party import together_summary


def wm(match_id, slot, radiant_win):
    return {"match_id": match_id, "player_slot": slot, "radiant_win": radiant_win}


def win(match_id):
    return wm(match_id, 0, True)  # Radiant победа


def loss(match_id):
    return wm(match_id, 0, False)  # Radiant поражение


def test_together_summary_counts_shared_matches():
    players = [
        ("Alice", [win(1), loss(2), win(3)]),
        ("Bob", [win(1), loss(2), win(4)]),
        ("Carol", [win(1)]),
    ]
    s = together_summary(players)
    assert s["games"] == 2   # матчи 1 и 2 (у >=2 игроков)
    assert s["wins"] == 1    # матч 1 победа
    assert s["losses"] == 1  # матч 2 поражение


def test_together_summary_skips_opposite_teams():
    players = [
        ("Alice", [win(5)]),                 # Radiant, победа
        ("Dave", [wm(5, 128, True)]),         # Dire в том же матче → поражение (разные команды)
    ]
    s = together_summary(players)
    assert s["games"] == 0  # противоположные команды не считаем совместной игрой


def test_together_summary_empty():
    assert together_summary([]) == {"games": 0, "wins": 0, "losses": 0}


def test_together_counts_same_side_subgroup_when_split():
    # A,B на Radiant (победа), C на Dire — A и B сыграли вместе на одной стороне.
    players = [
        ("A", [wm(50, 0, True)]),
        ("B", [wm(50, 1, True)]),
        ("C", [wm(50, 128, True)]),
    ]
    s = together_summary(players)
    assert s["games"] == 1
    assert s["wins"] == 1


def test_together_skips_even_split():
    # 2 на 2 — неоднозначно, не считаем.
    players = [
        ("A", [wm(60, 0, True)]),
        ("B", [wm(60, 1, True)]),
        ("C", [wm(60, 128, True)]),
        ("D", [wm(60, 129, True)]),
    ]
    assert together_summary(players)["games"] == 0


# --- together_report: составы, герои, последние игры -----------------------

from mmrbot.party import together_report


def tm(match_id, t, slot=0, radiant_win=True, hero=1, k=5, d=3, a=7):
    return {"match_id": match_id, "start_time": t, "player_slot": slot, "radiant_win": radiant_win,
            "hero_id": hero, "kills": k, "deaths": d, "assists": a}


def test_report_groups_matches_by_exact_lineup():
    a = [tm(1, 10), tm(2, 20), tm(3, 30, radiant_win=False), tm(4, 40)]
    b = [tm(1, 10), tm(2, 20), tm(3, 30, radiant_win=False)]
    c = [tm(3, 30, radiant_win=False), tm(5, 50)]
    r = together_report([("A", a), ("B", b), ("C", c)])
    assert (r["games"], r["wins"], r["losses"]) == (3, 2, 1)
    lineups = {tuple(x["names"]): x for x in r["lineups"]}
    assert lineups[("A", "B")]["games"] == 2 and lineups[("A", "B")]["wins"] == 2
    assert lineups[("A", "B", "C")]["games"] == 1 and lineups[("A", "B", "C")]["losses"] == 1
    assert r["lineups"][0]["names"] == ["A", "B"]  # сначала самый частый состав
    assert lineups[("A", "B")]["last_ts"] == 20


def test_report_ignores_opponents_and_counts_solo_games():
    a = [tm(1, 10, slot=0), tm(2, 20)]
    b = [tm(1, 10, slot=128)]  # тот же матч, но против — это не «вместе»
    r = together_report([("A", a), ("B", b)])
    assert r["games"] == 0 and r["lineups"] == []
    assert (r["solo_games"], r["solo_wins"]) == (3, 2)  # A: 2 победы, B: поражение


def test_report_split_party_counts_each_side_separately():
    rad = [tm(1, 10, slot=0), ]
    r = together_report([("A", rad), ("B", [tm(1, 10, slot=1)]),
                         ("C", [tm(1, 10, slot=128)]), ("D", [tm(1, 10, slot=129)])])
    assert r["games"] == 2 and (r["wins"], r["losses"]) == (1, 1)
    assert {tuple(x["names"]) for x in r["lineups"]} == {("A", "B"), ("C", "D")}


def test_report_since_ts_limits_period():
    a, b = [tm(1, 10), tm(2, 100)], [tm(1, 10), tm(2, 100)]
    r = together_report([("A", a), ("B", b)], since_ts=50)
    assert r["games"] == 1 and r["recent"][0]["match_id"] == 2


def test_report_lineup_heroes_and_recent_games():
    a = [tm(1, 10, hero=14), tm(2, 20, hero=14), tm(3, 30, hero=5, k=12, d=1, a=9)]
    b = [tm(1, 10, hero=26), tm(2, 20, hero=31), tm(3, 30, hero=26)]
    r = together_report([("A", a), ("B", b)])
    heroes = r["lineups"][0]["heroes"]
    assert heroes[0] == {"hero_id": 14, "games": 2} and heroes[1] == {"hero_id": 26, "games": 2}
    assert [g["match_id"] for g in r["recent"]] == [3, 2, 1]  # новые сверху
    first = r["recent"][0]
    assert first["win"] is True and first["start_time"] == 30
    assert first["players"][0] == {"name": "A", "hero_id": 5, "kills": 12, "deaths": 1, "assists": 9}


def test_report_same_names_do_not_merge():
    r = together_report([("A", [tm(1, 10)]), ("A", [tm(1, 10)])])
    assert r["games"] == 1 and r["lineups"][0]["names"] == ["A", "A"]


def test_report_empty():
    r = together_report([])
    assert r["games"] == 0 and r["lineups"] == [] and r["recent"] == []
