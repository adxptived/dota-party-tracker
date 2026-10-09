from mmrbot.awards import compute_period_awards


def g(t, win=True, k=5, d=3, a=7, gpm=None, dmg=None, perf=None):
    return {"start_time": t, "player_slot": 0, "radiant_win": win, "kills": k, "deaths": d, "assists": a,
            "gpm": gpm, "hero_damage": dmg, "perf_score": perf}


def by_key(awards):
    return {a["key"]: a for a in awards}


def test_no_awards_for_single_player():
    assert compute_period_awards([("A", [g(1), g(2), g(3)])]) == []


def test_period_awards_pick_leaders_from_period_matches():
    a = [g(1, True, gpm=700), g(2, True, gpm=650), g(3, True, gpm=600)]
    b = [g(1, False, gpm=400), g(2, False, gpm=420), g(3, False, gpm=380)]
    r = by_key(compute_period_awards([("A", a), ("B", b)]))
    assert r["winrate"]["player"] == "A" and r["gpm"]["player"] == "A"
    assert r["climb"]["player"] == "A" and r["drop"]["player"] == "B"
    assert r["win_streak"]["player"] == "A" and r["loss_streak"]["player"] == "B"


def test_no_award_on_tie_or_equal_values():
    same = [g(1), g(2, False), g(3)]
    r = by_key(compute_period_awards([("A", same), ("B", list(same))]))
    assert "winrate" not in r and "climb" not in r  # поровну — отличия нет


def test_average_metrics_need_min_games():
    r = by_key(compute_period_awards([("A", [g(1, gpm=900)]), ("B", [g(1, False, gpm=300)])], min_games=3))
    assert "gpm" not in r and "winrate" not in r  # одной игры мало для средних
    assert r["climb"]["player"] == "A"  # а итог MMR за период считается и по одной игре


def test_climb_not_awarded_when_everyone_lost():
    r = by_key(compute_period_awards([("A", [g(1, False)]), ("B", [g(1, False), g(2, False)])]))
    assert "climb" not in r and r["drop"]["player"] == "B"


def test_board_and_weekly_use_period_awards(tmp_path):
    import asyncio
    import time
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

    text = asyncio.run(service.render_board(st, OD(), 1, refresh=False, awards_period="day"))
    assert "Награды за сутки" in text and "Вася" in text
    weekly = render_weekly(build_weekly_report(st, 1, now))
    assert "Лучшие показатели недели" in weekly and "Лучший винрейт" in weekly


def test_digest_pulse_shows_last_24h_instead_of_today():
    from mmrbot.formatting import render_party_pulse
    rows = [{"name": "Вася", "games": 3, "wins": 2, "losses": 1, "delta": 25, "winrate": 2 / 3, "kda": 3.0}]
    text = render_party_pulse([], rows, {"records": []}, day_rows=rows)
    assert "За сутки: 3" in text and "Сегодня" not in text
    assert "Сегодня: игр пока не было" in render_party_pulse([], rows, {"records": []})


# --- нормализация по герою/роли (пункт 17) --------------------------------------------------

import json  # noqa: E402

from mmrbot.awards import compute_standings  # noqa: E402
from mmrbot.stats import match_benchmark  # noqa: E402


def gb(t, gpm, dmg, gpm_pct=None, dmg_pct=None):
    bench = {}
    if gpm_pct is not None:
        bench["gold_per_min"] = gpm_pct
    if dmg_pct is not None:
        bench["hero_damage_per_min"] = dmg_pct
    return g(t, gpm=gpm, dmg=dmg) | {"hero_damage": dmg, "bench_json": json.dumps(bench) if bench else None}


def nomination(standings, key):
    return next((s for s in standings if s["key"] == key), None)


def test_match_benchmark_reads_percentile_and_survives_garbage():
    assert match_benchmark({"bench_json": '{"gold_per_min": 0.83}'}, "gold_per_min") == 0.83
    assert match_benchmark({"bench_json": '{"gold_per_min": null}'}, "gold_per_min") is None
    assert match_benchmark({"bench_json": "{}"}, "gold_per_min") is None
    assert match_benchmark({"bench_json": "не json"}, "gold_per_min") is None
    assert match_benchmark({"bench_json": None}, "gold_per_min") is None and match_benchmark({}, "gold_per_min") is None


def test_support_can_win_gpm_and_damage_by_percentile_of_own_hero():
    carry = [gb(i, 700, 30000, 0.50, 0.45) for i in range(1, 4)]      # много фарма, но для кора это норма
    support = [gb(i, 380, 12000, 0.92, 0.88) for i in range(1, 4)]    # мало фарма, но лучше почти всех саппортов
    standings = compute_standings([("Кор", carry), ("Саппорт", support)])
    gpm, dmg = nomination(standings, "gpm"), nomination(standings, "damage")
    assert gpm["entries"][0]["player"] == "Саппорт" and "380 GPM" in gpm["entries"][0]["text"]
    assert "92%" in gpm["entries"][0]["text"]
    assert dmg["entries"][0]["player"] == "Саппорт" and "12.0k" in dmg["entries"][0]["text"]
    assert "героя" in gpm["title"]  # из названия ясно, что это не сырой GPM


def test_raw_gpm_is_used_when_benchmarks_are_missing():
    carry = [gb(i, 700, 30000) for i in range(1, 4)]
    support = [gb(i, 380, 12000) for i in range(1, 4)]
    gpm = nomination(compute_standings([("Кор", carry), ("Саппорт", support)]), "gpm")
    assert gpm["entries"][0]["player"] == "Кор" and gpm["title"] == "Наибольший GPM"


def test_one_player_with_benchmarks_is_not_compared_with_raw_numbers():
    with_bench = [gb(i, 380, 12000, 0.9, 0.9) for i in range(1, 4)]
    without = [gb(i, 700, 30000) for i in range(1, 4)]
    gpm = nomination(compute_standings([("Саппорт", with_bench), ("Кор", without)]), "gpm")
    assert gpm["title"] == "Наибольший GPM"  # сравнивать проценты не с кем — прежний способ
    assert gpm["entries"][0]["player"] == "Кор"


def test_player_with_too_few_benchmarked_games_is_left_out_of_relative_gpm():
    a = [gb(i, 400, 12000, 0.9, 0.9) for i in range(1, 4)]
    b = [gb(i, 700, 30000, 0.5, 0.5) for i in range(1, 4)]
    c = [gb(1, 900, 40000, 0.99, 0.99), gb(2, 900, 40000), gb(3, 900, 40000)]  # процент только в одной игре
    gpm = nomination(compute_standings([("A", a), ("B", b), ("C", c)]), "gpm")
    assert [e["player"] for e in gpm["entries"]] == ["A", "B"]
