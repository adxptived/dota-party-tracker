import io
from types import SimpleNamespace

from PIL import Image

from mmrbot import card_data as cd
from mmrbot.cards import WIDTH
from mmrbot.compare_image import render_compare_image
from mmrbot.together_image import MAX_PLAYERS, render_together_image
from mmrbot.tracker import build_chat_comparison


def _open(png: bytes) -> Image.Image:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(png))


def _row(name="Вася", **extra):
    row = {"name": name, "avatar": None, "rank_tier": 55, "rank_text": "Legend 5", "power": 0.8, "index_text": "80",
           "cells": [{"value": "70", "rank": 1}, {"value": "60%", "rank": 1}, {"value": "3.1", "rank": 2}, {"value": "540", "rank": 1}]}
    row.update(extra)
    return row


# --- сравнение -----------------------------------------------------------------------------------

def test_compare_height_grows_with_rows_and_empty_renders():
    one = _open(render_compare_image([_row()]))
    four = _open(render_compare_image([_row(f"P{i}") for i in range(4)]))
    assert one.width == four.width == WIDTH and four.height > one.height + 3 * 100
    assert _open(render_compare_image([])).width == WIDTH


def test_compare_strange_data_does_not_break():
    rows = [_row("😀" * 3 + "x" * 90, power=None, index_text=None, cells=[{"value": None, "rank": None}] * 4),
            _row(None, cells=[{"value": "9" * 40, "rank": 99}]), _row("Без ячеек", cells=[])]
    assert _open(render_compare_image(rows, {"u": b"junk"}, "заметка")).width == WIDTH


def _summary(name, perf, winrate, kda, gpm, games=20):
    return SimpleNamespace(display_name=name, avatar=None, rank_tier=55, rank="Legend 5", avg_perf=perf, winrate=winrate,
                           kda_ratio=kda, avg_gpm_window=gpm, games_total=games, enriched_games=games, detail_games=games)


def test_compare_rows_follow_power_order_and_ranks():
    summaries = [_summary("Петя", 0.4, 0.45, 2.0, 400), _summary("Вася", 0.7, 0.62, 3.1, 540)]
    comparison = build_chat_comparison(summaries)
    rows = cd.compare_rows(comparison, summaries)
    assert [r["name"] for r in rows] == ["Вася", "Петя"] and rows[0]["index_text"] == "100"
    assert [c["value"] for c in rows[0]["cells"]] == ["70", "62%", "3.1", "540"]
    assert [c["rank"] for c in rows[0]["cells"]] == [1, 1, 1, 1] and rows[1]["cells"][0]["rank"] == 2
    assert "Вася" in cd.compare_caption(comparison, summaries) and "участников: 2" in cd.compare_caption(comparison, summaries)


def test_compare_rows_without_data_show_dashes():
    summaries = [_summary("Вася", None, 0.0, 0.0, None, games=0)]
    (row,) = cd.compare_rows(build_chat_comparison(summaries), summaries)
    assert [c["value"] for c in row["cells"]] == [None, None, None, None]
    assert "Сравнение" in cd.compare_caption(build_chat_comparison(summaries), summaries)


# --- совместные игры -----------------------------------------------------------------------------

def _players(n):
    return [{"name": f"P{i}", "avatar": None} for i in range(n)]


def test_together_matrix_grows_with_players_and_caps_at_limit():
    pairs3 = [{"a": 0, "b": 1, "games": 5, "wins": 3}, {"a": 1, "b": 2, "games": 2, "wins": 0}]
    three = _open(render_together_image({"games": 7, "wins": 3, "losses": 4}, None, _players(3), pairs3))
    two = _open(render_together_image({"games": 5, "wins": 3, "losses": 2}, None, _players(2), pairs3[:1]))
    assert three.width == two.width == WIDTH and three.height > two.height
    many = [{"a": i, "b": j, "games": 3, "wins": 1} for i in range(15) for j in range(i + 1, 15)]
    capped = _open(render_together_image({"games": 9, "wins": 3, "losses": 6}, None, _players(15), many))
    among_eight = [p for p in many if p["a"] < MAX_PLAYERS and p["b"] < MAX_PLAYERS]
    eight = _open(render_together_image({"games": 9, "wins": 3, "losses": 6}, None, _players(MAX_PLAYERS), among_eight))
    assert abs(capped.height - eight.height) < 80  # 15 игроков → показаны 8 + строка-пояснение


def test_together_empty_and_strange_data():
    assert _open(render_together_image({"games": 0}, None, _players(2), [])).width == WIDTH
    duo = {"names": ("😀" * 30, "x" * 90), "games": 4, "wins": 4}
    png = render_together_image({"games": 4, "wins": 4, "losses": 0}, duo, [{"name": None, "avatar": "u"}, {"name": "я" * 80, "avatar": None}],
                                [{"a": 0, "b": 1, "games": 4, "wins": 4}], {"u": b"junk"}, "заметка")
    assert _open(png).width == WIDTH
    assert _open(render_together_image({"games": 3, "wins": 1, "losses": 2}, None, _players(1), [])).width == WIDTH


def test_together_card_data_and_caption():
    result = {"summary": {"games": 33, "wins": 19, "losses": 14}, "duo": {"pair": ("Вася", "Петя"), "games": 24, "wins": 15, "winrate": 0.625},
              "players": _players(2), "pairs": [{"a": 0, "b": 1, "games": 24, "wins": 15}]}
    summary, duo, players, pairs = cd.together_card(result)
    assert summary["games"] == 33 and duo == {"names": ("Вася", "Петя"), "games": 24, "wins": 15} and len(players) == 2 and len(pairs) == 1
    caption = cd.together_caption(result)
    assert "33 игры" in caption and "19–14" in caption and "Вася + Петя" in caption
    assert "пока нет" in cd.together_caption({"summary": {"games": 0}})
