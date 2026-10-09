"""Иконки шарда и скипетра из Доты вместо подписей «Ш»/«С» в билдах."""
from mmrbot import upgrade_icons
from mmrbot.upgrade_icons import upgrade_icon


def test_icons_are_bundled_and_scaled_with_rounded_corners():
    for key in ("shard", "scepter"):
        icon = upgrade_icon(key, 40)
        assert icon.size == (40, 40) and icon.mode == "RGBA"
        assert icon.getpixel((0, 0))[3] < 40 and icon.getpixel((20, 20))[3] == 255


def test_unknown_key_or_missing_file_gives_none(monkeypatch):
    assert upgrade_icon("nope", 40) is None
    monkeypatch.setattr(upgrade_icons, "ASSETS", "/nonexistent")
    upgrade_icon.cache_clear()
    assert upgrade_icon("shard", 40) is None
    upgrade_icon.cache_clear()


def test_match_build_draws_icons_not_pills_and_falls_back(monkeypatch):
    from PIL import Image
    from mmrbot import cards, match_image
    img = Image.new("RGB", (1000, 100), cards.BG)
    draw = __import__("PIL.ImageDraw", fromlist=["x"]).Draw(img)
    before = img.copy().tobytes()
    match_image._draw_build(img, draw, 0, {"shard": True, "scepter": True}, {})
    assert img.tobytes() != before
    monkeypatch.setattr(match_image, "paste_upgrade", lambda *a, **k: None)
    pill_img = Image.new("RGB", (1000, 100), cards.BG)
    match_image._draw_build(pill_img, __import__("PIL.ImageDraw", fromlist=["x"]).Draw(pill_img), 0,
                            {"shard": True, "scepter": True}, {})
    assert pill_img.tobytes() != before and pill_img.tobytes() != img.tobytes()
