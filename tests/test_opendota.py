from mmrbot.opendota import OpenDota


class FakeResp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params or {}})
        return FakeResp(self.payload)


def test_get_profile_extracts_fields():
    session = FakeSession({"profile": {"personaname": "Вася"}, "rank_tier": 75, "leaderboard_rank": None})
    od = OpenDota(session=session, min_interval=0)
    profile = od.get_profile(42)
    assert profile["rank_tier"] == 75
    assert profile["leaderboard_rank"] is None
    assert profile["personaname"] == "Вася"
    assert session.calls[0]["url"].endswith("/players/42")


def test_get_matches_returns_list():
    session = FakeSession([{"match_id": 1, "lobby_type": 7}, {"match_id": 2, "lobby_type": 0}])
    od = OpenDota(session=session, min_interval=0)
    matches = od.get_matches(42)
    assert [m["match_id"] for m in matches] == [1, 2]
    assert session.calls[0]["url"].endswith("/players/42/matches")


def test_api_key_added_to_params():
    session = FakeSession({"rank_tier": 11})
    od = OpenDota(session=session, min_interval=0, api_key="SECRET")
    od.get_profile(42)
    assert session.calls[0]["params"].get("api_key") == "SECRET"


def test_no_api_key_means_no_param():
    session = FakeSession({"rank_tier": 11})
    od = OpenDota(session=session, min_interval=0)
    od.get_profile(42)
    assert "api_key" not in session.calls[0]["params"]


def test_get_lanes_normalizes_lane_role():
    session = FakeSession({"lane_role": {"1": {"games": 10, "win": 6}, "2": {"games": 4, "win": 1}}})
    od = OpenDota(session=session, min_interval=0)
    lanes = od.get_lanes(42)
    assert lanes[1] == (10, 6)
    assert lanes[2] == (4, 1)
    assert session.calls[0]["url"].endswith("/players/42/counts")


def test_get_lanes_empty_when_absent():
    od = OpenDota(session=FakeSession({}), min_interval=0)
    assert od.get_lanes(42) == {}


def test_get_gpm_distribution_median_and_best():
    session = FakeSession([
        {"x": 0, "games": 1, "win": 0},
        {"x": 100, "games": 2, "win": 1},
        {"x": 200, "games": 1, "win": 1},
    ])
    od = OpenDota(session=session, min_interval=0)
    dist = od.get_gpm_distribution(42)
    assert dist["median"] == 100  # 4 игры, медиана падает в бакет 100
    assert dist["best"] == 200
    assert session.calls[0]["url"].endswith("/players/42/histograms/gold_per_min")


def test_get_gpm_distribution_empty():
    od = OpenDota(session=FakeSession([]), min_interval=0)
    assert od.get_gpm_distribution(42) == {"median": None, "best": None}


def test_get_totals_computes_averages():
    session = FakeSession([
        {"field": "gold_per_min", "n": 10, "sum": 5000},   # avg 500
        {"field": "xp_per_min", "n": 10, "sum": 6000},      # avg 600
        {"field": "last_hits", "n": 10, "sum": 1800},       # avg 180
        {"field": "kills", "n": 10, "sum": 100},            # игнор
    ])
    od = OpenDota(session=session, min_interval=0)
    totals = od.get_totals(42)
    assert totals["gpm"] == 500
    assert totals["xpm"] == 600
    assert totals["last_hits"] == 180
    assert session.calls[0]["url"].endswith("/players/42/totals")


def test_get_totals_handles_missing_fields():
    session = FakeSession([])
    od = OpenDota(session=session, min_interval=0)
    totals = od.get_totals(42)
    assert totals == {"gpm": None, "xpm": None, "last_hits": None}


def test_concurrent_calls_are_serialized_by_lock():
    """Один общий клиент из нескольких потоков не должен делать запросы одновременно."""
    import threading
    import time

    class ConcurrencyProbe:
        def __init__(self):
            self.active = 0
            self.max_active = 0
            self._lock = threading.Lock()

        def get(self, url, params=None, timeout=None):
            with self._lock:
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            time.sleep(0.02)
            with self._lock:
                self.active -= 1
            return FakeResp({"rank_tier": 11})

    probe = ConcurrencyProbe()
    od = OpenDota(session=probe, min_interval=0)
    threads = [threading.Thread(target=lambda: od.get_profile(1)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert probe.max_active == 1  # запросы не пересекались
