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
    assert "Разные стороны" in text and "Вася" in text and "+25" in text and "−25" in text
    assert "Матч завершён" not in text and "5420" not in text and "4975" not in text  # это уже на картинке


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


def test_build_line_adds_height_only_for_rows_with_build():
    plain = _open(render_alert_image(_event(), "UTC"))
    built = _open(render_alert_image(_event([_row("A", items=[1, 2, 3])]), "UTC"))
    ranked = _open(render_alert_image(_event([_row("A", rank_tier=75)]), "UTC"))
    assert built.height > plain.height + 30
    assert ranked.height == plain.height  # ранг стоит под ±MMR в верхней части строки, места не добавляет


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


def test_upgrades_alone_make_a_build_line():
    plain = _open(render_alert_image(_event(), "UTC"))
    assert _open(render_alert_image(_event([_row("A", tower_damage=5000)]), "UTC")).height == plain.height
    assert _open(render_alert_image(_event([_row("A", shard=True)]), "UTC")).height > plain.height
    junk = _row("A", items=[1], item_times=["x", None], shard=True, shard_time="bad", tower_damage="много")
    assert _open(render_alert_image(_event([junk]), "UTC")).width == WIDTH  # странные данные не роняют рендер


def test_strip_stats_are_labelled_cells(drawn):
    row = _row("Вася", items=[1, 2], net_worth=18200, last_hits=312, denies=14, tower_damage=4200, rank_tier=55)
    render_alert_image(_event([row]), "UTC")
    texts = [t[0] for t in drawn]
    for label, value in (("IMP", "+21"), ("GPM", "640"), ("НЕТВОРС", "18.2k"), ("КРИПЫ", "312/14"),
                         ("УРОН", "31.2k"), ("ЗДАНИЯ", "4.2k")):
        assert texts[texts.index(label) + 1] == value
    assert "K / D / A" in texts
    assert not any(t.startswith("NW ") or "по зданиям" in t or "урона" in t or "GPM" in t and t != "GPM" for t in texts)


def test_imp_is_a_cell_colored_by_sign(drawn):
    from mmrbot.cards import LOSS, WIN
    render_alert_image(_event([_row("A"), _row("B", imp=-14)]), "UTC")
    assert ("+21", WIN, True) in drawn and ("−14", LOSS, True) in drawn


def test_banner_has_no_numbers_and_summary_holds_score_time_and_id(drawn):
    event = _event([_row("Вася", is_radiant=True)], score={"radiant": 41, "dire": 27, "gold": (98400, 86000)})
    render_alert_image(event, "UTC")
    texts = [t[0] for t in drawn]
    banner = texts[:texts.index("Legend 5")]  # исход, подпись, «ЛОББИ»; ранг лобби — словами
    assert banner and not any(ch.isdigit() for t in banner for ch in t)  # в шапке нет цифр
    for label, value in (("СЧЁТ", "41 : 27"), ("ЗОЛОТО", "+12.4k"), ("ДЛИТЕЛЬНОСТЬ", "38:00")):
        assert texts[texts.index(label) + 1] == value
    assert "матч 7812345678" in texts


def test_score_adds_summary_and_support_cells_keep_layout():
    plain = _open(render_alert_image(_event(start_time=None, duration=None), "UTC"))
    scored = _open(render_alert_image(_event([_row("Вася", is_radiant=True)], start_time=None, duration=None,
                                             score={"radiant": 41, "dire": 27, "gold": (98400, 86000)}), "UTC"))
    assert scored.height > plain.height                                         # итог матча — отдельной плашкой
    support = _open(render_alert_image(_event([_row("Петя", position=5, wards=18, stacks=4)]), "UTC"))
    core = _open(render_alert_image(_event([_row("Вася", wards=18, stacks=4)]), "UTC"))
    assert support.height == core.height == _open(render_alert_image(_event(), "UTC")).height


def test_long_name_shrinks_instead_of_running_under_mmr(drawn):
    render_alert_image(_event([_row("Оооочень длинный ник игрока номер один")]), "UTC")
    assert any(t[0] == "Оооочень длинный ник игрока номер один" for t in drawn)  # целиком, без многоточия


def test_support_strip_puts_vision_first_and_keeps_four_cells():
    from mmrbot.alert_image import _strip_cells
    row = _row("Петя", position=5, wards=18, stacks=0, hero_healing=5200, net_worth=9800, last_hits=40, tower_damage=300)
    assert [label for label, _ in _strip_cells(row)] == ["Варды", "Стаки", "Лечение", "Урон"]
    assert dict(_strip_cells(row))["Стаки"] == "0"                             # ноль стаков — тоже значение
    core = _row("Вася", net_worth=21400, last_hits=312, denies=14, tower_damage=4200, wards=3)
    assert [label for label, _ in _strip_cells(core)] == ["Нетворс", "Крипы", "Урон", "Здания"]


def test_talent_tree_is_graphic_only(drawn):
    plain = render_alert_image(_event([_row("A", items=[1, 2])]), "UTC")
    tree = [{"level": 10, "left": "+30 Feast of Souls Attack Speed", "right": "+30 Shadowraze Stack Damage",
             "pick": "left"},
            {"level": 25, "left": "Shadowraze Applies Attack Damage", "right": "+30% Cast Speed", "pick": None}]
    with_tree = render_alert_image(_event([_row("A", items=[1, 2], talents=tree)]), "UTC")
    assert _open(with_tree).size == _open(plain).size and with_tree != plain  # дерево — в линии билда, места не просит
    texts = [t[0] for t in drawn]
    assert not any("Shadowraze" in t or "Feast" in t or t == "ТАЛАНТЫ" for t in texts)  # без подписей
    alone = _open(render_alert_image(_event([_row("A", talents=tree)]), "UTC"))
    assert alone.height > _open(render_alert_image(_event(), "UTC")).height  # без билда дерево занимает его линию
    junk = _open(render_alert_image(_event([_row("A", talents=[["x"], None, {"level": 10}])]), "UTC"))
    assert junk.height == _open(render_alert_image(_event(), "UTC")).height  # без выбранных талантов дерева нет


def test_hero_level_is_drawn_on_alert_icon():
    from PIL import Image
    import io
    from mmrbot.alert_image import render_alert_image
    row = {"name": "Вася", "hero_id": 1, "won": True, "kills": 1, "deaths": 2, "assists": 3, "delta": 25}
    event = {"match_id": 1, "rows": [row]}
    plain = Image.open(io.BytesIO(render_alert_image(event))).convert("RGB")
    event["rows"] = [dict(row, level=22)]
    leveled = Image.open(io.BytesIO(render_alert_image(event))).convert("RGB")
    assert plain.tobytes() != leveled.tobytes()


def test_dota_plus_tier_is_drawn_on_alert_icon():
    from PIL import Image
    import io
    from mmrbot.alert_image import render_alert_image
    row = {"name": "Вася", "hero_id": 1, "won": True, "kills": 1, "deaths": 2, "assists": 3, "delta": 25}
    event = {"match_id": 1, "rows": [row]}
    plain = Image.open(io.BytesIO(render_alert_image(event))).convert("RGB")
    event["rows"] = [dict(row, plus_xp=72050)]
    plus = Image.open(io.BytesIO(render_alert_image(event))).convert("RGB")
    assert plain.tobytes() != plus.tobytes()


def test_lone_druid_row_shows_bear_items_on_its_own_line():
    hero = _row("Cotara", hero_id=80, items=[1, 2, 3], item_times=[300, 900, 1500], neutral_item=4)
    bear = dict(hero, bear_items=[5, 6, 7, 8], bear_item_times=[400, 1000, None, 2000], bear_neutral=9)
    plain = _open(render_alert_image(_event([hero]), "UTC"))
    with_bear = _open(render_alert_image(_event([bear]), "UTC"))
    assert with_bear.height > plain.height + 40  # вторая линия билда — предметы медведя


def test_bear_alone_is_a_build_too():
    row = _row("Cotara", hero_id=80, bear_items=[5, 6])
    assert _open(render_alert_image(_event([row]), "UTC")).height > _open(render_alert_image(_event([_row("X")]), "UTC")).height
