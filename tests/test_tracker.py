import pytest

from mmrbot.storage import Storage
from mmrbot.tracker import build_leaderboard, build_player_summary, refresh_player


class FakeOpenDota:
    """Фейковый клиент: без сети, возвращает заранее заданные профиль и матчи."""

    def __init__(self, profile=None, matches=None):
        self.profile = profile or {"rank_tier": None, "leaderboard_rank": None, "personaname": None}
        self.matches = matches or []
        self.profile_calls = 0
        self.match_calls = 0

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

def test_refresh_stores_only_ranked_since_created(store):
    player = store.add_player(100, 42, "Вася", 5000, anchor_ts=1000, created_ts=1000)
    client = FakeOpenDota(
        profile={"rank_tier": 75, "leaderboard_rank": None, "personaname": "Вася"},
        matches=[
            od_match(1, start_time=500, lobby_type=7),    # раньше created_ts — игнор
            od_match(2, start_time=1500, lobby_type=0),   # не ранкед — игнор
            od_match(3, start_time=1500, lobby_type=7),   # ок
            od_match(4, start_time=2500, lobby_type=7),   # ок
        ],
    )
    new_count = refresh_player(store, client, player, now=3000)
    assert new_count == 2
    stored = store.get_matches(player.id)
    assert {m["match_id"] for m in stored} == {3, 4}


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
