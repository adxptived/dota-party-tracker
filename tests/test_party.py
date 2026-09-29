from mmrbot.party import best_duo, together_summary


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


def test_best_duo_picks_pair_with_most_shared_games():
    players = [
        ("Alice", [win(1), loss(2), win(3)]),
        ("Bob", [win(1), loss(2)]),
        ("Carol", [win(1)]),
    ]
    duo = best_duo(players)
    assert set(duo["pair"]) == {"Alice", "Bob"}  # 2 совместных матча
    assert duo["games"] == 2
    assert duo["wins"] == 1


def test_best_duo_none_when_no_shared():
    players = [("Alice", [win(1)]), ("Bob", [win(2)])]
    assert best_duo(players) is None
