import pytest

from mmrbot.storage import Storage
from mmrbot.tracker import (
    build_chat_comparison,
    build_leaderboard,
    build_player_summary,
    build_together,
    refresh_player,
)


class FakeOpenDota:
    """Фейковый клиент: без сети, возвращает заранее заданные профиль и матчи."""

    def __init__(self, profile=None, matches=None, match_stats=None):
        self.profile = profile or {"rank_tier": None, "leaderboard_rank": None, "personaname": None}
        self.matches = matches or []
        self.match_stats = match_stats  # dict пер-матч статы (одинаковые для всех) или None
        self.profile_calls = 0
        self.match_calls = 0
        self.refresh_calls = 0

    def refresh(self, account_id):
        self.refresh_calls += 1
        return True

    def get_match_player_stats(self, match_id, account_id, player_slot=None):
        return self.match_stats

    def get_profile(self, account_id):
        self.profile_calls += 1
        return self.profile

    def get_matches(self, account_id, limit=200):
        self.match_calls += 1
        return list(self.matches)


def od_match(match_id, start_time, slot=0, radiant_win=True, lobby_type=7, k=1, d=1, a=1, hero_id=1):
    return {
        "match_id": match_id,
        "start_time": start_time,
        "player_slot": slot,
        "radiant_win": radiant_win,
        "lobby_type": lobby_type,
        "kills": k,
        "deaths": d,
        "assists": a,
        "hero_id": hero_id,
    }


@pytest.fixture
def store(tmp_path):
    return Storage(str(tmp_path / "t.db"))


# --- refresh_player -----------------------------------------------------

def test_refresh_stores_all_ranked_history(store):
    player = store.add_player(100, 42, "Вася", 5000, anchor_ts=1000, created_ts=1000)
    client = FakeOpenDota(
        profile={"rank_tier": 75, "leaderboard_rank": None, "personaname": "Вася"},
        matches=[
            od_match(1, start_time=500, lobby_type=7),    # до добавления игрока — тоже история
            od_match(2, start_time=1500, lobby_type=0),   # не ранкед — игнор
            od_match(3, start_time=1500, lobby_type=7),   # ок
            od_match(4, start_time=2500, lobby_type=7),   # ок
        ],
    )
    new_count = refresh_player(store, client, player, now=3000)
    assert new_count == 3
    stored = store.get_matches(player.id)
    assert {m["match_id"] for m in stored} == {1, 3, 4}


def test_summary_counts_whole_history_but_mmr_only_since_anchor(store):
    player = store.add_player(100, 42, "Вася", 5000, anchor_ts=1000, created_ts=1000)
    client = FakeOpenDota(matches=[od_match(1, 500), od_match(2, 1500), od_match(3, 2500, radiant_win=False)])
    refresh_player(store, client, player, now=3000)
    summary = build_player_summary(store, store.get_or_create_chat(100), player, now=3000)
    assert summary.games_total == 3                      # статистика — по всей истории
    assert summary.mmr_delta == 0                        # MMR-оценка: с якоря — 1 победа и 1 поражение
    assert len(store.get_matches(player.id)) == 3


def test_first_refresh_loads_deep_history_then_recent_only(store):
    player = store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    limits = []

    class Spy(FakeOpenDota):
        def get_matches(self, account_id, limit=200):
            limits.append(limit)
            return super().get_matches(account_id, limit)

    client = Spy(matches=[od_match(1, 1500)])
    refresh_player(store, client, player, now=3000)
    refresh_player(store, client, player, now=3100)
    assert limits[0] is None and limits[1] == 200     # первая загрузка — вся история, дальше свежие


def test_refresh_updates_rank(store):
    player = store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    client = FakeOpenDota(profile={"rank_tier": 63, "leaderboard_rank": None, "personaname": "Вася"})
    refresh_player(store, client, player, now=3000)
    refreshed = store.get_player(100, "Вася")
    assert refreshed.last_rank_tier == 63
    assert refreshed.updated_ts == 3000


def test_refresh_is_idempotent(store):
    player = store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    client = FakeOpenDota(matches=[od_match(3, 1500), od_match(4, 2500)])
    assert refresh_player(store, client, player, now=3000) == 2
    assert refresh_player(store, client, player, now=4000) == 0  # те же матчи — 0 новых


def test_refresh_skips_matches_with_unknown_outcome(store):
    # radiant_win=None (матч ещё не финализирован) не должен сохраняться как поражение.
    player = store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    client = FakeOpenDota(matches=[
        od_match(3, 1500, radiant_win=None),  # исход неизвестен — пропустить
        od_match(4, 2500, radiant_win=True),  # ок
    ])
    inserted = refresh_player(store, client, player, now=3000)
    assert inserted == 1
    assert {m["match_id"] for m in store.get_matches(player.id)} == {4}


def test_leaderboard_survives_one_player_refresh_error(store):
    now = 100_000
    good = store.add_player(100, 1, "Good", 5000, 1000, 1000)
    store.add_player(100, 2, "Bad", 4000, 1000, 1000)
    store.add_matches(good.id, [{"match_id": 10, "start_time": 2000, "player_slot": 0, "radiant_win": True, "lobby_type": 7, "kills": 1, "deaths": 1, "assists": 1, "hero_id": 1}])

    class FlakyClient(FakeOpenDota):
        def get_profile(self, account_id):
            if account_id == 2:
                raise RuntimeError("OpenDota HTTP 503")
            return super().get_profile(account_id)

    board = build_leaderboard(store, FlakyClient(), 100, now=now, refresh=True)
    names = {s.display_name for s in board}
    assert names == {"Good", "Bad"}  # битый игрок не рушит весь лидерборд


def _m(match_id, start_time, slot=0, radiant_win=True, hero_id=1, k=1, d=1, a=1, lobby_type=7, duration=1800, party_size=1):
    return {
        "match_id": match_id, "start_time": start_time, "player_slot": slot,
        "radiant_win": radiant_win, "lobby_type": lobby_type, "kills": k, "deaths": d,
        "assists": a, "hero_id": hero_id, "duration": duration, "party_size": party_size,
    }


def test_summary_includes_streak_and_top_heroes(store):
    now = 100_000
    p = store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    store.add_matches(p.id, [
        _m(1, 2000, hero_id=1, radiant_win=False),  # loss
        _m(2, 3000, hero_id=1, radiant_win=True),   # win
        _m(3, 4000, hero_id=2, radiant_win=True),   # win
    ])
    p = store.get_player(100, "Вася")
    chat = store.get_or_create_chat(100)
    s = build_player_summary(store, chat, p, now=now)
    assert (s.streak_type, s.streak_len) == ("W", 2)
    assert s.top_heroes[0]["hero_id"] == 1  # 2 игры на герое 1


def test_refresh_enriches_matches_and_perf(store):
    p = store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    client = FakeOpenDota(
        matches=[od_match(1, 1500), od_match(2, 2500)],
        match_stats={
            "gpm": 500, "xpm": 600, "last_hits": 180, "denies": 10, "hero_damage": 25000,
            "tower_damage": 3000, "hero_healing": 0, "net_worth": 18000, "level": 25,
            "benchmarks": {"gold_per_min": 0.6, "hero_damage_per_min": 0.8},
        },
    )
    refresh_player(store, client, p, now=3000)
    rows = store.get_matches(p.id)
    assert all(r["enriched"] == 1 for r in rows)
    assert rows[0]["gpm"] == 500 and rows[0]["net_worth"] == 18000

    p2 = store.get_player(100, "Вася")
    chat = store.get_or_create_chat(100)
    s = build_player_summary(store, chat, p2, now=100_000)
    assert s.avg_perf == pytest.approx((0.6 + 0.8) / 2)
    assert s.enriched_games == 2
    assert s.avg_gpm_window == pytest.approx(500)
    # профиль скилла (перцентили) и роль
    assert s.skill["gold_per_min"] == pytest.approx(0.6)
    assert s.skill["hero_damage_per_min"] == pytest.approx(0.8)
    assert s.role_style == "кор (фарм)"  # last_hits 180 → кор


def test_build_chat_comparison_ranks_and_power(store):
    from dataclasses import replace
    now = 100_000
    p = store.add_player(100, 1, "Base", 5000, 1000, 1000)
    store.add_matches(p.id, [_m(10 + i, 2000 + i, radiant_win=(i % 2 == 0)) for i in range(4)])
    base = build_leaderboard(store, FakeOpenDota(), 100, now=now, refresh=False)[0]
    # A лучше по всем метрикам, B хуже
    a = replace(base, display_name="A", avg_perf=0.8, winrate=0.6, kda_ratio=4.0, avg_gpm_window=500.0, games_total=5, enriched_games=5, detail_games=5)
    b = replace(base, display_name="B", avg_perf=0.4, winrate=0.4, kda_ratio=2.0, avg_gpm_window=400.0, games_total=5, enriched_games=5, detail_games=5)
    comp = build_chat_comparison([a, b])
    assert comp["size"] == 2
    assert comp["players"]["A"]["ranks"]["perf"] == 1
    assert comp["players"]["B"]["ranks"]["perf"] == 2
    assert comp["players"]["A"]["power_rank"] == 1
    assert comp["players"]["B"]["power_rank"] == 2
    assert "perf" in comp["players"]["A"]["leads"]


def test_build_chat_comparison_handles_missing_metrics(store):
    from dataclasses import replace
    now = 100_000
    p = store.add_player(100, 1, "Base", 5000, 1000, 1000)
    store.add_matches(p.id, [_m(10, 2000)])
    base = build_leaderboard(store, FakeOpenDota(), 100, now=now, refresh=False)[0]
    a = replace(base, display_name="A", avg_perf=0.7, games_total=5, enriched_games=5)
    b = replace(base, display_name="B", avg_perf=None, games_total=5)  # без перфа
    comp = build_chat_comparison([a, b])
    assert comp["players"]["A"]["ranks"]["perf"] == 1
    assert "perf" not in comp["players"]["B"]["ranks"]  # нет метрики — нет ранга




def test_summary_includes_form_and_records(store):
    now = 100_000
    p = store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    store.add_matches(p.id, [
        _m(1, 2000, radiant_win=True),
        _m(2, 3000, radiant_win=True),
        _m(3, 4000, radiant_win=False),
        _m(4, 5000, radiant_win=True, k=8, d=2, a=8),
    ])
    p = store.get_player(100, "Вася")
    chat = store.get_or_create_chat(100)
    s = build_player_summary(store, chat, p, now=now)
    assert s.recent_form == [True, True, False, True]
    assert s.longest_win_streak == 2
    assert s.last_game is not None and s.last_game["kills"] == 8 and s.last_game["won"] is True


def test_summary_includes_solo_party_and_totals(store):
    now = 100_000
    p = store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    store.add_matches(p.id, [
        _m(1, 2000, party_size=1, radiant_win=True),   # solo win
        _m(2, 3000, party_size=3, radiant_win=False),  # party loss
    ])
    p = store.get_player(100, "Вася")
    chat = store.get_or_create_chat(100)
    s = build_player_summary(store, chat, p, now=now)
    assert s.solo == (1, 1)
    assert s.party == (1, 0)
    assert s.avg_duration_min > 0






def test_build_together_counts_shared(store):
    now = 100_000
    a = store.add_player(100, 1, "Alice", 5000, 1000, 1000)
    b = store.add_player(100, 2, "Bob", 4000, 1000, 1000)
    store.add_matches(a.id, [_m(1, 2000, radiant_win=True, party_size=2), _m(2, 3000, radiant_win=False)])
    store.add_matches(b.id, [_m(1, 2000, radiant_win=True, party_size=2), _m(9, 3000, radiant_win=True)])
    result = build_together(store, 100)
    assert result["summary"]["games"] == 1  # общий матч 1
    assert result["summary"]["wins"] == 1
    assert [p["name"] for p in result["players"]] == ["Alice", "Bob"]
    assert result["pairs"] == [{"a": 0, "b": 1, "games": 1, "wins": 1}]  # матрица пар для картинки


def test_leaderboard_reread_by_account_id_not_name(store):
    # Игрок с именем-числом не должен подменять другого при внутренней перечитке.
    now = 100_000
    store.add_player(100, 555, "Alice", anchor_mmr=5000, anchor_ts=1000, created_ts=1000)
    store.add_player(100, 999, "555", anchor_mmr=4000, anchor_ts=1000, created_ts=1000)
    board = build_leaderboard(store, FakeOpenDota(), 100, now=now, refresh=True)
    by_name = {s.display_name: s.anchor_mmr for s in board}
    assert by_name["Alice"] == 5000
    assert by_name["555"] == 4000


# --- build_player_summary ----------------------------------------------

def test_summary_computes_mmr_and_windows(store):
    now = 100_000
    player = store.add_player(100, 42, "Вася", anchor_mmr=5000, anchor_ts=1000, created_ts=1000)
    store.add_matches(player.id, [
        {"match_id": 1, "start_time": 2000, "player_slot": 0, "radiant_win": True, "lobby_type": 7, "kills": 10, "deaths": 2, "assists": 5, "hero_id": 1},    # win, старый
        {"match_id": 2, "start_time": 3000, "player_slot": 0, "radiant_win": False, "lobby_type": 7, "kills": 1, "deaths": 8, "assists": 2, "hero_id": 2},     # loss, старый
        {"match_id": 3, "start_time": 90000, "player_slot": 128, "radiant_win": False, "lobby_type": 7, "kills": 6, "deaths": 3, "assists": 9, "hero_id": 3},  # win, сегодня
        {"match_id": 4, "start_time": 95000, "player_slot": 0, "radiant_win": True, "lobby_type": 7, "kills": 8, "deaths": 4, "assists": 7, "hero_id": 4},     # win, сегодня
    ])
    store.update_player_rank(player.id, rank_tier=75, leaderboard_rank=None, updated_ts=now)
    player = store.get_player(100, "Вася")
    chat = store.get_or_create_chat(100)  # step=25 default

    s = build_player_summary(store, chat, player, now=now)
    assert s.games_total == 4
    assert s.wins_total == 3
    assert s.losses_total == 1
    assert s.mmr_delta == 50            # (3-1)*25
    assert s.current_mmr == 5050        # 5000 + 50
    assert s.games_today == 2           # start_time >= now-86400 (13600)
    assert s.wins_today == 2
    assert s.delta_today == 50          # (2-0)*25
    assert s.rank == "Divine 5"


def test_summary_without_anchor_mmr_has_none_current(store):
    now = 100_000
    player = store.add_player(100, 42, "NoMMR", anchor_mmr=None, anchor_ts=1000, created_ts=1000)
    store.add_matches(player.id, [
        {"match_id": 1, "start_time": 2000, "player_slot": 0, "radiant_win": True, "lobby_type": 7, "kills": 1, "deaths": 1, "assists": 1, "hero_id": 1},
    ])
    player = store.get_player(100, "NoMMR")
    chat = store.get_or_create_chat(100)
    s = build_player_summary(store, chat, player, now=now)
    assert s.current_mmr is None
    assert s.mmr_delta == 25  # дельта считается всё равно (1-0)*25


# --- build_leaderboard --------------------------------------------------

def test_leaderboard_skips_refresh_when_recent(store):
    now = 100_000
    p = store.add_player(100, 1, "A", 5000, 1000, 1000)
    store.update_player_rank(p.id, 80, None, updated_ts=now - 10)  # обновлён 10с назад
    client = FakeOpenDota()
    build_leaderboard(store, client, 100, now=now, refresh=True)
    assert client.refresh_calls == 0  # кулдаун → в OpenDota не ходили


def test_leaderboard_refreshes_when_stale(store):
    now = 100_000
    p = store.add_player(100, 1, "A", 5000, 1000, 1000)
    store.update_player_rank(p.id, 80, None, updated_ts=now - 100_000)  # давно
    client = FakeOpenDota()
    build_leaderboard(store, client, 100, now=now, refresh=True)
    assert client.refresh_calls >= 1  # устарело → обновили


def test_leaderboard_sorted_by_current_mmr_desc(store):
    now = 100_000
    high = store.add_player(100, 1, "High", anchor_mmr=5000, anchor_ts=1000, created_ts=1000)
    low = store.add_player(100, 2, "Low", anchor_mmr=3000, anchor_ts=1000, created_ts=1000)
    none = store.add_player(100, 3, "None", anchor_mmr=None, anchor_ts=1000, created_ts=1000)
    store.add_matches(high.id, [{"match_id": 10, "start_time": 2000, "player_slot": 0, "radiant_win": True, "lobby_type": 7, "kills": 0, "deaths": 0, "assists": 0, "hero_id": 1}])

    board = build_leaderboard(store, FakeOpenDota(), 100, now=now, refresh=False)
    names = [s.display_name for s in board]
    assert names[0] == "High"          # 5025
    assert names[1] == "Low"           # 3000
    assert names[2] == "None"          # None current — в конце


class FakeStratz:
    def __init__(self, data=None, fail=False):
        self.data = data or {}
        self.fail = fail
        self.calls = 0

    def get_matches(self, account_id, match_ids, hints=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("stratz down")
        return {m: v for m, v in self.data.items() if m in match_ids}


def test_refresh_player_enriches_with_stratz(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    od = FakeOpenDota(matches=[od_match(100, 1000)])
    stratz = FakeStratz({100: {"position": 3, "role": "CORE", "lane": "OFF_LANE", "imp": 7}})
    refresh_player(store, od, player, 2000, stratz=stratz)
    row = store.get_matches(player.id)[0]
    assert (row["position"], row["lane"], row["imp"]) == (3, "OFF_LANE", 7)


def test_refresh_player_survives_stratz_failure(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    od = FakeOpenDota(matches=[od_match(100, 1000)])
    inserted = refresh_player(store, od, player, 2000, stratz=FakeStratz(fail=True))
    assert inserted == 1
    assert store.get_matches(player.id)[0]["position"] is None


def test_refresh_player_skips_stratz_when_all_matches_enriched(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    od = FakeOpenDota(matches=[od_match(100, 1000)])
    stratz = FakeStratz({100: {"position": 1, "role": "CORE", "lane": "SAFE_LANE", "imp": 1, "party_size": 1}})
    refresh_player(store, od, player, 2000, stratz=stratz)
    refresh_player(store, od, player, 2100, stratz=stratz)
    assert stratz.calls == 1


# --- представления для /match, /heroes <игрок>, /hero ------------------

def _seed(store, name, acc, rows):
    player = store.add_player(1, acc, name, None, 0, 0)
    store.add_matches(player.id, rows)
    return player


def _row(match_id, start, hero=1, slot=0, rw=True):
    return {"match_id": match_id, "start_time": start, "player_slot": slot,
            "radiant_win": rw, "lobby_type": 7, "hero_id": hero}


def test_build_match_view_latest_across_chat(store):
    from mmrbot.tracker import build_match_view
    _seed(store, "Вася", 1, [_row(10, 100), _row(11, 200)])
    _seed(store, "Петя", 2, [_row(12, 300, hero=5)])
    view = build_match_view(store, 1, None, None)
    assert view["player"].display_name == "Петя" and view["match"]["match_id"] == 12
    assert "party" not in view


def test_build_match_view_by_name_and_id(store):
    from mmrbot.tracker import build_match_view
    _seed(store, "Вася", 1, [_row(10, 100), _row(11, 200)])
    view = build_match_view(store, 1, "вася", 10)
    assert view["match"]["match_id"] == 10
    assert build_match_view(store, 1, "Никто", None) is None
    assert build_match_view(store, 1, "Вася", 999) is None


def test_build_player_heroes_and_hero_view(store):
    from mmrbot.tracker import build_hero_view, build_player_heroes
    _seed(store, "Вася", 1, [_row(10, 100, hero=1), _row(11, 200, hero=1), _row(12, 300, hero=2)])
    _seed(store, "Петя", 2, [_row(13, 100, hero=1, rw=False)])
    player, rows = build_player_heroes(store, 1, "Вася", None)
    assert player.display_name == "Вася" and [r["hero_id"] for r in rows] == [1, 2]
    assert build_player_heroes(store, 1, "нет", None) is None
    _, rows = build_player_heroes(store, 1, "Вася", 250)
    assert [r["hero_id"] for r in rows] == [2]
    entries = build_hero_view(store, 1, 1, None)
    assert [(p.display_name, s["games"]) for p, s in entries] == [("Вася", 2), ("Петя", 1)]


def test_stratz_miss_is_retried_then_given_up(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    od = FakeOpenDota(matches=[od_match(100, 1000)])
    stratz = FakeStratz({})  # Stratz этот матч не знает
    for i in range(12):  # между попытками проходит достаточно времени, чтобы пауза всегда успевала выйти
        refresh_player(store, od, player, 2000 + i * 100_000, stratz=stratz)
    assert stratz.calls == 8  # дальше max_tries — не спрашиваем
    assert store.get_matches(player.id)[0]["position"] is None


def test_summary_heroes_use_full_history(store):
    player = store.add_player(100, 42, "Вася", 5000, anchor_ts=1000, created_ts=1000)
    client = FakeOpenDota(matches=[od_match(1, 100, hero_id=7), od_match(2, 200, hero_id=7)])
    refresh_player(store, client, player, now=3000)
    summary = build_player_summary(store, store.get_or_create_chat(100), player, now=3000)
    assert [h["hero_id"] for h in summary.top_heroes] == [7]
    assert summary.hero_pool == 1 and summary.games_total == 2
    assert summary.mmr_delta == 0                        # оба матча до якоря — на MMR не влияют


def test_backfill_stratz_fills_pending_across_players_in_batches(store):
    import mmrbot.tracker as tr
    from mmrbot.tracker import backfill_stratz
    store.get_or_create_chat(100)
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    store.add_matches(player.id, [
        {"match_id": i, "start_time": i, "player_slot": 0, "radiant_win": True, "lobby_type": 7}
        for i in range(1, 8)
    ])
    data = {i: {"position": 1, "role": "CORE", "lane": "SAFE_LANE", "imp": i, "party_size": 1} for i in range(1, 8)}
    old = tr.STRATZ_CAP
    tr.STRATZ_CAP = 3
    try:
        stratz = FakeStratz(data)
        backfill_stratz(store, stratz, rounds=2)
        assert sum(1 for m in store.get_matches(player.id) if m["position"]) == 6   # 2 пачки по 3
        backfill_stratz(store, stratz, rounds=2)
        assert all(m["position"] == 1 for m in store.get_matches(player.id))
        calls = stratz.calls
        backfill_stratz(store, stratz, rounds=2)
        assert stratz.calls == calls                       # всё заполнено — лишних запросов нет
    finally:
        tr.STRATZ_CAP = old


def _seed_matches(store, player, n):
    store.add_matches(player.id, [
        {"match_id": i, "start_time": i, "player_slot": 0, "radiant_win": True, "lobby_type": 7}
        for i in range(1, n + 1)
    ])


def test_refresh_enriches_only_few_matches_in_request(store):
    """В пользовательском запросе обогащаем немного — иначе /stats ждёт по ~1с на матч."""
    import mmrbot.tracker as tr
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    _seed_matches(store, player, 30)
    client = FakeOpenDota(match_stats={"gpm": 500, "benchmarks": {"gold_per_min": 0.5}})
    calls = []
    orig = client.get_match_player_stats
    client.get_match_player_stats = lambda m, a, s=None: (calls.append(m), orig(m, a, s))[1]
    refresh_player(store, client, player, now=100)
    assert len(calls) <= tr.ENRICH_CAP <= 4


def test_backfill_opendota_enriches_backlog_across_players(store):
    from mmrbot.tracker import backfill_opendota
    store.get_or_create_chat(100)
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    _seed_matches(store, player, 10)
    client = FakeOpenDota(match_stats={"gpm": 500, "benchmarks": {"gold_per_min": 0.5}})
    assert backfill_opendota(store, client, per_player=6, days=0) == 6
    assert sum(1 for m in store.get_matches(player.id) if m["enriched"]) == 6
    backfill_opendota(store, client, per_player=6, days=0)
    assert all(m["enriched"] for m in store.get_matches(player.id))
    assert backfill_opendota(store, client, per_player=6, days=0) == 0   # всё готово — запросов нет


def test_empty_match_details_do_not_block_queue(store):
    """Матч, по которому OpenDota ничего не отдаёт, сдаётся после нескольких попыток."""
    from mmrbot.tracker import backfill_opendota
    store.get_or_create_chat(100)
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    _seed_matches(store, player, 2)
    client = FakeOpenDota(match_stats=None)               # нет данных ни по одному матчу
    for _ in range(6):
        backfill_opendota(store, client, per_player=5, days=0)
    assert store.get_unenriched_match_ids(player.id, 0, 10) == []


# --- скорость: доп. запросы только когда есть что обновлять --------------------

class InsightsOpenDota(FakeOpenDota):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.extra_calls = 0

    def get_totals(self, account_id):
        self.extra_calls += 1
        return {"gpm": 400.0, "xpm": 500.0, "last_hits": 150.0}

    def get_lanes(self, account_id):
        self.extra_calls += 1
        return {1: (3, 2)}

    def get_gpm_distribution(self, account_id):
        self.extra_calls += 1
        return {"median": 400, "best": 700}


def test_refresh_never_requests_unused_career_aggregates(store):
    """Средние GPM/XPM, линии и медиана GPM нигде не показываются — запросов за ними нет."""
    player = store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    client = InsightsOpenDota(matches=[od_match(3, 1500)])
    refresh_player(store, client, player, now=3000)
    client.matches.append(od_match(4, 2500))
    refresh_player(store, client, store.get_player(100, "Вася"), now=4000)
    assert client.extra_calls == 0


# --- лидерборд за период (/stats неделя|месяц) --------------------------------

def test_period_leaderboard_counts_only_window_and_sorts_by_delta(store):
    from mmrbot.tracker import build_period_leaderboard

    a = store.add_player(100, 1, "Аня", 5000, 0, 0)
    b = store.add_player(100, 2, "Боря", 5000, 0, 0)
    c = store.add_player(100, 3, "Ваня", 5000, 0, 0)
    now = 10_000_000
    refresh_player(store, FakeOpenDota(matches=[
        od_match(1, now - 100, radiant_win=True),          # в окне: победа
        od_match(2, now - 200, radiant_win=True),          # в окне: победа
        od_match(3, now - 9_000_000, radiant_win=True),    # вне окна
    ]), a, now=now)
    refresh_player(store, FakeOpenDota(matches=[od_match(4, now - 100, radiant_win=False)]), b, now=now)
    refresh_player(store, FakeOpenDota(matches=[]), c, now=now)

    rows = build_period_leaderboard(store, 100, since_ts=now - 7 * 86_400)
    assert [r["name"] for r in rows] == ["Аня", "Боря", "Ваня"]  # плюс → минус → без игр
    assert rows[0]["games"] == 2 and rows[0]["wins"] == 2 and rows[0]["delta"] > 0
    assert rows[1]["losses"] == 1 and rows[1]["delta"] < 0
    assert rows[2]["games"] == 0


def test_summary_today_is_calendar_day_in_chat_tz(store):
    from datetime import datetime, timezone
    now = int(datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc).timestamp())  # 15:00 МСК
    midnight = int(datetime(2026, 9, 30, 21, 0, tzinfo=timezone.utc).timestamp())  # 00:00 МСК
    player = store.add_player(100, 42, "Вася", anchor_mmr=5000, anchor_ts=1000, created_ts=1000)
    store.add_matches(player.id, [
        {"match_id": 1, "start_time": midnight - 3600, "player_slot": 0, "radiant_win": True, "lobby_type": 7, "kills": 1, "deaths": 1, "assists": 1, "hero_id": 1},  # вчера 23:00 МСК, но <24ч назад
        {"match_id": 2, "start_time": midnight + 3600, "player_slot": 0, "radiant_win": True, "lobby_type": 7, "kills": 1, "deaths": 1, "assists": 1, "hero_id": 2},  # сегодня
    ])
    player = store.get_player(100, "Вася")
    chat = store.get_or_create_chat(100)  # tz по умолчанию Europe/Moscow
    s = build_player_summary(store, chat, player, now=now)
    assert s.games_today == 1


def test_refresh_chat_refreshes_only_stale_players_and_returns_fresh_rows(store):
    from mmrbot.tracker import refresh_chat
    now = 1_000_000
    stale = store.add_player(1, 11, "Старый", None, 0, 0)
    fresh = store.add_player(1, 22, "Свежий", None, 0, 0)
    store.update_player_rank(fresh.id, 80, None, updated_ts=now - 10)
    client = FakeOpenDota()
    players = refresh_chat(store, client, 1, now)
    assert client.profile_calls == 1  # только устаревший
    assert {p.account_id: p.updated_ts for p in players}[11] == now


def test_get_outcomes_returns_light_rows_in_time_order(store):
    p = store.add_player(1, 11, "A", None, 0, 0)
    store.add_matches(p.id, [
        {**od_match(2, 200), "duration": 1}, {**od_match(1, 100, slot=130, radiant_win=False)},
    ])
    rows = store.get_outcomes(p.id)
    assert [r["start_time"] for r in rows] == [100, 200]
    assert set(rows[0]) == {"start_time", "player_slot", "radiant_win"}


# --- достоверность и скорость сбора матчей -------------------------------------

class RecentOpenDota(FakeOpenDota):
    """Клиент с лёгким списком последних матчей (как настоящий OpenDota.get_recent_matches)."""

    def __init__(self, *a, recent=None, **kw):
        super().__init__(*a, **kw)
        self.recent = recent or []
        self.recent_calls = 0
        self.limits = []

    def get_recent_matches(self, account_id):
        self.recent_calls += 1
        return list(self.recent)

    def get_matches(self, account_id, limit=200):
        self.limits.append(limit)
        return super().get_matches(account_id, limit)


def _synced_player(store, client, now=3000):
    """Игрок после первой (полной) загрузки истории."""
    player = store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    refresh_player(store, client, player, now=now)
    return store.get_player(100, "Вася")


def test_refresh_uses_light_recent_list_with_match_details(store):
    client = RecentOpenDota(matches=[od_match(1, 1500)])
    player = _synced_player(store, client)
    client.recent = [
        {**od_match(2, 2500), "gold_per_min": 612, "hero_damage": 30500, "hero_healing": 0, "party_size": 2},
        {**od_match(9, 2400, lobby_type=0)},   # не ранкед — мимо
        od_match(1, 1500),                      # перекрытие с сохранённым — пропусков нет
    ]
    assert refresh_player(store, client, player, now=3200) == 1
    assert client.limits == [None]              # тяжёлый список после первой загрузки не трогали
    row = store.get_matches(player.id)[-1]
    assert (row["match_id"], row["gpm"], row["hero_damage"], row["hero_healing"], row["party_size"]) == (
        2, 612, 30500, 0, 2)                    # статистика матча — без запроса на матч


def test_refresh_goes_deep_when_recent_list_does_not_reach_stored_history(store):
    client = RecentOpenDota(matches=[od_match(1, 1500)])
    player = _synced_player(store, client)
    client.matches = [od_match(1, 1500), od_match(2, 2000), od_match(3, 2500)]
    client.recent = [od_match(3, 2500)]         # между 1500 и 2500 могло быть что угодно
    assert refresh_player(store, client, player, now=3200) == 2
    assert client.limits == [None, 200]
    assert {m["match_id"] for m in store.get_matches(player.id)} == {1, 2, 3}


def test_refresh_goes_deep_periodically_for_self_check(store):
    import mmrbot.tracker as tr
    client = RecentOpenDota(matches=[od_match(1, 1500)], recent=[od_match(1, 1500)])
    player = _synced_player(store, client)
    refresh_player(store, client, player, now=3200)
    assert client.limits == [None]
    late = 3000 + tr.DEEP_SYNC_SEC
    refresh_player(store, client, store.get_player(100, "Вася"), now=late)
    assert client.limits == [None, 200]         # раз в DEEP_SYNC_SEC сверяемся по большому списку
    assert store.get_player(100, "Вася").history_ts == late


def test_refresh_loads_full_history_when_gap_exceeds_page(store):
    import mmrbot.tracker as tr
    client = FakeOpenDota(matches=[od_match(1, 100)])
    player = _synced_player(store, client)
    limits = []

    class Gap(FakeOpenDota):
        def get_matches(self, account_id, limit=200):
            limits.append(limit)
            count = 250 if limit is None else limit
            return [od_match(1000 + i, 5000 + i) for i in range(count)]

    assert refresh_player(store, Gap(), player, now=9000) == 250
    assert limits == [tr.HISTORY_LIMIT_REFRESH, None]   # все 200 новые → разрыв → вся история


def test_matches_are_saved_even_if_profile_fails(store):
    player = store.add_player(100, 42, "Вася", 5000, 1000, 1000)

    class NoProfile(FakeOpenDota):
        def get_profile(self, account_id):
            raise RuntimeError("OpenDota HTTP 503")

    assert refresh_player(store, NoProfile(matches=[od_match(1, 1500)]), player, now=3000) == 1
    assert store.get_player(100, "Вася").updated_ts == 3000


def test_failed_match_fetch_does_not_mark_player_updated(store):
    player = store.add_player(100, 42, "Вася", 5000, 1000, 1000)

    class NoMatches(FakeOpenDota):
        def get_matches(self, account_id, limit=200):
            raise RuntimeError("OpenDota HTTP 503")

    with pytest.raises(RuntimeError):
        refresh_player(store, NoMatches(), player, now=3000)
    assert store.get_player(100, "Вася").updated_ts is None   # кулдаун не выдаст старое за свежее


def test_profile_is_not_refetched_without_new_matches(store):
    import mmrbot.tracker as tr
    client = FakeOpenDota(profile={"rank_tier": 63, "leaderboard_rank": None, "personaname": "Вася"},
                          matches=[od_match(1, 1500)])
    player = _synced_player(store, client)
    assert client.profile_calls == 1
    refresh_player(store, client, player, now=3300)
    assert client.profile_calls == 1                         # игр не было — ранг не менялся
    client.matches.append(od_match(2, 3400))
    refresh_player(store, client, store.get_player(100, "Вася"), now=3600)
    assert client.profile_calls == 2                         # новая игра — ранг мог измениться
    refresh_player(store, client, store.get_player(100, "Вася"), now=3600 + tr.PROFILE_TTL)
    assert client.profile_calls == 3                         # и изредка — для подстраховки


def test_empty_profile_does_not_erase_known_rank(store):
    client = FakeOpenDota(profile={"rank_tier": 63, "leaderboard_rank": None, "personaname": "Вася"})
    player = _synced_player(store, client)
    client.profile = {"rank_tier": None, "leaderboard_rank": None, "personaname": None}  # сбой/скрытый профиль
    client.matches = [od_match(1, 3100)]
    refresh_player(store, client, player, now=3300)
    assert store.get_player(100, "Вася").last_rank_tier == 63


def test_steam_watch_also_updates_rank(store):
    from mmrbot.tracker import detect_steam_changes
    store.get_or_create_chat(100)
    store.add_player(100, 42, "Вася", 5000, 1000, 1000)
    client = FakeOpenDota(profile={"rank_tier": 71, "leaderboard_rank": None, "personaname": "V"})
    detect_steam_changes(store, client, now=5000)
    got = store.get_player(100, "Вася")
    assert (got.last_rank_tier, got.profile_ts) == (71, 5000)
    assert got.updated_ts is None                            # матчи при этом не сверялись


def test_mmr_counts_game_that_was_in_progress_at_anchor(store):
    # MMR задан в 2000: игра 1 уже закончилась (в MMR учтена), игра 2 ещё шла — её результат прибавляем.
    player = store.add_player(100, 42, "Вася", 5000, anchor_ts=2000, created_ts=2000)
    store.add_matches(player.id, [
        _m(1, 100, duration=1800),                       # кончилась в 1900 — до якоря
        _m(2, 1500, duration=1800),                      # кончилась в 3300 — после якоря
        _m(3, 4000, duration=1800, radiant_win=False),
    ])
    s = build_player_summary(store, store.get_or_create_chat(100), store.get_player(100, "Вася"), now=10_000)
    assert s.mmr_delta == 0 and s.current_mmr == 5000   # +25 за игру 2, −25 за игру 3


def test_fast_refresh_fetches_only_matches_and_background_finishes_the_rest(store):
    from mmrbot.tracker import finish_refresh, refresh_chat
    store.get_or_create_chat(100)
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    _seed_matches(store, player, 5)
    client = InsightsOpenDota(matches=[od_match(99, 500)],
                              match_stats={"gpm": 500, "benchmarks": {"gold_per_min": 0.5}})
    calls = []
    orig = client.get_match_player_stats
    client.get_match_player_stats = lambda m, a, s=None: (calls.append(m), orig(m, a, s))[1]
    stratz = FakeStratz({99: {"position": 2, "role": "CORE", "lane": "MID", "imp": 7, "party_size": 1}})

    refresh_chat(store, client, 100, 1_000_000, stratz, fast=True)
    # Команда пользователя: у OpenDota только матчи (+ профиль, раз есть новая игра) — два запроса.
    assert (client.match_calls, client.profile_calls) == (1, 1)
    assert (client.refresh_calls, client.extra_calls, calls) == (0, 0, [])
    new = next(m for m in store.get_matches(player.id) if m["match_id"] == 99)
    assert new["position"] == 2 and stratz.calls == 1     # новая игра и её позиция (Stratz, пачкой) — сразу

    assert finish_refresh(store, client, 100, per_player=3, days=0) == 3   # остальное догоняет фон
    assert (client.refresh_calls, client.extra_calls, len(calls)) == (1, 0, 3)

    client.extra_calls = 0
    finish_refresh(store, client, 100, per_player=0, days=0)
    assert client.extra_calls == 0                        # всё актуально — лишних запросов нет


def test_idle_party_is_polled_less_often_without_api_key(store):
    import mmrbot.tracker as tr
    from mmrbot.tracker import detect_new_games
    now = 1_000_000
    store.get_or_create_chat(100)
    p = store.add_player(100, 42, "Вася", 5000, 0, 0)
    store.add_matches(p.id, [_m(1, now - 10 * 3600)])     # последняя игра давно — пати не в сессии
    store.touch_player(p.id, now - 300)
    store.mark_notified(p.id)

    keyless = FakeOpenDota()
    keyless.api_key = None
    detect_new_games(store, keyless, store.get_or_create_chat(100), now)
    assert keyless.match_calls == 0                       # 5 минут < GAME_IDLE_COOLDOWN
    detect_new_games(store, keyless, store.get_or_create_chat(100), now - 300 + tr.GAME_IDLE_COOLDOWN)
    assert keyless.match_calls == 1

    store.touch_player(p.id, now - 300)
    keyed = FakeOpenDota()
    keyed.api_key = "KEY"
    detect_new_games(store, keyed, store.get_or_create_chat(100), now)
    assert keyed.match_calls == 1                         # с ключом лимит не жмёт — опрос частый


def test_active_party_is_polled_often_even_without_api_key(store):
    from mmrbot.tracker import detect_new_games
    now = 1_000_000
    store.get_or_create_chat(100)
    p = store.add_player(100, 42, "Вася", 5000, 0, 0)
    store.add_matches(p.id, [_m(1, now - 3600)])          # играли час назад — сессия идёт
    store.touch_player(p.id, now - 300)
    store.mark_notified(p.id)
    client = FakeOpenDota()
    client.api_key = None
    detect_new_games(store, client, store.get_or_create_chat(100), now)
    assert client.match_calls == 1


# --- аудит данных: точность ---------------------------------------------

def test_best_worst_hour_needs_two_distinct_hours():
    from mmrbot.tracker import _best_worst_hour
    assert _best_worst_hour({10: (5, 3)}) == (None, None)          # один час не бывает и лучшим, и худшим
    assert _best_worst_hour({10: (4, 2), 11: (4, 2)}) == (None, None)  # одинаковый винрейт
    best, worst = _best_worst_hour({10: (4, 3), 11: (4, 1)})
    assert best[0] == 10 and worst[0] == 11


def test_lobby_rank_is_a_real_rank_tier(store):
    """Медиана 45 и 52 — не «Archon 8»: берём реальное значение из набора."""
    from mmrbot.ranks import rank_label
    from mmrbot.tracker import median_rank_tier
    assert median_rank_tier([45, 52]) in (45, 52)
    assert rank_label(median_rank_tier([45, 52])) in ("Archon 5", "Legend 2")
    assert median_rank_tier([]) is None
    assert median_rank_tier([54, 54, 61]) == 54


def test_enrich_failure_does_not_burn_attempts(store):
    """Сбой/лимит OpenDota — не «нет данных»: попытки не тратятся, цикл останавливается."""
    from mmrbot.tracker import backfill_opendota
    store.get_or_create_chat(100)
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    _seed_matches(store, player, 3)
    client = FakeOpenDota()
    calls = []

    def boom(match_id, account_id, player_slot=None):
        calls.append(match_id)
        raise RuntimeError("opendota down")

    client.get_match_player_stats = boom
    for _ in range(6):
        backfill_opendota(store, client, per_player=5, days=0)
    assert len(store.get_unenriched_match_ids(player.id, 0, 10)) == 3   # все ещё в очереди
    assert len(calls) == 6                                              # по одному запросу за прогон, не по матчу


def test_stratz_failure_does_not_burn_attempts(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    od = FakeOpenDota(matches=[od_match(100, 1000)])
    for _ in range(8):
        refresh_player(store, od, player, 2000, stratz=FakeStratz(fail=True))
    assert store.get_match_ids_without_stratz(player.id, 0, 10) == [100]


def test_stratz_miss_backs_off_then_retries(store):
    """Stratz ещё не разобрал матч: повтор не сразу, а через растущую паузу, и позже всё же происходит."""
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    od = FakeOpenDota(matches=[od_match(100, 1000)])
    stratz = FakeStratz({})                               # матч не найден
    refresh_player(store, od, player, 2000, stratz=stratz)
    assert stratz.calls == 1
    refresh_player(store, od, player, 2100, stratz=stratz)   # пауза не вышла — запроса нет
    assert stratz.calls == 1
    refresh_player(store, od, player, 2000 + 301, stratz=stratz)
    assert stratz.calls == 2
    # паузы растут, а сдаёмся не раньше чем через сутки-двое, а не через 15 минут
    assert sum(store.STRATZ_BACKOFF) >= 86400
    stratz.data = {100: {"position": 1, "role": "CORE", "lane": "SAFE_LANE", "imp": 1, "party_size": 1}}
    refresh_player(store, od, player, 2000 + 301 + 901, stratz=stratz)
    assert store.get_matches(player.id)[0]["position"] == 1


def test_refresh_heroes_uses_opendota_list():
    from mmrbot import heroes
    from mmrbot.tracker import refresh_heroes

    class C:
        def get_heroes(self):
            return [{"id": 9998, "localized_name": "Test Hero"}]

    try:
        assert refresh_heroes(C()) == 1 and heroes.hero_name(9998) == "Test Hero"
    finally:
        heroes.HERO_NAMES.pop(9998, None)


def test_closed_history_flag_saved_from_profile(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    od = FakeOpenDota(profile={"rank_tier": 55, "leaderboard_rank": None, "personaname": "x", "fh_unavailable": True},
                      matches=[od_match(1, 1000)])
    refresh_player(store, od, player, 2000)
    assert store.get_player(1, "Вася").fh_unavailable is True
    chat = store.get_or_create_chat(1)
    s = build_player_summary(store, chat, store.get_player(1, "Вася"), now=2000)
    assert s.history_closed is True
    from mmrbot.formatting import render_player_card
    assert "🔒" in render_player_card(s)
    # профиль без признака (сбой) флаг не сбрасывает
    refresh_player(store, FakeOpenDota(profile={"rank_tier": 55, "leaderboard_rank": None, "personaname": "x"},
                                       matches=[od_match(2, 1500)]), store.get_player(1, "Вася"), 90_000)
    assert store.get_player(1, "Вася").fh_unavailable is True


def test_leaver_status_stored_and_shown(store):
    from mmrbot.formatting import render_match_card
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    store.add_matches(player.id, [{**_m(5, 1000), "leaver_status": 3}])
    row = store.get_matches(player.id)[0]
    assert row["leaver_status"] == 3
    assert "покинул" in render_match_card({"player": player, "match": row})


def test_comparison_ignores_perf_built_on_too_few_games(store):
    """Перф по 3 матчам не ставят рядом с перфом по 500: ниже порога метрика в сравнении не участвует."""
    from dataclasses import replace
    p = store.add_player(100, 1, "Base", 5000, 1000, 1000)
    store.add_matches(p.id, [_m(10, 2000)])
    base = build_leaderboard(store, FakeOpenDota(), 100, now=100_000, refresh=False)[0]
    a = replace(base, display_name="A", avg_perf=0.9, enriched_games=3, avg_gpm_window=900.0, detail_games=2)
    b = replace(base, display_name="B", avg_perf=0.5, enriched_games=50, avg_gpm_window=400.0, detail_games=50)
    comp = build_chat_comparison([a, b])
    assert "perf" not in comp["players"]["A"]["ranks"] and "gpm" not in comp["players"]["A"]["ranks"]
    assert comp["players"]["B"]["ranks"]["perf"] == 1


# --- бережём лимит OpenDota ---------------------------------------------

DAY = 86_400
T0 = 1_780_000_000


def test_backfill_enriches_only_recent_window(store):
    """Детали догружаются только за последние дни: вся история ветерана стоила бы тысяч запросов."""
    from mmrbot.tracker import ENRICH_DAYS, backfill_opendota
    store.get_or_create_chat(100)
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    store.add_matches(player.id, [
        {"match_id": 1, "start_time": T0 - (ENRICH_DAYS + 5) * DAY, "player_slot": 0, "radiant_win": True, "lobby_type": 7},
        {"match_id": 2, "start_time": T0 - DAY, "player_slot": 0, "radiant_win": True, "lobby_type": 7},
    ])
    client = FakeOpenDota(match_stats={"gpm": 500, "benchmarks": {"gold_per_min": 0.5}})
    asked = []
    original = client.get_match_player_stats
    client.get_match_player_stats = lambda mid, acc, slot=None: asked.append(mid) or original(mid, acc, slot)
    assert backfill_opendota(store, client, now=T0) == 1
    assert asked == [2]


def test_backfill_stops_when_client_forbids_background(store):
    from mmrbot.tracker import backfill_opendota
    store.get_or_create_chat(100)
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    _seed_matches(store, player, 5)
    client = FakeOpenDota(match_stats={"gpm": 500, "benchmarks": {}})
    budget = {"left": 2}

    def stats(match_id, account_id, player_slot=None):
        budget["left"] -= 1
        return {"gpm": 500, "benchmarks": {}}

    client.get_match_player_stats = stats
    client.background_allowed = lambda: budget["left"] > 0
    assert backfill_opendota(store, client, days=0) == 2  # остаток лимита кончился — остальное в другой раз
    assert len(store.get_unenriched_match_ids(player.id, 0, 10)) == 3


class RecentClient(FakeOpenDota):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.recent = []
        self.recent_calls = 0
        self.limits = []

    def get_matches(self, account_id, limit=200):
        self.limits.append(limit)
        return super().get_matches(account_id, limit)

    def get_recent_matches(self, account_id):
        self.recent_calls += 1
        return list(self.recent)


def test_player_without_matches_is_not_fully_refetched_every_poll(store):
    """Закрытый профиль: полную историю спрашиваем раз в несколько часов, между — лёгкий список."""
    from mmrbot.tracker import EMPTY_RECHECK_SEC
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    client = RecentClient()
    refresh_player(store, client, player, now=T0, fast=True)
    assert client.limits == [None]  # первая загрузка — вся история
    player = store.get_player(100, "Вася")
    refresh_player(store, client, player, now=T0 + 300, fast=True)
    assert client.limits == [None] and client.recent_calls == 1  # дальше — один лёгкий запрос
    player = store.get_player(100, "Вася")
    refresh_player(store, client, player, now=T0 + EMPTY_RECHECK_SEC + 1, fast=True)
    assert client.limits == [None, None]  # время вышло — перепроверяем полностью


def test_player_without_matches_gets_full_history_once_ranked_game_appears(store):
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    client = RecentClient()
    refresh_player(store, client, player, now=T0, fast=True)
    client.recent = [od_match(7, T0 + 100)]
    client.matches = [od_match(7, T0 + 100), od_match(6, T0 - 500)]
    player = store.get_player(100, "Вася")
    assert refresh_player(store, client, player, now=T0 + 300, fast=True) == 2  # открыл профиль — тянем всё


def test_keyless_idle_cooldown_applies_to_player_without_matches(store):
    from mmrbot.tracker import GAME_IDLE_COOLDOWN, GAME_REFRESH_COOLDOWN, detect_new_games
    chat = store.get_or_create_chat(100)
    store.add_player(100, 42, "Вася", None, 0, 0)
    client = RecentClient()
    client.api_key = None
    detect_new_games(store, client, chat, T0)
    calls = client.match_calls + client.recent_calls
    detect_new_games(store, client, chat, T0 + GAME_REFRESH_COOLDOWN + 1)
    assert client.match_calls + client.recent_calls == calls  # пустого игрока часто не дёргаем
    detect_new_games(store, client, chat, T0 + GAME_IDLE_COOLDOWN + 1)
    assert client.match_calls + client.recent_calls == calls + 1


# --- оповещения о матчах -------------------------------------------------

class PerAccountClient(FakeOpenDota):
    api_key = "k"

    def __init__(self):
        super().__init__(profile={"rank_tier": 55, "personaname": "x"})
        self.visible = {}

    def get_matches(self, account_id, limit=200):
        return list(self.visible.get(account_id, []))


def _party_of_two(store, client):
    chat = store.get_or_create_chat(100)
    for account in (1, 2):
        client.visible[account] = [dict(od_match(100, T0 - DAY, slot=account), duration=1800)]
        player = store.add_player(100, account, f"P{account}", 4000, T0 - 2 * DAY, T0 - 2 * DAY)
        refresh_player(store, client, player, T0 - DAY + 3600)
        store.mark_notified(player.id)
    return chat


def test_shared_match_arriving_late_for_teammate_is_not_announced_twice(store):
    from mmrbot.tracker import detect_new_games
    client = PerAccountClient()
    chat = _party_of_two(store, client)
    game = dict(od_match(200, T0 - 2000), duration=1800)
    client.visible[1].insert(0, dict(game, player_slot=1))
    first = [e for e in detect_new_games(store, client, chat, T0) if e["kind"] == "match"]
    client.visible[2].insert(0, dict(game, player_slot=2))  # OpenDota отдал матч напарнику опросом позже
    second = [e for e in detect_new_games(store, client, chat, T0 + 240) if e["kind"] == "match"]
    assert [e["match_id"] for e in first] == [200] and second == []


def test_shared_match_seen_in_one_poll_is_one_event_with_both_players(store):
    from mmrbot.tracker import detect_new_games
    client = PerAccountClient()
    chat = _party_of_two(store, client)
    game = dict(od_match(200, T0 - 2000), duration=1800)
    client.visible[1].insert(0, dict(game, player_slot=1))
    client.visible[2].insert(0, dict(game, player_slot=2))
    events = [e for e in detect_new_games(store, client, chat, T0) if e["kind"] == "match"]
    assert len(events) == 1 and [r["name"] for r in events[0]["rows"]] == ["P1", "P2"]


def test_unsent_alert_is_retried_until_marked(store):
    """mark=False: матч остаётся неоповещённым, пока отправка не подтверждена."""
    from mmrbot.tracker import detect_new_games
    client = PerAccountClient()
    chat = _party_of_two(store, client)
    client.visible[1].insert(0, dict(od_match(200, T0 - 2000, slot=1), duration=1800))
    first = [e for e in detect_new_games(store, client, chat, T0, mark=False) if e["kind"] == "match"]
    again = [e for e in detect_new_games(store, client, chat, T0 + 240, mark=False) if e["kind"] == "match"]
    assert [e["match_id"] for e in first] == [e["match_id"] for e in again] == [200]  # Telegram не принял — повторяем
    store.mark_notified_matches(again[0]["pending"])
    assert [e for e in detect_new_games(store, client, chat, T0 + 480, mark=False) if e["kind"] == "match"] == []


def test_idle_poll_does_not_spend_reserve_on_old_backlog(store):
    """Опрос без новых игр не тратит запросы на старые детали, когда клиент бережёт остаток лимита."""
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    client = FakeOpenDota(matches=[od_match(i, T0 - i * 3600) for i in range(1, 6)],
                          match_stats={"gpm": 500, "benchmarks": {}})
    asked = []
    client.get_match_player_stats = lambda mid, acc, slot=None: asked.append(mid) or {"gpm": 500, "benchmarks": {}}
    client.background_allowed = lambda: False
    assert refresh_player(store, client, player, now=T0) == 5
    assert len(asked) == 3  # новые игры — обогащаем сразу, даже на исходе лимита
    asked.clear()
    refresh_player(store, client, store.get_player(100, "Вася"), now=T0 + 600)
    assert asked == []  # новых игр нет — бэклог подождёт


# --- A2: провайдер лежит — в сеть не ходим (команды и фон) -------------------------------

def _down(name="OpenDota"):
    from mmrbot.health import ProviderHealth
    health = ProviderHealth(name)
    health.failure(RuntimeError("down"))
    return health


def _down_od():
    client = FakeOpenDota(matches=[od_match(500, 5000)])
    client.health = _down()
    return client


def test_refresh_chat_does_not_touch_client_when_opendota_is_down(store):
    from mmrbot.tracker import refresh_chat
    store.add_player(1, 11, "Вася", None, 0, 0)
    store.add_player(1, 22, "Петя", None, 0, 0)
    client = _down_od()
    players = refresh_chat(store, client, 1, 1_000_000)
    assert {p.display_name for p in players} == {"Вася", "Петя"}  # игроки из БД
    assert (client.profile_calls, client.match_calls, client.refresh_calls) == (0, 0, 0)


def test_refresh_player_skips_opendota_but_still_enriches_from_stratz(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    store.add_matches(player.id, [{**od_match(100, 1000)}])
    client = _down_od()
    stratz = FakeStratz({100: {"position": 3, "role": "CORE", "lane": "OFF_LANE", "imp": 7, "party_size": 1}})
    assert refresh_player(store, client, player, 2000, stratz=stratz) == 0
    assert (client.profile_calls, client.match_calls, client.refresh_calls) == (0, 0, 0)
    assert store.get_matches(player.id)[0]["position"] == 3  # Stratz жив — дозаполнение идёт без OpenDota
    assert store.get_player_by_account_id(1, 42).updated_ts is None  # «обновлён» не ставим — сверки не было


def test_stratz_enrichment_is_skipped_when_stratz_is_down(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    od = FakeOpenDota(matches=[od_match(100, 1000)])
    stratz = FakeStratz({100: {"position": 3}})
    stratz.health = _down("Stratz")
    assert refresh_player(store, od, player, 2000, stratz=stratz) == 1  # матчи OpenDota сохранены
    assert stratz.calls == 0
    assert store.get_match_ids_without_stratz(player.id, 0, 10) == [100]  # попытка не сожжена


def test_background_jobs_do_nothing_when_providers_are_down(store):
    from mmrbot.tracker import backfill_opendota, backfill_stratz, detect_steam_changes, finish_refresh
    store.get_or_create_chat(100)
    player = store.add_player(100, 42, "Вася", None, 0, 0)
    store.add_matches(player.id, [od_match(1, 1000)])

    class Calls(FakeOpenDota):
        extra = 0

        def get_match_player_stats(self, match_id, account_id, player_slot=None):
            self.extra += 1
            return {}

    client = Calls()
    client.health = _down()
    stratz = FakeStratz({1: {"position": 1}})
    stratz.health = _down("Stratz")

    assert backfill_opendota(store, client, days=0) == 0
    assert finish_refresh(store, client, 100, days=0) == 0
    assert detect_steam_changes(store, client) == []
    assert backfill_stratz(store, stratz) == 0
    assert (client.profile_calls, client.match_calls, client.refresh_calls, client.extra) == (0, 0, 0, 0)
    assert stratz.calls == 0


def test_detect_new_games_announces_db_matches_without_network_when_opendota_is_down(store):
    from mmrbot.tracker import detect_new_games
    now = 1_000_000
    store.get_or_create_chat(100)
    player = store.add_player(100, 42, "Вася", 5000, 0, 0)
    store.add_matches(player.id, [{**od_match(7, now - 600), "duration": 1800}])
    client = _down_od()
    events = detect_new_games(store, client, store.get_or_create_chat(100), now, mark=False)
    assert [e["match_id"] for e in events if e["kind"] == "match"] == [7]  # матч уже в БД — оповещение не теряем
    assert client.match_calls == 0 and client.profile_calls == 0


# --- A5: ожидаемые сетевые сбои — одна строка в логе, без трейсбеков ----------------------

class _RaisingOpenDota(FakeOpenDota):
    def __init__(self, exc):
        super().__init__()
        self.exc = exc

    def get_matches(self, account_id, limit=200):
        raise self.exc


def _tracker_records(caplog):
    return [r for r in caplog.records if r.name == "mmrbot.tracker"]


def test_refresh_chat_network_failure_is_one_line_without_traceback(store, caplog):
    import logging

    import requests
    from mmrbot.tracker import refresh_chat
    store.add_player(1, 11, "Вася", None, 0, 0)
    with caplog.at_level(logging.DEBUG, logger="mmrbot.tracker"):
        refresh_chat(store, _RaisingOpenDota(requests.exceptions.ConnectTimeout("boom")), 1, 1_000_000)
    records = _tracker_records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.WARNING
    assert records[0].exc_info is None
    assert "ConnectTimeout" in records[0].getMessage() and "Traceback" not in caplog.text


def test_refresh_chat_unexpected_error_keeps_traceback(store, caplog):
    import logging

    from mmrbot.tracker import refresh_chat
    store.add_player(1, 11, "Вася", None, 0, 0)
    with caplog.at_level(logging.DEBUG, logger="mmrbot.tracker"):
        refresh_chat(store, _RaisingOpenDota(KeyError("bug")), 1, 1_000_000)
    records = _tracker_records(caplog)
    assert len(records) == 1 and records[0].levelno == logging.ERROR
    assert records[0].exc_info is not None  # баг в нашем коде не должен прятаться


def test_outage_of_real_client_logs_one_warning_for_the_whole_chat(store, caplog):
    """Четыре игрока обновляются параллельно, OpenDota лежит: в логе одна строка о падении и одна от трекера."""
    import logging

    import requests
    from mmrbot.opendota import OpenDota
    from mmrbot.tracker import refresh_chat

    class Down:
        def get(self, *a, **kw):
            raise requests.exceptions.ConnectTimeout("connect timeout")

        post = get

    for n in range(4):
        store.add_player(1, 100 + n, f"Игрок{n}", None, 0, 0)
    od = OpenDota(session=Down(), min_interval=0)
    with caplog.at_level(logging.DEBUG):
        refresh_chat(store, od, 1, 1_000_000)
        refresh_chat(store, od, 1, 1_000_001)  # вторая команда в паузу — вообще без записей уровня WARNING
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [r.name for r in warnings].count("mmrbot.health") == 1
    assert [r.name for r in warnings].count("mmrbot.tracker") <= 1
    assert all(r.exc_info is None for r in warnings) and "Traceback" not in caplog.text


def test_stratz_network_failure_in_enrichment_is_one_line(store, caplog):
    import logging

    import requests
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    store.add_matches(player.id, [od_match(100, 1000)])

    class DownStratz:
        def get_matches(self, *a, **kw):
            raise requests.exceptions.ConnectTimeout("boom")

    from mmrbot.tracker import _enrich_from_stratz
    with caplog.at_level(logging.DEBUG, logger="mmrbot.tracker"):
        _enrich_from_stratz(store, DownStratz(), player, 2000)
    records = _tracker_records(caplog)
    assert [r.levelno for r in records] == [logging.WARNING] and records[0].exc_info is None


# --- B2: одно обновление игрока за раз (single-flight) -----------------------------------

class _SlowOpenDota(FakeOpenDota):
    def __init__(self, delay=0.2, **kw):
        super().__init__(**kw)
        self.delay = delay
        self.fail = None

    def get_matches(self, account_id, limit=200):
        import time as _t
        _t.sleep(self.delay)
        if self.fail:
            self.match_calls += 1  # обращение было, даже если оно упало
            raise self.fail
        return super().get_matches(account_id, limit)


def _in_threads(*calls):
    import threading
    results = [None] * len(calls)

    def runner(i, fn):
        try:
            results[i] = ("ok", fn())
        except Exception as exc:  # noqa: BLE001 — тест собирает исход каждого потока
            results[i] = ("err", exc)

    threads = [threading.Thread(target=runner, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_refreshes_of_same_player_hit_the_client_once(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    client = _SlowOpenDota(matches=[od_match(100, 1000), od_match(101, 1100)])
    results = _in_threads(*[lambda: refresh_player(store, client, player, 2000, fast=True)] * 3)
    assert client.match_calls == 1                       # лимит OpenDota не тратим на дубли
    assert [r[0] for r in results] == ["ok"] * 3 and {r[1] for r in results} == {2}  # все получили результат


def test_player_in_two_chats_is_refreshed_once(store):
    """game_watch и команда (или два чата с одним аккаунтом) не обновляют игрока дважды."""
    first = store.add_player(1, 42, "Вася", None, 0, 0)
    second = store.add_player(2, 42, "Вася", None, 0, 0)
    client = _SlowOpenDota(matches=[od_match(100, 1000)])
    _in_threads(lambda: refresh_player(store, client, first, 2000, fast=True),
                lambda: refresh_player(store, client, second, 2000, fast=True))
    assert client.match_calls == 1 and store.has_matches(first.id)


def test_sequential_refreshes_both_go_to_the_network(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    client = _SlowOpenDota(delay=0, matches=[od_match(100, 1000)])
    refresh_player(store, client, player, 2000, fast=True)
    refresh_player(store, client, player, 2001, fast=True)
    assert client.match_calls == 2                       # реестр очищается: следующий опрос — снова в сеть


def test_different_players_refresh_in_parallel(store):
    import time as _t
    a = store.add_player(1, 11, "А", None, 0, 0)
    b = store.add_player(1, 22, "Б", None, 0, 0)
    client = _SlowOpenDota(delay=0.3, matches=[od_match(100, 1000)])
    started = _t.monotonic()
    _in_threads(lambda: refresh_player(store, client, a, 2000, fast=True),
                lambda: refresh_player(store, client, b, 2000, fast=True))
    assert client.match_calls == 2 and _t.monotonic() - started < 0.55


def test_failed_refresh_error_reaches_joined_callers_and_registry_is_released(store):
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    client = _SlowOpenDota(matches=[od_match(100, 1000)])
    client.fail = RuntimeError("boom")
    results = _in_threads(*[lambda: refresh_player(store, client, player, 2000, fast=True)] * 2)
    assert client.match_calls == 1 and [r[0] for r in results] == ["err", "err"]
    client.fail = None
    assert refresh_player(store, client, player, 2001, fast=True) == 1   # после сбоя реестр свободен


def test_join_wait_is_bounded(store, monkeypatch):
    """Ждать чужое обновление бесконечно нельзя: по таймауту присоединившийся берёт БД (0 новых)."""
    import mmrbot.tracker as tr
    monkeypatch.setattr(tr, "SINGLE_FLIGHT_WAIT", 0.05)
    player = store.add_player(1, 42, "Вася", None, 0, 0)
    client = _SlowOpenDota(delay=0.4, matches=[od_match(100, 1000)])
    import time as _t
    started = {}

    def joiner():
        _t.sleep(0.05)
        started["t"] = _t.monotonic()
        value = refresh_player(store, client, player, 2000, fast=True)
        started["took"] = _t.monotonic() - started["t"]
        return value

    results = _in_threads(lambda: refresh_player(store, client, player, 2000, fast=True), joiner)
    assert results[0] == ("ok", 1) and results[1] == ("ok", 0)
    assert started["took"] < 0.3 and client.match_calls == 1
