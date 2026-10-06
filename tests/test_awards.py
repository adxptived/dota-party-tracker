from mmrbot.awards import compute_period_awards
from mmrbot.heroes import hero_name


def g(t, win=True, k=5, d=3, a=7, perf=None, hero=1):
    return {"start_time": t, "player_slot": 0, "radiant_win": win, "kills": k, "deaths": d, "assists": a,
            "hero_id": hero, "perf_score": perf}


def by_key(awards):
    return {a["key"]: a for a in awards}


def test_no_awards_for_single_player():
    assert compute_period_awards([("A", [g(1), g(2), g(3)])]) == []


def test_period_awards_pick_leaders_from_period_matches():
    a = [g(1, True), g(2, True), g(3, True)]
    b = [g(1, False), g(2, False), g(3, False)]
    r = by_key(compute_period_awards([("A", a), ("B", b)]))
    assert r["winrate"]["player"] == "A" and r["climb"]["player"] == "A"
    assert r["drop"]["player"] == "B"
    assert r["win_streak"]["player"] == "A" and r["loss_streak"]["player"] == "B"


def test_no_award_on_tie_or_equal_values():
    same = [g(1), g(2, False), g(3)]
    r = by_key(compute_period_awards([("A", same), ("B", list(same))]))
    assert "winrate" not in r and "climb" not in r  # поровну — награды нет


def test_average_metrics_need_min_games():
    r = by_key(compute_period_awards(
        [("A", [g(1, perf=0.9)]), ("B", [g(1, False, perf=0.3)])], min_games=3))
    assert "winrate" not in r and "mvp" not in r  # одной игры мало для средних
    assert r["climb"]["player"] == "A"  # а итог MMR за период считается и по одной игре


def test_climb_not_awarded_when_everyone_lost():
    r = by_key(compute_period_awards([("A", [g(1, False)]), ("B", [g(1, False), g(2, False)])]))
    assert "climb" not in r and r["drop"]["player"] == "B"


def test_win_streak_needs_three_games():
    two = [g(1), g(2), g(3, False)]
    r = by_key(compute_period_awards([("A", two), ("B", [g(1, False), g(2, False), g(3, False)])]))
    assert "win_streak" not in r  # серия из двух побед — ещё не награда


def test_mvp_is_best_average_perf():
    a = [g(i, perf=0.7) for i in (1, 2, 3)]
    b = [g(i, perf=0.4) for i in (1, 2, 3)]
    r = by_key(compute_period_awards([("A", a), ("B", b)]))
    assert r["mvp"]["player"] == "A" and "70" in r["mvp"]["detail"]


def test_mvp_skipped_without_perf_data():
    r = by_key(compute_period_awards([("A", [g(i) for i in (1, 2, 3)]), ("B", [g(i, False) for i in (1, 2, 3)])]))
    assert "mvp" not in r


def test_best_game_names_hero_and_score():
    a = [g(1, k=12, d=1, a=9, hero=1), g(2), g(3)]
    b = [g(1, k=4, d=6, a=8), g(2), g(3)]
    r = by_key(compute_period_awards([("A", a), ("B", b)]))
    assert r["best_game"]["player"] == "A"
    assert hero_name(1) in r["best_game"]["detail"] and "12/1/9" in r["best_game"]["detail"]


def test_feeder_only_when_deaths_are_really_high():
    feeder = [g(i, d=12) for i in (1, 2, 3)]
    calm = [g(i, d=5) for i in (1, 2, 3)]
    r = by_key(compute_period_awards([("A", feeder), ("B", calm)]))
    assert r["feeder"]["player"] == "A" and "12.0" in r["feeder"]["detail"]
    mild = [g(i, d=6) for i in (1, 2, 3)]
    r = by_key(compute_period_awards([("A", mild), ("B", [g(i, d=3) for i in (1, 2, 3)])]))
    assert "feeder" not in r  # 6 смертей за игру — не повод для «фидера»


def test_secondary_stat_awards_are_gone():
    a = [g(i, True, perf=0.7) for i in (1, 2, 3)]
    b = [g(i, False, perf=0.4) for i in (1, 2, 3)]
    r = by_key(compute_period_awards([("A", a), ("B", b)]))
    assert not {"gpm", "damage", "assists", "perf", "deaths"} & set(r)


def test_negative_awards_come_last_and_are_flagged():
    a = [g(i, True, perf=0.7, d=2) for i in (1, 2, 3)]
    b = [g(i, False, perf=0.4, d=12) for i in (1, 2, 3)]
    awards = compute_period_awards([("A", a), ("B", b)])
    flags = [bool(x.get("anti")) for x in awards]
    assert True in flags and flags == sorted(flags)
    assert {x["key"] for x in awards if x.get("anti")} == {"drop", "feeder", "loss_streak"}


def test_board_and_weekly_use_period_awards(tmp_path):
    import asyncio, time
    import mmrbot.service as service
    from mmrbot.storage import Storage
    from mmrbot.tracker import build_weekly_report
    from mmrbot.formatting import render_weekly

    st = Storage(str(tmp_path / "a.db"))
    st.get_or_create_chat(1)
    a, b = st.add_player(1, 1, "Вася", None, 0, 0), st.add_player(1, 2, "Петя", None, 0, 0)
    now = int(time.time())

    def row(i, t, win):
        return {"match_id": i, "start_time": t, "player_slot": 0, "radiant_win": win, "lobby_type": 7,
                "kills": 5, "deaths": 3, "assists": 7, "hero_id": 1, "duration": 2400}

    st.add_matches(a.id, [row(i, now - 3600 * i, True) for i in range(1, 4)])
    st.add_matches(b.id, [row(10 + i, now - 3600 * i, False) for i in range(1, 4)])

    class OD:  # сеть не нужна: refresh=False
        pass

    text = asyncio.run(service.render_board(st, OD(), 1, refresh=False))
    assert "Награды за неделю" in text and "Вася" in text
    weekly = render_weekly(build_weekly_report(st, 1, now))
    assert "Лучшие показатели недели" in weekly and "Лучший винрейт" in weekly


def test_pulse_shows_today_when_no_games():
    from mmrbot.formatting import render_party_pulse
    rows = [{"name": "Вася", "games": 3, "wins": 2, "losses": 1, "delta": 25, "winrate": 2 / 3, "kda": 3.0}]
    assert "Сегодня: игр пока не было" in render_party_pulse([], rows, {"records": []})
