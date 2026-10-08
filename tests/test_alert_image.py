import io

from PIL import Image

from mmrbot.alert_image import alert_caption, render_alert_image
from mmrbot.cards import WIDTH


def _row(name, won=True, **extra):
    row = {"name": name, "hero_id": 12, "kills": 13, "deaths": 3, "assists": 10, "won": won, "step": 25,
           "current_mmr": 5420, "streak_type": "W", "streak_len": 4, "gpm": 640, "hero_damage": 31250,
           "position": 1, "imp": 21, "leaver_status": 0, "account_id": 1, "avatar": None}
    row.update(extra)
    return row


def _event(rows=None, **extra):
    event = {"kind": "match", "chat_id": 1, "match_id": 7812345678, "start_time": 1_700_000_000, "duration": 2280,
             "rows": rows or [_row("Вася")], "shared": None, "average_rank": 55}
    event.update(extra)
    return event


def _open(png: bytes) -> Image.Image:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png))


def test_renders_png_of_telegram_width_and_grows_with_players():
    one = _open(render_alert_image(_event(), "Europe/Moscow"))
    five = _open(render_alert_image(_event([_row(f"P{i}") for i in range(5)]), "Europe/Moscow"))
    assert one.width == five.width == WIDTH
    assert five.height > one.height + 3 * 90


def test_mixed_and_lost_results_render_differently():
    won = render_alert_image(_event([_row("A"), _row("B")]), "UTC")
    lost = render_alert_image(_event([_row("A", False), _row("B", False)]), "UTC")
    mixed = render_alert_image(_event([_row("A"), _row("B", False)]), "UTC")
    assert len({won, lost, mixed}) == 3


def test_missing_and_strange_data_do_not_break():
    rows = [
        _row("😀" * 3 + "x" * 80 + "\x00", current_mmr=None, streak_len=0, gpm=None, hero_damage=None,
             position=None, imp=None, hero_id=None),
        _row("Лив", False, leaver_status=3, streak_type="L", streak_len=5),
        _row("Без аватара", avatar=None, account_id=None),
        {"name": "Минимум", "hero_id": 1, "kills": 0, "deaths": 0, "assists": 0, "won": True, "step": 25},
    ]
    event = _event(rows, duration=None, average_rank=None, shared={"games": 5, "wins": 3, "losses": 2})
    assert _open(render_alert_image(event, "Nope/Zone", icons={1: b"junk"}, avatars={})).width == WIDTH


def test_shared_footer_adds_height():
    plain = _open(render_alert_image(_event(), "UTC"))
    shared = _open(render_alert_image(_event(shared={"games": 5, "wins": 3, "losses": 2}), "UTC"))
    assert shared.height > plain.height


def test_caption_is_short_with_result_and_player_deltas():
    text = alert_caption(_event([_row("Вася"), _row("Петя", False, current_mmr=4975)]))
    assert text.count("\n") <= 2 and len(text) <= 1024
    assert "Матч завершён" in text and "Разные стороны" in text
    assert "Вася" in text and "+25" in text and "−25" in text and "5420" in text


def test_caption_escapes_names_and_fits_many_players():
    event = _event([_row("<b>Hack&", current_mmr=100)] + [_row(f"Игрок{i}" * 3) for i in range(8)])
    text = alert_caption(event)
    assert "<b>Hack" not in text and "&lt;b&gt;Hack&amp;" in text
    assert len(text) <= 1024


def test_caption_for_loss_and_win():
    assert "Поражение" in alert_caption(_event([_row("A", False)]))
    assert "Победа" in alert_caption(_event([_row("A")]))


def _png(color=(200, 50, 50)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (88, 64), color).save(buf, "PNG")
    return buf.getvalue()


def test_build_strip_adds_height_only_for_rows_with_build_or_rank():
    plain = _open(render_alert_image(_event(), "UTC"))
    built = _open(render_alert_image(_event([_row("A", items=[1, 2, 3])]), "UTC"))
    ranked = _open(render_alert_image(_event([_row("A", rank_tier=75)]), "UTC"))
    assert built.height > plain.height + 30 and ranked.height > plain.height + 30


def test_build_icons_and_neutral_are_drawn_and_junk_does_not_break():
    row = _row("A", items=[1, 2, 3, 4, 5, 6], neutral_item=9, net_worth=21400, last_hits=312, denies=14,
               rank_tier=75)
    event = _event([row])
    placeholders = render_alert_image(event, "UTC")
    with_icons = render_alert_image(event, "UTC", item_icons={1: _png(), 9: _png((50, 200, 50))})
    junk = _open(render_alert_image(event, "UTC", item_icons={1: b"junk", 2: b""}))
    assert with_icons != placeholders and junk.width == WIDTH


def test_row_without_data_for_build_is_unchanged_by_item_icons():
    event = _event()
    assert render_alert_image(event, "UTC") == render_alert_image(event, "UTC", item_icons={1: _png()})


def test_clock_formats_purchase_time():
    from mmrbot.alert_image import clock
    assert clock(0) == "0:00" and clock(-30) == "0:00" and clock(65) == "1:05" and clock(1450) == "24:10"
    assert clock(4510) == "75:10" and clock(None) == ""


def test_purchase_times_shard_scepter_and_tower_damage_are_drawn():
    base = _row("A", items=[1, 2, 3], rank_tier=75)
    timed = dict(base, item_times=[300, 1100, None])
    full = dict(timed, shard=True, shard_time=1450, scepter=True, scepter_time=2000, tower_damage=6589,
                net_worth=21400, last_hits=300, denies=5)
    plain_png = render_alert_image(_event([base]), "UTC")
    timed_png = render_alert_image(_event([timed]), "UTC")
    full_png = render_alert_image(_event([full]), "UTC")
    assert len({plain_png, timed_png, full_png}) == 3
    assert _open(timed_png).height > _open(plain_png).height  # подписи времени под иконками


def test_tower_damage_alone_or_upgrades_alone_make_a_strip():
    plain = _open(render_alert_image(_event(), "UTC"))
    assert _open(render_alert_image(_event([_row("A", tower_damage=5000)]), "UTC")).height > plain.height
    assert _open(render_alert_image(_event([_row("A", shard=True)]), "UTC")).height > plain.height
    junk = _row("A", items=[1], item_times=["x", None], shard=True, shard_time="bad", tower_damage="много")
    assert _open(render_alert_image(_event([junk]), "UTC")).width == WIDTH  # странные данные не роняют рендер
