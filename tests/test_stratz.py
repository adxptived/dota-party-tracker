from mmrbot.stratz import Stratz


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
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        item = self.payloads.pop(0)
        return item if isinstance(item, FakeResp) else FakeResp(item)


def _match(position="POSITION_1", imp=12, lobby="RANKED"):
    return {
        "lobbyType": lobby,
        "players": [{
            "position": position, "role": "CORE", "lane": "SAFE_LANE", "imp": imp,
            "goldPerMinute": 600, "experiencePerMinute": 700, "networth": 30000,
            "heroDamage": 25000, "towerDamage": 3000, "heroHealing": 0,
            "numLastHits": 400, "numDenies": 20, "level": 25,
        }],
    }


def test_get_matches_maps_fields_and_skips_missing():
    session = FakeSession([{"data": {"m0": _match(), "m1": None, "m2": _match("POSITION_5", -4)}}])
    st = Stratz("key", session=session, min_interval=0)
    result = st.get_matches(42, [100, 101, 102])
    assert set(result) == {100, 102}
    assert result[100]["position"] == 1 and result[100]["role"] == "CORE"
    assert result[100]["lane"] == "SAFE_LANE" and result[100]["imp"] == 12
    assert result[100]["gpm"] == 600 and result[100]["net_worth"] == 30000 and result[100]["last_hits"] == 400
    assert result[102]["position"] == 5 and result[102]["imp"] == -4


def test_query_uses_aliases_ids_and_headers():
    session = FakeSession([{"data": {"m0": None, "m1": None}}])
    Stratz("secret", session=session, min_interval=0).get_matches(42, [100, 101])
    call = session.calls[0]
    assert call["headers"]["Authorization"] == "Bearer secret"
    assert call["headers"]["User-Agent"] == "STRATZ_API"
    assert call["json"]["variables"] == {}
    assert "$acc" not in call["json"]["query"]  # неиспользуемая переменная — 400 у Stratz
    assert "m0: match(id: 100)" in call["json"]["query"] and "m1: match(id: 101)" in call["json"]["query"]


def test_chunks_large_batches():
    payloads = [{"data": {f"m{i}": None for i in range(10)}}, {"data": {f"m{i}": None for i in range(3)}}]
    session = FakeSession(payloads)
    Stratz("k", session=session, min_interval=0, chunk=10).get_matches(1, list(range(13)))
    assert len(session.calls) == 2


def test_unknown_position_is_none_and_empty_ids_make_no_request():
    session = FakeSession([{"data": {"m0": _match(position=None)}}])
    st = Stratz("k", session=session, min_interval=0)
    assert st.get_matches(1, [5])[5]["position"] is None
    assert st.get_matches(1, []) == {}
    assert len(session.calls) == 1


def test_retries_on_429_then_succeeds():
    session = FakeSession([FakeResp({}, 429), {"data": {"m0": _match()}}])
    st = Stratz("k", session=session, min_interval=0, retry_sleep=0)
    assert 5 in st.get_matches(1, [5])
    assert len(session.calls) == 2


def test_graphql_errors_raise():
    session = FakeSession([{"errors": [{"message": "boom"}]}])
    st = Stratz("k", session=session, min_interval=0)
    try:
        st.get_matches(1, [5])
    except RuntimeError as exc:
        assert "boom" in str(exc)
    else:
        raise AssertionError("ожидали RuntimeError")


def _full_player(acc, radiant, hero, pos="POSITION_1", name="Ник"):
    return {"steamAccountId": acc, "isRadiant": radiant, "heroId": hero, "position": pos, "role": "CORE",
            "lane": "SAFE_LANE", "kills": 5, "deaths": 2, "assists": 7, "imp": 10,
            "goldPerMinute": 600, "experiencePerMinute": 700, "networth": 30000, "heroDamage": 25000,
            "towerDamage": 3000, "heroHealing": 0, "numLastHits": 400, "numDenies": 20, "level": 25,
            "steamAccount": {"name": name}}


def test_get_match_returns_full_match():
    payload = {"data": {"match": {
        "id": 77, "lobbyType": "RANKED", "durationSeconds": 2000, "didRadiantWin": True, "startDateTime": 1700000000,
        "players": [_full_player(1, True, 2, name="Вася"), _full_player(2, False, 5, "POSITION_5", None)],
    }}}
    session = FakeSession([payload])
    match = Stratz("k", session=session, min_interval=0).get_match(77)
    assert match["match_id"] == 77 and match["radiant_win"] is True
    assert match["duration"] == 2000 and match["start_time"] == 1700000000
    first, second = match["players"]
    assert first["account_id"] == 1 and first["name"] == "Вася" and first["is_radiant"] is True
    assert first["position"] == 1 and first["hero_id"] == 2 and first["imp"] == 10
    assert first["kills"] == 5 and first["net_worth"] == 30000
    assert second["position"] == 5 and second["name"] is None
    assert "match(id: 77)" in session.calls[0]["json"]["query"]


def test_get_match_reads_lone_druid_bear_inventory():
    druid = dict(_full_player(1, True, 80), item0Id=240, item1Id=16,
                 additionalUnit={"item0Id": 1, "item1Id": 158, "item2Id": 0, "item3Id": None, "item4Id": 116,
                                 "item5Id": None, "neutral0Id": 1168})
    other = dict(_full_player(2, False, 5), additionalUnit=None)
    payload = {"data": {"match": {"id": 78, "durationSeconds": 2000, "didRadiantWin": True, "startDateTime": 1,
                                  "players": [druid, other, _full_player(3, False, 6)]}}}
    session = FakeSession([payload])
    match = Stratz("k", session=session, min_interval=0).get_match(78)
    first, second, third = match["players"]
    assert first["bear_items"] == [1, 158, 116] and first["bear_neutral"] == 1168  # пустые слоты не берём
    assert "bear_items" not in second and "bear_items" not in third  # у других героев второго инвентаря нет
    query = session.calls[0]["json"]["query"]
    assert "additionalUnit" in query and "item0Id" in query


def test_get_match_missing_returns_none():
    session = FakeSession([{"data": {"match": None}}])
    assert Stratz("k", session=session, min_interval=0).get_match(1) is None


def _party_match(me_party, others):
    """Матч с 10 игроками: наш (acc 42, команда radiant) + остальные (acc, isRadiant, partyId)."""
    row = lambda acc, rad, party: {"steamAccountId": acc, "isRadiant": rad, "partyId": party,
                                   "position": "POSITION_1", "imp": 1}
    return {"players": [row(42, True, me_party)] + [row(a, r, p) for a, r, p in others]}


def test_party_size_counts_teammates_with_same_party_id():
    match = _party_match(7, [(1, True, 7), (2, True, 7), (3, True, 9), (4, False, 7)])  # враг с тем же id — не в счёт
    session = FakeSession([{"data": {"m0": match}}])
    info = Stratz("k", session=session, min_interval=0).get_matches(42, [5])[5]
    assert info["party_size"] == 3


def test_party_size_is_one_when_no_party_id():
    session = FakeSession([{"data": {"m0": _party_match(None, [(1, True, None), (2, False, None)])}}])
    assert Stratz("k", session=session, min_interval=0).get_matches(42, [5])[5]["party_size"] == 1


def test_hidden_profile_found_by_side_and_hero():
    rows = [
        {"steamAccountId": None, "isRadiant": True, "heroId": 8, "position": "POSITION_2", "imp": 3},
        {"steamAccountId": 7, "isRadiant": True, "heroId": 9, "position": "POSITION_1", "imp": 1},
        {"steamAccountId": None, "isRadiant": False, "heroId": 8, "position": "POSITION_4", "imp": 0},
    ]
    session = FakeSession([{"data": {"m0": {"lobbyType": "RANKED", "players": rows}}}] * 2)
    st = Stratz("k", session=session, min_interval=0)
    assert st.get_matches(42, [1]) == {}                                   # без подсказки — не угадываем
    assert st.get_matches(42, [1], hints={1: (True, 8)})[1]["position"] == 2


# --- предохранитель: Stratz недоступен --------------------------------------------------

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def mono(self):
        return self.now

    def wall(self):
        return 1_700_000_000.0 + (self.now - 1000.0)


def _st_with_clock(session, **kw):
    from mmrbot.health import ProviderHealth
    clock = _Clock()
    health = ProviderHealth("Stratz", clock=clock.mono, wall=clock.wall)
    return Stratz("k", session=session, min_interval=0, retry_sleep=0, health=health, **kw), clock


class _DownSession:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        import requests
        self.calls.append(url)
        raise requests.exceptions.ConnectTimeout("connect timeout")


def test_network_failure_is_not_retried_and_next_calls_fail_fast():
    """Stratz лёг: одна попытка (без 3 × таймаут), следующие вызовы отказывают без обращения в сеть."""
    import requests
    from mmrbot.health import ProviderUnavailable
    session = _DownSession()
    st, clock = _st_with_clock(session)
    try:
        st.get_matches(1, [5])
        assert False, "ожидали ошибку сети"
    except requests.exceptions.ConnectionError:
        pass
    assert len(session.calls) == 1
    for call in (lambda: st.get_matches(1, [5]), lambda: st.get_match(7)):
        try:
            call()
            assert False, "ожидали отказ предохранителя"
        except ProviderUnavailable:
            pass
    assert len(session.calls) == 1  # пауза: в сеть не ходили
    clock.now += 61  # пауза истекла — одна пробная попытка
    try:
        st.get_matches(1, [5])
    except requests.exceptions.ConnectionError:
        pass
    assert len(session.calls) == 2


def test_server_errors_on_all_attempts_open_the_breaker():
    from mmrbot.health import ProviderUnavailable
    session = FakeSession([FakeResp({}, 503)] * 3)
    st, _ = _st_with_clock(session)
    try:
        st.get_matches(1, [5])
        assert False, "ожидали ошибку"
    except RuntimeError:
        pass
    try:
        st.get_matches(1, [5])
        assert False, "ожидали отказ предохранителя"
    except ProviderUnavailable:
        pass
    assert len(session.calls) == 3


def test_graphql_error_does_not_open_the_breaker():
    """Stratz ответил (пусть и ошибкой запроса) — он жив, остальные запросы идут как обычно."""
    session = FakeSession([{"errors": [{"message": "boom"}]}, {"data": {"m0": _match()}}])
    st, _ = _st_with_clock(session)
    try:
        st.get_matches(1, [5])
    except RuntimeError:
        pass
    assert 5 in st.get_matches(1, [5])
    assert st.health.status()["state"] == "up"


def test_health_is_available_for_status():
    st, _ = _st_with_clock(FakeSession([]))
    assert st.health.status()["state"] == "up" and st.health.name == "Stratz"


# --- B5: кэш полного матча ----------------------------------------------------------------

def _match_payload(match_id, start=None):
    import time as _t
    return {"data": {"match": {
        "id": match_id, "durationSeconds": 2000, "didRadiantWin": True,
        "startDateTime": int(_t.time()) - 600 if start is None else start,
        "players": [_full_player(1, True, 2, name="Вася")],
    }}}


def _clocked(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("mmrbot.stratz.time.monotonic", lambda: clock[0])
    return clock


def test_get_match_is_cached_one_http_request(monkeypatch):
    _clocked(monkeypatch)
    session = FakeSession([_match_payload(77)])
    st = Stratz("k", session=session, min_interval=0)
    first, second = st.get_match(77), st.get_match(77)
    assert first == second and first["match_id"] == 77
    assert len(session.calls) == 1  # /match, «📝 Текстом» и «Весь матч» — один запрос


def test_fresh_match_cache_expires_after_ten_minutes(monkeypatch):
    clock = _clocked(monkeypatch)
    session = FakeSession([_match_payload(77), _match_payload(77)])
    st = Stratz("k", session=session, min_interval=0)
    st.get_match(77)
    clock[0] += 599
    st.get_match(77)
    assert len(session.calls) == 1
    clock[0] += 2  # 10 минут вышли: свежий матч мог дополниться (разбор Stratz)
    st.get_match(77)
    assert len(session.calls) == 2


def test_old_match_is_cached_for_a_day(monkeypatch):
    import time as _t
    clock = _clocked(monkeypatch)
    old = int(_t.time()) - 3 * 86_400
    session = FakeSession([_match_payload(5, start=old), _match_payload(5, start=old)])
    st = Stratz("k", session=session, min_interval=0)
    st.get_match(5)
    clock[0] += 23 * 3600
    st.get_match(5)
    assert len(session.calls) == 1  # матч старше суток уже не меняется
    clock[0] += 2 * 3600
    st.get_match(5)
    assert len(session.calls) == 2


def test_missing_match_is_not_cached(monkeypatch):
    _clocked(monkeypatch)
    session = FakeSession([{"data": {"match": None}}, _match_payload(9)])
    st = Stratz("k", session=session, min_interval=0)
    assert st.get_match(9) is None
    assert st.get_match(9)["match_id"] == 9  # Stratz мог ещё не разобрать матч — спросим снова
    assert len(session.calls) == 2


def test_match_cache_is_lru_bounded(monkeypatch):
    _clocked(monkeypatch)
    ids = list(range(1, Stratz.MATCH_CACHE_SIZE + 3))
    session = FakeSession([_match_payload(i) for i in ids] + [_match_payload(1)])
    st = Stratz("k", session=session, min_interval=0)
    for i in ids:
        st.get_match(i)
    assert len(st._match_cache) == Stratz.MATCH_CACHE_SIZE
    st.get_match(1)  # самый старый вытеснен — снова запрос
    assert len(session.calls) == len(ids) + 1


def test_cached_match_is_served_while_stratz_is_down(monkeypatch):
    """Кэш отвечает и во время паузы предохранителя — «Весь матч» не падает из-за лежащего Stratz."""
    from mmrbot.health import ProviderHealth
    _clocked(monkeypatch)
    session = FakeSession([_match_payload(77)])
    health = ProviderHealth("Stratz")
    st = Stratz("k", session=session, min_interval=0, health=health)
    st.get_match(77)
    health.failure(RuntimeError("down"))
    assert st.get_match(77)["match_id"] == 77
