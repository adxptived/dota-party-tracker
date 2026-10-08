from mmrbot.awards import compute_period_awards, compute_standings, contest_points


def g(t, win=True, k=5, d=3, a=7, gpm=None, dmg=None, perf=None):
    return {"start_time": t, "player_slot": 0, "radiant_win": win, "kills": k, "deaths": d, "assists": a,
            "gpm": gpm, "hero_damage": dmg, "perf_score": perf}


def by_key(standings):
    return {s["key"]: s for s in standings}


def three_players():
    a = [g(1, True, gpm=700), g(2, True, gpm=650), g(3, True, gpm=600)]
    b = [g(1, True, gpm=500), g(2, False, gpm=520), g(3, False, gpm=480)]
    c = [g(1, False, gpm=400), g(2, False, gpm=420), g(3, False, gpm=380)]
    return [("A", a), ("B", b), ("C", c)]


def test_no_standings_for_single_player():
    assert compute_standings([("A", [g(1), g(2), g(3)])]) == []


def test_entries_are_sorted_best_first_with_places():
    r = by_key(compute_standings(three_players()))
    gpm = r["gpm"]["entries"]
    assert [e["player"] for e in gpm] == ["A", "B", "C"]
    assert [e["place"] for e in gpm] == [1, 2, 3]
    assert gpm[0]["text"].startswith("650")  # среднее по трём играм: (700+650+600)/3


def test_anti_nominations_rank_worst_first():
    r = by_key(compute_standings(three_players()))
    assert r["loss_streak"]["anti"] is True
    assert r["loss_streak"]["entries"][0]["player"] == "C"
    assert r["drop"]["entries"][0]["player"] == "C"
    assert r["gpm"]["anti"] is False


def test_top_is_limited_and_ties_share_place():
    players = [(n, [g(1, True), g(2, True), g(3, v)]) for n, v in (("A", True), ("B", False), ("C", False), ("D", False))]
    r = by_key(compute_standings(players, top=3))
    wr = r["winrate"]["entries"]
    assert [e["player"] for e in wr] == ["A", "B", "C"]
    assert [e["place"] for e in wr] == [1, 2, 2]  # у B и C поровну — оба вторые


def test_nomination_skipped_when_everyone_equal():
    same = [g(1), g(2, False), g(3)]
    r = by_key(compute_standings([("A", same), ("B", list(same))]))
    assert "winrate" not in r and "climb" not in r


def test_average_metrics_need_min_games_but_climb_does_not():
    r = by_key(compute_standings([("A", [g(1, gpm=900)]), ("B", [g(1, False, gpm=300)])], min_games=3))
    assert "gpm" not in r and "winrate" not in r
    assert r["climb"]["entries"][0]["player"] == "A"


def test_climb_and_drop_only_list_real_movers():
    r = by_key(compute_standings([("A", [g(1, False)]), ("B", [g(1, False), g(2, False)]), ("C", [g(1, True)])]))
    assert [e["player"] for e in r["climb"]["entries"]] == ["C"]
    assert [e["player"] for e in r["drop"]["entries"]] == ["B", "A"]


def test_points_give_3_2_1_for_places_and_skip_anti():
    standings = compute_standings(three_players())
    pts = contest_points(standings)
    assert [p["player"] for p in pts][0] == "A"
    assert pts[0]["points"] > pts[1]["points"] > pts[2]["points"]
    # антирекорды очков не дают: C не получает баллов за «серию поражений»
    only_anti = [s for s in standings if s["anti"]]
    assert all(p["points"] == 0 for p in contest_points(only_anti))


def test_points_tie_break_by_golds():
    st = [{"key": "x", "anti": False, "entries": [{"player": "A", "place": 1}, {"player": "B", "place": 2}]},
          {"key": "y", "anti": False, "entries": [{"player": "B", "place": 1}, {"player": "A", "place": 3}]},
          {"key": "z", "anti": False, "entries": [{"player": "B", "place": 3}, {"player": "A", "place": 2}]}]
    pts = {p["player"]: p for p in contest_points(st)}
    assert pts["A"]["points"] == pts["B"]["points"] == 6
    assert pts["A"]["golds"] == pts["B"]["golds"] == 1


def test_period_awards_still_the_single_leader_of_each_standing():
    awards = {a["key"]: a for a in compute_period_awards(three_players())}
    standings = by_key(compute_standings(three_players()))
    for key, award in awards.items():
        assert standings[key]["entries"][0]["player"] == award["player"]


def test_champion_is_unique_leader_only():
    from mmrbot.tracker import contest_champion
    assert contest_champion([]) is None
    assert contest_champion([{"player": "A", "points": 0, "golds": 0}]) is None
    tie = [{"player": "A", "points": 6, "golds": 1}, {"player": "B", "points": 6, "golds": 1}]
    assert contest_champion(tie) is None
    assert contest_champion([{"player": "A", "points": 7, "golds": 2}, tie[1]])["player"] == "A"


def test_weekly_report_has_champion_in_text_and_tile(tmp_path):
    import time
    from mmrbot.card_data import weekly_tiles
    from mmrbot.formatting import render_weekly
    from mmrbot.storage import Storage
    from mmrbot.tracker import build_weekly_report

    st = Storage(str(tmp_path / "c.db"))
    st.get_or_create_chat(1)
    a, b = st.add_player(1, 1, "Вася", None, 0, 0), st.add_player(1, 2, "Петя", None, 0, 0)
    now = int(time.time())

    def row(i, t, win):
        return {"match_id": i, "start_time": t, "player_slot": 0, "radiant_win": win, "lobby_type": 7,
                "kills": 5, "deaths": 3, "assists": 7, "hero_id": 1, "duration": 2400}

    st.add_matches(a.id, [row(i, now - 3600 * i, True) for i in range(1, 4)])
    st.add_matches(b.id, [row(10 + i, now - 3600 * i, False) for i in range(1, 4)])
    report = build_weekly_report(st, 1, now)
    assert report["champion"]["player"] == "Вася"
    assert "Чемпион недели: <b>Вася</b>" in render_weekly(report)
    assert any(t["label"] == "Чемпион недели" and t["value"] == "Вася" for t in weekly_tiles(report))


# --- смена лидера -------------------------------------------------------------------------------

def _st(key, *players, anti=False):
    return {"key": key, "emoji": "💰", "title": f"Номинация {key}", "anti": anti,
            "entries": [{"player": p, "place": i + 1, "text": f"{p}-текст"} for i, p in enumerate(players)]}


def test_leader_changes_reports_only_real_takeovers():
    from mmrbot.awards import leader_changes
    standings = [_st("gpm", "Петя", "Вася"), _st("winrate", "Вася", "Петя"), _st("damage", "Вася", "Петя"),
                 _st("loss_streak", "Петя", "Вася", anti=True)]
    previous = {"gpm": "Вася", "winrate": "Вася", "loss_streak": "Вася"}  # damage — новой номинации не было
    got = leader_changes(standings, previous)
    assert [(c["key"], c["old"], c["new"]) for c in got] == [("gpm", "Вася", "Петя")]  # антирекорды и новые — молча


def test_leader_changes_ignores_shared_first_place():
    from mmrbot.awards import current_leaders, leader_changes
    shared = {"key": "gpm", "emoji": "💰", "title": "GPM", "anti": False, "entries": [
        {"player": "A", "place": 1, "text": ""}, {"player": "B", "place": 1, "text": ""}]}
    assert current_leaders([shared]) == {}
    assert leader_changes([shared], {"gpm": "A"}) == []


def test_storage_keeps_contest_leaders_per_chat_and_period(tmp_path):
    from mmrbot.storage import Storage
    st = Storage(str(tmp_path / "l.db"))
    assert st.get_contest_leaders(1, "week") == {}
    st.set_contest_leaders(1, "week", {"gpm": "Вася", "winrate": "Петя"})
    st.set_contest_leaders(1, "week", {"gpm": "Петя"})  # перезапись: набор заменяется
    st.set_contest_leaders(1, "month", {"gpm": "Оля"})
    assert st.get_contest_leaders(1, "week") == {"gpm": "Петя"}
    assert st.get_contest_leaders(1, "month") == {"gpm": "Оля"} and st.get_contest_leaders(2, "week") == {}


def _two(tmp_path, a_wins=True):
    import time
    from mmrbot.storage import Storage
    st = Storage(str(tmp_path / "t.db"))
    st.get_or_create_chat(1)
    a, b = st.add_player(1, 1, "Вася", None, 0, 0), st.add_player(1, 2, "Петя", None, 0, 0)
    now = int(time.time())

    def add(player, base, win, gpm):
        st.add_matches(player.id, [{"match_id": base + i, "start_time": now - 3600 * (i + 1), "player_slot": 0,
                                    "radiant_win": win, "lobby_type": 7, "kills": 5, "deaths": 3, "assists": 7,
                                    "hero_id": 1, "duration": 2400, "gpm": gpm} for i in range(3)])
    return st, a, b, now, add


def test_check_contest_leaders_seeds_silently_then_announces_takeover(tmp_path):
    from mmrbot.tracker import check_contest_leaders
    st, a, b, now, add = _two(tmp_path)
    add(a, 100, True, 700)
    add(b, 200, False, 400)
    assert check_contest_leaders(st, 1, now) == []                      # первый проход только запоминает
    assert st.get_contest_leaders(1, "week")["gpm"] == "Вася"
    assert check_contest_leaders(st, 1, now) == []                      # ничего не поменялось
    st.add_matches(b.id, [{"match_id": 300 + i, "start_time": now - 60 * (i + 1), "player_slot": 0, "radiant_win": True,
                           "lobby_type": 7, "kills": 5, "deaths": 3, "assists": 7, "hero_id": 1, "duration": 2400,
                           "gpm": 1500} for i in range(3)])             # Петя рванул вперёд
    events = check_contest_leaders(st, 1, now)
    weeks = [e for e in events if e["period"] == "week"]
    assert weeks and any(c["key"] == "gpm" and c["old"] == "Вася" and c["new"] == "Петя" for c in weeks[0]["changes"])
    assert check_contest_leaders(st, 1, now) == []                      # уже объявлено


def test_render_leader_change_text():
    from mmrbot.formatting import render_leader_change
    text = render_leader_change("за неделю", [{"key": "gpm", "emoji": "💰", "title": "Наибольший GPM", "old": "Вася",
                                               "new": "Петя", "text": "650 GPM в среднем"}])
    assert "Смена лидера за неделю" in text and "<b>Петя</b>" in text and "Вася" in text and "650 GPM" in text
