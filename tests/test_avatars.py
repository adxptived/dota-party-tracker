import requests

from mmrbot.avatars import Avatars, allowed_url
from mmrbot.health import ProviderHealth

URL = "https://avatars.steamstatic.com/abc_full.jpg"
URL2 = "https://avatars.akamai.steamstatic.com/def_full.jpg"


class Resp:
    def __init__(self, status=200, content=b"JPG", content_type="image/jpeg"):
        self.status_code, self.content, self.headers = status, content, {"Content-Type": content_type}


class Session:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.urls = resp or Resp(), exc, []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if self.exc:
            raise self.exc
        return self.resp


def test_only_steam_https_hosts_are_allowed():
    assert allowed_url(URL) and allowed_url(URL2)
    assert not allowed_url("http://avatars.steamstatic.com/a.jpg")          # не https
    assert not allowed_url("https://evil.example.com/a.jpg")
    assert not allowed_url("https://steamstatic.com.evil.com/a.jpg")        # суффикс-обманка
    assert not allowed_url("https://127.0.0.1/a.jpg") and not allowed_url(None) and not allowed_url("")


def test_downloaded_once_cached_in_memory_and_on_disk(tmp_path):
    session = Session()
    avatars = Avatars(str(tmp_path), session=session)
    assert avatars.get(URL) == b"JPG" and avatars.get(URL) == b"JPG"
    assert session.urls == [URL]
    fresh = Avatars(str(tmp_path), session=Session(exc=RuntimeError("сети нет")))
    assert fresh.get(URL) == b"JPG"  # с диска


def test_foreign_host_never_requested():
    session = Session()
    assert Avatars(None, session=session).get("https://evil.example.com/x.jpg") is None
    assert session.urls == []


def test_bad_responses_give_none_and_miss_is_remembered():
    session = Session(Resp(content_type="text/html"))
    avatars = Avatars(None, session=session)
    assert avatars.get(URL) is None and avatars.get(URL) is None
    assert len(session.urls) == 1
    assert Avatars(None, session=Session(Resp(status=404))).get(URL) is None
    assert Avatars(None, session=Session(Resp(content=b"x" * 600_000))).get(URL) is None  # слишком большой


def test_cdn_down_skips_requests_until_pause_ends():
    health = ProviderHealth("Steam CDN", clock=lambda: 1000.0, wall=lambda: 1.0)
    session = Session(exc=requests.exceptions.ConnectTimeout("t"))
    avatars = Avatars(None, session=session, health=health)
    assert avatars.get(URL) is None
    assert avatars.get(URL2) is None
    assert len(session.urls) == 1 and health.status()["state"] == "down"


def test_get_many_skips_missing_and_dedupes():
    avatars = Avatars(None, session=Session())
    assert avatars.get_many([URL, URL, None, "https://evil.example.com/x"]) == {URL: b"JPG"}
    assert avatars.get_many([]) == {}
