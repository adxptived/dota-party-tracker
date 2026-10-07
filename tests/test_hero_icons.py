from mmrbot.hero_icons import ICON_URL, HeroIcons
from mmrbot.heroes import HERO_NAMES, HERO_SLUGS, hero_slug, update_heroes


class FakeResp:
    def __init__(self, status=200, content=b"PNG", content_type="image/png"):
        self.status_code = status
        self.content = content
        self.headers = {"Content-Type": content_type}


class FakeSession:
    def __init__(self, resp=None, exc=None):
        self.resp = resp or FakeResp()
        self.exc = exc
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if self.exc:
            raise self.exc
        return self.resp


def test_every_hero_has_slug():
    assert all(hero_slug(hid) for hid in HERO_NAMES)
    assert hero_slug(11) == "nevermore" and hero_slug(22) == "zuus" and hero_slug(1) == "antimage"
    assert hero_slug(None) is None and hero_slug(9999) is None


def test_update_heroes_learns_slug_of_new_hero():
    update_heroes([{"id": 999, "localized_name": "Новый", "name": "npc_dota_hero_brand_new"}])
    try:
        assert hero_slug(999) == "brand_new"
    finally:
        HERO_NAMES.pop(999, None)
        HERO_SLUGS.pop(999, None)
        update_heroes([])  # пересобрать индекс поиска без тестового героя


def test_icon_downloaded_once_and_cached_on_disk(tmp_path):
    session = FakeSession()
    icons = HeroIcons(str(tmp_path), session=session)
    assert icons.get(1) == b"PNG"
    assert icons.get(1) == b"PNG"
    assert session.urls == [ICON_URL.format(slug="antimage")]
    assert (tmp_path / "antimage.png").read_bytes() == b"PNG"

    fresh = HeroIcons(str(tmp_path), session=FakeSession(exc=RuntimeError("сети нет")))
    assert fresh.get(1) == b"PNG"  # с диска, без сети


def test_icon_network_error_gives_none_and_is_not_retried_immediately(tmp_path):
    session = FakeSession(exc=RuntimeError("timeout"))
    icons = HeroIcons(str(tmp_path), session=session)
    assert icons.get(1) is None
    assert icons.get(1) is None
    assert len(session.urls) == 1  # промах запомнили — каждая картинка не ждёт таймаут заново


def test_icon_bad_response_and_unknown_hero(tmp_path):
    icons = HeroIcons(str(tmp_path), session=FakeSession(FakeResp(status=404)))
    assert icons.get(1) is None
    html = HeroIcons(str(tmp_path), session=FakeSession(FakeResp(content=b"<html>", content_type="text/html")))
    assert html.get(2) is None
    assert icons.get(9999) is None and icons.get(None) is None


def test_get_many_skips_missing(tmp_path):
    icons = HeroIcons(None, session=FakeSession())  # без папки — только память
    assert icons.get_many([1, 2, None, 9999]) == {1: b"PNG", 2: b"PNG"}
