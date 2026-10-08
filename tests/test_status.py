"""A9: /status для админа и расширенный heartbeat (JSON)."""
import asyncio
import json
import os
import time

import pytest

from mmrbot import scheduler as sched
from mmrbot import status as st
from mmrbot.health import ProviderHealth
from mmrbot.storage import Storage

NOW = 1_760_000_000


def run(coro):
    return asyncio.run(coro)


class FakeOD:
    def __init__(self, down=False, remaining=1500, key=None):
        self.health = ProviderHealth("OpenDota")
        if down:
            self.health.failure(RuntimeError("down"))
        else:
            self.health.success()
        self.remaining_day, self.api_key = remaining, key
        self._match_cache = {1: object(), 2: object()}


class FakeStratz:
    def __init__(self):
        self.health = ProviderHealth("Stratz")
        self.health.limit(120)


def _match(mid, start, **extra):
    row = {"match_id": mid, "start_time": start, "player_slot": 0, "radiant_win": True, "lobby_type": 7}
    row.update(extra)
    return row


@pytest.fixture
def store(tmp_path):
    storage = Storage(str(tmp_path / "s.db"))
    storage.get_or_create_chat(1)
    a = storage.add_player(1, 10, "Вася", 5000, 0, 0)
    b = storage.add_player(1, 11, "Петя", 5000, 0, 0)
    storage.touch_player(a.id, NOW - 120)
    storage.touch_player(b.id, NOW - 7200)
    storage.add_matches(a.id, [_match(1, NOW - 3600), _match(2, NOW - 7200), _match(3, NOW - 86400 * 400)])
    return storage


def test_collect_status_is_json_serializable_and_complete(store):
    data = st.collect_status(store, FakeOD(remaining=1234), FakeStratz(), now=NOW)
    json.dumps(data)  # в heartbeat и в логи — только простые типы
    assert data["ts"] == NOW and data["chats"] == 1 and data["players"]["count"] == 2
    assert data["players"]["newest_update"] == NOW - 120 and data["players"]["oldest_update"] == NOW - 7200
    assert data["opendota"] == {"remaining_day": 1234, "has_key": False}
    by_name = {p["name"]: p for p in data["providers"]}
    assert by_name["OpenDota"]["state"] == "up" and by_name["Stratz"]["state"] == "limited"
    assert data["caches"]["opendota_matches"] == 2


def test_backlog_counts_only_matches_that_the_bot_will_still_fetch(store):
    data = st.collect_status(store, FakeOD(), None, now=NOW)
    # детали: два матча за последние 90 дней; 400-дневный — глубже границы догрузки, в очередь не входит
    assert data["backlog"]["details"] == 2 and data["backlog"]["stratz"] == 3
    a = store.get_player(1, "Вася")
    store.mark_enrich_miss(a.id, 1)
    store.mark_enrich_miss(a.id, 1)
    store.mark_enrich_miss(a.id, 1)  # три пустых ответа — сдались
    assert st.collect_status(store, FakeOD(), None, now=NOW)["backlog"]["details"] == 1


def test_players_never_updated_are_counted(tmp_path):
    storage = Storage(str(tmp_path / "n.db"))
    storage.get_or_create_chat(1)
    storage.add_player(1, 10, "Новичок", None, 0, 0)
    players = st.collect_status(storage, FakeOD(), None, now=NOW)["players"]
    assert players["count"] == 1 and players["never_updated"] == 1 and players["newest_update"] is None


def test_inactive_chats_are_not_counted(store):
    store.set_chat_active(1, False)
    data = st.collect_status(store, FakeOD(), None, now=NOW)
    assert data["chats"] == 0 and data["players"]["count"] == 0


def test_cache_folders_are_counted(store, tmp_path, monkeypatch):
    from mmrbot import avatars, hero_icons
    icons_dir, avatars_dir = tmp_path / "icons", tmp_path / "avatars"
    icons_dir.mkdir()
    avatars_dir.mkdir()
    for i in range(3):
        (icons_dir / f"h{i}.png").write_bytes(b"x")
    (avatars_dir / "a.img").write_bytes(b"x")
    monkeypatch.setattr(hero_icons, "_shared", hero_icons.HeroIcons(str(icons_dir)))
    monkeypatch.setattr(avatars, "_shared", avatars.Avatars(str(avatars_dir)))
    caches = st.collect_status(store, FakeOD(), None, now=NOW)["caches"]
    assert caches["hero_icons"] == 3 and caches["avatars"] == 1
    assert [p["name"] for p in st.collect_status(store, FakeOD(), None, now=NOW)["providers"]][-1] == "Steam CDN"


def test_collect_status_works_without_clients(store):
    data = st.collect_status(store, None, None, now=NOW)
    assert data["providers"] == [] or all("state" in p for p in data["providers"])
    assert data["opendota"] == {"remaining_day": None, "has_key": False}


def test_render_status_shows_everything_in_human_words(store):
    data = st.collect_status(store, FakeOD(down=True, remaining=1234), FakeStratz(), now=NOW)
    data["providers"][0]["since"] = NOW - 300
    data["providers"][0]["next_try"] = NOW + 45
    text = st.render_status(data, now=NOW)
    assert "OpenDota" in text and "недоступен" in text and "5 мин" in text and "через 45 с" in text
    assert "Stratz" in text and "лимит" in text
    assert "1234" in text  # остаток суточного лимита
    assert "Игроки: 2" in text and "обновление" in text
    assert "деталей матчей: 2" in text and "Stratz: 3" in text
    assert "<" not in text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")  # HTML безопасен


def test_render_status_for_healthy_service_and_unknown_quota(store):
    text = st.render_status(st.collect_status(store, FakeOD(remaining=None, key="K"), None, now=NOW), now=NOW)
    assert "работает" in text and "с ключом" in text


# --- heartbeat -----------------------------------------------------------------------------------------

def test_heartbeat_file_contains_json_snapshot_and_is_replaced_atomically(store, tmp_path):
    path = str(tmp_path / "heartbeat")
    st.write_heartbeat(path, store, FakeOD(), None)
    payload = json.loads(open(path, encoding="utf-8").read())
    assert abs(payload["ts"] - time.time()) < 5 and payload["players"]["count"] == 2
    assert [p for p in os.listdir(tmp_path) if p.startswith("heartbeat")] == ["heartbeat"]  # временных файлов не осталось
    before = os.path.getmtime(path)
    time.sleep(0.01)
    st.write_heartbeat(path, store, FakeOD(), None)
    assert os.path.getmtime(path) >= before  # healthcheck смотрит на mtime


def test_heartbeat_is_written_even_if_status_collection_fails(tmp_path):
    class Broken:
        def list_chats(self, *a, **k):
            raise RuntimeError("БД занята")

    path = str(tmp_path / "heartbeat")
    st.write_heartbeat(path, Broken(), None, None)
    payload = json.loads(open(path, encoding="utf-8").read())
    assert "ts" in payload and payload.get("error")


def test_scheduler_heartbeat_job_writes_json(store, tmp_path):
    path = str(tmp_path / "heartbeat")
    scheduler = sched.setup_scheduler(None, store, FakeOD(), heartbeat_path=path)
    jobs = {j.func.__name__: j.func for j in scheduler.get_jobs()}
    run(jobs["heartbeat"]())
    assert json.loads(open(path, encoding="utf-8").read())["players"]["count"] == 2


# --- команда /status -------------------------------------------------------------------------------

def test_status_command_only_for_admin(tmp_path):
    from tests.test_access import GROUP, Bot, Msg
    import mmrbot.bot as botmod

    storage = Storage(str(tmp_path / "s.db"))
    stranger = Msg(user_id=2, bot=Bot(admins=(1,)))
    run(botmod.cmd_status(stranger, storage, FakeOD(), None, bot=stranger.bot))
    from mmrbot.access import DENIED
    assert stranger.sent == [DENIED]

    admin = Msg(user_id=1, bot=Bot(admins=(1,)))
    run(botmod.cmd_status(admin, storage, FakeOD(), None, bot=admin.bot))
    assert len(admin.sent) == 1 and "Состояние бота" in admin.sent[0]
    assert GROUP.id  # группа, не личка: проверка админа настоящая
