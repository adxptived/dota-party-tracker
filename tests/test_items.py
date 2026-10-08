from mmrbot import items
from mmrbot.item_icons import ICON_URL, ItemIcons
from mmrbot.opendota import OpenDota
from mmrbot.tracker import enrich_alert_items, refresh_items


class FakeResp:
    def __init__(self, status=200, content=b"PNG", content_type="image/png"):
        self.status_code = status
        self.content = content
        self.headers = {"Content-Type": content_type}


class FakeIconSession:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        return FakeResp()


class FakeApiResp:
    status_code = 200
    headers: dict = {}

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeApiSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None, **kwargs):
        self.calls.append(url)
        return FakeApiResp(self.payload)


def _reset_items(saved):
    items.ITEM_SLUGS.clear()
    items.ITEM_SLUGS.update(saved)


def test_update_items_learns_slugs_and_skips_garbage():
    saved = dict(items.ITEM_SLUGS)
    try:
        assert items.update_items({"1": "blink", "63": "power_treads", "x": "bad", "5": 7, "6": ""}) == 2
        assert items.item_slug(1) == "blink" and items.item_slug(63) == "power_treads"
        assert items.item_slug(0) is None and items.item_slug(None) is None and items.item_slug(5) is None
        assert items.update_items(None) == 0 and items.update_items([1, 2]) == 0
    finally:
        _reset_items(saved)


def test_opendota_get_item_ids_and_refresh_items():
    saved = dict(items.ITEM_SLUGS)
    try:
        session = FakeApiSession({"1": "blink", "116": "black_king_bar"})
        od = OpenDota(session=session, min_interval=0)
        assert od.get_item_ids() == {"1": "blink", "116": "black_king_bar"}
        assert session.calls[0].endswith("/constants/item_ids")
        assert refresh_items(od) == 2
        assert items.item_slug(116) == "black_king_bar"
    finally:
        _reset_items(saved)


def test_opendota_get_item_ids_ignores_wrong_format():
    od = OpenDota(session=FakeApiSession([1, 2]), min_interval=0)
    assert od.get_item_ids() == {}


def test_item_icons_use_item_url_and_skip_unknown_items(tmp_path):
    saved = dict(items.ITEM_SLUGS)
    try:
        items.update_items({"1": "blink"})
        session = FakeIconSession()
        icons = ItemIcons(str(tmp_path), session=session)
        assert icons.get(1) == b"PNG"
        assert icons.get(1) == b"PNG"
        assert icons.get(404) is None and icons.get(None) is None and icons.get(0) is None
        assert session.urls == [ICON_URL.format(slug="blink")]
        assert (tmp_path / "blink.png").read_bytes() == b"PNG"
        assert icons.get_many([1, 1, 404, None]) == {1: b"PNG"}
    finally:
        _reset_items(saved)


def test_match_player_stats_carry_items_and_neutral():
    match = {"players": [{"account_id": 42, "item_0": 1, "item_1": 0, "item_2": 116, "item_3": None,
                          "item_4": 63, "item_5": 0, "item_neutral": 300, "backpack_0": 5}]}
    od = OpenDota(session=FakeApiSession(match), min_interval=0)
    stats = od.get_match_player_stats(1, 42)
    assert stats["items"] == [1, 116, 63]  # пустые слоты (0/None) выкидываем, рюкзак не берём
    assert stats["neutral_item"] == 300


class FakeClient:
    def __init__(self, stats=None, down=False, boom=False):
        self.stats = stats or {}
        self.calls = []
        self.boom = boom
        self.health = type("H", (), {"available": lambda s: not down})()

    def get_match_player_stats(self, match_id, account_id, player_slot=None):
        self.calls.append((match_id, account_id))
        if self.boom:
            raise RuntimeError("сеть")
        return self.stats.get(account_id)


def _event():
    return {"kind": "match", "match_id": 9, "rows": [
        {"name": "A", "account_id": 1, "kills": 1}, {"name": "B", "account_id": 2, "kills": 2},
    ]}


def test_enrich_alert_items_adds_build_and_farm_to_rows():
    client = FakeClient({1: {"items": [1, 2], "neutral_item": 300, "net_worth": 21400, "last_hits": 312, "denies": 14,
                             "hero_healing": 900}})
    event = _event()
    enrich_alert_items(client, event)
    first, second = event["rows"]
    assert first["items"] == [1, 2] and first["neutral_item"] == 300
    assert first["net_worth"] == 21400 and first["last_hits"] == 312 and first["denies"] == 14
    assert "items" not in second  # у игрока нет данных матча — строка остаётся как была
    assert first["kills"] == 1  # то, что уже есть в строке, не затираем


def test_enrich_alert_items_is_best_effort():
    event = _event()
    enrich_alert_items(FakeClient(boom=True), event)  # сбой сети не бросает
    assert "items" not in event["rows"][0]
    down = FakeClient({1: {"items": [1]}}, down=True)
    enrich_alert_items(down, event)  # предохранитель закрыт — в сеть не ходим
    assert down.calls == [] and "items" not in event["rows"][0]


def test_match_player_stats_item_times_and_upgrades_from_purchase_log():
    saved = dict(items.ITEM_SLUGS)
    try:
        items.update_items({"1": "blink", "63": "power_treads", "116": "black_king_bar"})
        match = {"players": [{
            "account_id": 42, "item_0": 63, "item_1": 1, "item_2": 116, "item_3": 0, "tower_damage": 6589,
            "aghanims_shard": 1, "aghanims_scepter": 0,
            "purchase_log": [{"time": -30, "key": "tango"}, {"time": 300, "key": "power_treads"},
                             {"time": 700, "key": "blink"}, {"time": 1100, "key": "blink"},  # перекупка — берём последнюю
                             {"time": 1450, "key": "aghanims_shard"}],
        }]}
        stats = OpenDota(session=FakeApiSession(match), min_interval=0).get_match_player_stats(1, 42)
        assert stats["items"] == [63, 1, 116]
        assert stats["item_times"] == [300, 1100, None]  # у ЧЕРНОЙ ПЕРЕЧНИЦЫ покупки в логе нет — время неизвестно
        assert stats["shard"] is True and stats["shard_time"] == 1450
        assert stats["scepter"] is False and stats["scepter_time"] is None
        assert stats["tower_damage"] == 6589
    finally:
        _reset_items(saved)


def test_scepter_and_shard_also_detected_from_purchase_log_and_unparsed_match_has_no_times():
    saved = dict(items.ITEM_SLUGS)
    try:
        items.update_items({"1": "blink"})
        parsed = {"players": [{"account_id": 42, "item_0": 1,
                               "purchase_log": [{"time": 2000, "key": "ultimate_scepter"}]}]}
        stats = OpenDota(session=FakeApiSession(parsed), min_interval=0).get_match_player_stats(1, 42)
        assert stats["scepter"] is True and stats["scepter_time"] == 2000 and stats["shard"] is False
        bare = {"players": [{"account_id": 42, "item_0": 1}]}  # матч не разобран: purchase_log нет
        stats = OpenDota(session=FakeApiSession(bare), min_interval=0).get_match_player_stats(2, 42)
        assert stats["items"] == [1] and stats["item_times"] == [None]
        assert stats["shard"] is False and stats["scepter"] is False
    finally:
        _reset_items(saved)


def test_enrich_alert_items_copies_times_upgrades_and_tower_damage():
    client = FakeClient({1: {"items": [1], "item_times": [900], "shard": True, "shard_time": 1450, "scepter": False,
                             "scepter_time": None, "tower_damage": 6589}})
    event = _event()
    enrich_alert_items(client, event)
    row = event["rows"][0]
    assert row["item_times"] == [900] and row["shard"] is True and row["shard_time"] == 1450
    assert row["scepter"] is False and row["tower_damage"] == 6589


def test_request_parse_posts_once_per_match_and_swallows_errors():
    class Session(FakeApiSession):
        def __init__(self):
            super().__init__({})
            self.posts = []

        def post(self, url, timeout=None, **kwargs):
            self.posts.append(url)
            return FakeApiResp({})

    session = Session()
    od = OpenDota(session=session, min_interval=0)
    assert od.request_parse(77) is True
    assert od.request_parse(77) is False  # уже просили — реплей не дёргаем повторно
    assert od.request_parse(78) is True
    assert [u.rsplit("/", 2)[-2:] for u in session.posts] == [["request", "77"], ["request", "78"]]

    class Broken(Session):
        def post(self, url, timeout=None, **kwargs):
            raise RuntimeError("сеть")

    assert OpenDota(session=Broken(), min_interval=0).request_parse(1) is False  # best-effort: не бросает


def test_enrich_requests_parse_only_when_build_has_no_times():
    class Client(FakeClient):
        requested: list = []

        def request_parse(self, match_id):
            self.requested.append(match_id)
            return True

    unparsed = Client({1: {"items": [1, 2], "item_times": [None, None]}})
    unparsed.requested = []
    enrich_alert_items(unparsed, _event())
    assert unparsed.requested == [9]  # матч без разбора: просим OpenDota разобрать, времена появятся позже

    parsed = Client({1: {"items": [1, 2], "item_times": [300, None]}})
    parsed.requested = []
    enrich_alert_items(parsed, _event())
    assert parsed.requested == []


def test_get_match_builds_maps_every_player_by_hero():
    saved = dict(items.ITEM_SLUGS)
    try:
        items.update_items({"1": "blink", "63": "power_treads"})
        match = {"players": [
            {"hero_id": 8, "account_id": 42, "item_0": 63, "item_neutral": 300, "aghanims_shard": 1,
             "purchase_log": [{"time": 300, "key": "power_treads"}]},
            {"hero_id": 11, "account_id": None, "item_0": 1, "item_1": 0},  # скрытый профиль — тоже по герою
            {"hero_id": None, "item_0": 1},  # без героя в соответствие не ставим
        ]}
        builds = OpenDota(session=FakeApiSession(match), min_interval=0).get_match_builds(5)
        assert set(builds) == {8, 11}
        assert builds[8]["items"] == [63] and builds[8]["item_times"] == [300] and builds[8]["shard"] is True
        assert builds[8]["neutral_item"] == 300
        assert builds[11]["items"] == [1] and builds[11]["item_times"] == [None]
        assert OpenDota(session=FakeApiSession({}), min_interval=0).get_match_builds(6) == {}
    finally:
        _reset_items(saved)


def test_enrich_match_builds_fills_all_players_and_requests_parse_for_unparsed():
    from mmrbot.tracker import enrich_match_builds

    class Client:
        def __init__(self, builds, down=False, boom=False):
            self.builds, self.boom, self.requested = builds, boom, []
            self.health = type("H", (), {"available": lambda s: not down})()

        def get_match_builds(self, match_id):
            if self.boom:
                raise RuntimeError("сеть")
            return self.builds

        def request_parse(self, match_id):
            self.requested.append(match_id)

    def match():
        return {"match_id": 5, "players": [{"hero_id": 8, "kills": 1}, {"hero_id": 11}, {"hero_id": 99}]}

    parsed = Client({8: {"items": [1], "item_times": [300], "shard": True}, 11: {"items": [2], "item_times": [None]}})
    m = match()
    enrich_match_builds(parsed, m)
    assert m["players"][0]["items"] == [1] and m["players"][0]["shard"] is True and m["players"][0]["kills"] == 1
    assert m["players"][1]["items"] == [2] and "items" not in m["players"][2]  # героя нет в OpenDota — как есть
    assert parsed.requested == []  # времена известны — разбор не нужен

    unparsed = Client({8: {"items": [1], "item_times": [None]}})
    enrich_match_builds(unparsed, match())
    assert unparsed.requested == [5]

    for bad in (Client({8: {"items": [1], "item_times": [1]}}, down=True), Client({}, boom=True)):
        m = match()
        enrich_match_builds(bad, m)  # лежит предохранитель или сеть — таблица остаётся без билда
        assert "items" not in m["players"][0]


def test_enrich_match_builds_dates_bear_items_by_purchase_log():
    from mmrbot.tracker import enrich_match_builds
    saved = dict(items.ITEM_SLUGS)
    try:
        items.update_items({"1": "blink", "116": "black_king_bar", "139": "butterfly"})

        class Client:
            health = None

            def get_match_builds(self, match_id):
                return {80: {"items": [], "item_times": [], "bought": {"blink": 700, "black_king_bar": 1500}}}

        match = {"match_id": 9, "players": [{"hero_id": 80, "bear_items": [1, 116, 139], "bear_neutral": 5}]}
        enrich_match_builds(Client(), match)
        druid = match["players"][0]
        assert druid["bear_item_times"] == [700, 1500, None]  # у бабочки покупки в логе нет — время неизвестно
        assert "bought" not in druid  # служебные данные в строку игрока не попадают
    finally:
        _reset_items(saved)


def test_справочник_предметов_переживает_перезапуск(tmp_path):
    items.ITEM_SLUGS.clear()
    path = tmp_path / "item_ids.json"
    items.update_items({"1": "blink", "116": "black_king_bar"})
    items.save_items(str(path))
    items.ITEM_SLUGS.clear()
    assert items.load_items(str(path)) == 2
    assert items.item_slug(116) == "black_king_bar"


def test_загрузка_справочника_без_файла_или_с_мусором(tmp_path):
    items.ITEM_SLUGS.clear()
    assert items.load_items(str(tmp_path / "нет.json")) == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{не json", encoding="utf-8")
    assert items.load_items(str(bad)) == 0
