"""Inline-режим: `@бот Вася` → карточка игрока; видны только игроки чатов, где пользователь привязан через /me."""
import asyncio

import pytest
from aiogram.types import InlineQueryResultArticle, InlineQueryResultCachedPhoto

from mmrbot import inline
from mmrbot.storage import Storage

T0 = 1_780_000_000


@pytest.fixture(autouse=True)
def _fresh_file_ids():
    inline._file_ids.clear()
    yield
    inline._file_ids.clear()


@pytest.fixture
def store(tmp_path):
    storage = Storage(str(tmp_path / "i.db"))
    for chat in (1, 2, 3):
        storage.get_or_create_chat(chat)
    vasya = storage.add_player(1, 10, "Вася", None, T0, T0)
    petya = storage.add_player(1, 20, "Петя", None, T0, T0)
    storage.add_player(2, 10, "Вася-второй", None, T0, T0)   # тот же аккаунт Steam в другом чате
    storage.add_player(3, 30, "Чужой", None, T0, T0)          # чат, где пользователь не привязан
    storage.link_user(1, vasya.id, 7)
    storage.link_user(2, storage.list_players(2)[0].id, 7)
    return storage


def test_user_chats_only_linked(store):
    assert store.user_chats(7) == [1, 2]
    assert store.user_chats(999) == []


def test_visible_players_dedupes_account_and_hides_foreign_chats(store):
    found = inline.visible_players(store, 7, "")
    assert sorted(p.account_id for _, p in found) == [10, 20]       # аккаунт 10 — один раз; «Чужой» не виден


def test_visible_players_filters_by_query_case_insensitive(store):
    assert [p.display_name for _, p in inline.visible_players(store, 7, "пет")] == ["Петя"]
    assert [p.display_name for _, p in inline.visible_players(store, 7, "@ПЕТЯ")] == ["Петя"]
    assert inline.visible_players(store, 7, "нет такого") == []


def test_unlinked_user_sees_nothing(store):
    assert inline.visible_players(store, 999, "") == []


def _run(coro):
    return asyncio.run(coro)


def test_results_are_articles_without_cache_chat(store):
    results = _run(inline.build_results(store, 7, "Петя"))
    assert len(results) == 1 and isinstance(results[0], InlineQueryResultArticle)
    assert results[0].title == "Петя"
    assert "Петя" in results[0].input_message_content.message_text
    assert results[0].input_message_content.parse_mode == "HTML"


def test_results_use_cached_photo_when_upload_available(store):
    sent = []

    async def upload(png, caption):
        sent.append((png, caption))
        return "FILE_ID"

    results = _run(inline.build_results(store, 7, "Петя", upload=upload))
    assert sent and isinstance(results[0], InlineQueryResultCachedPhoto)
    assert results[0].photo_file_id == "FILE_ID"


def test_upload_failure_falls_back_to_article(store):
    async def upload(png, caption):
        raise RuntimeError("telegram не принял")

    results = _run(inline.build_results(store, 7, "Петя", upload=upload))
    assert isinstance(results[0], InlineQueryResultArticle)


def test_results_limited(store):
    for n in range(60):
        store.add_player(1, 1000 + n, f"Игрок{n}", None, T0, T0)
    assert len(inline.visible_players(store, 7, "")) <= inline.MAX_RESULTS
