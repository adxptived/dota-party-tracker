import importlib

from mmrbot.service import TELEGRAM_LIMIT, split_message


def test_split_short_message_single_chunk():
    assert split_message("привет") == ["привет"]


def test_split_long_message_into_multiple_chunks():
    block = "X" * 1000
    text = "\n\n".join([block] * 10)  # ~10k символов
    chunks = split_message(text)
    assert len(chunks) > 1
    assert all(len(c) <= TELEGRAM_LIMIT for c in chunks)


def test_split_hard_splits_oversized_single_block():
    # Один блок без разделителей длиннее лимита должен быть порезан, а не уйти целиком.
    text = "X" * 5000
    chunks = split_message(text, limit=4096)
    assert len(chunks) >= 2
    assert all(len(c) <= 4096 for c in chunks)
    assert "".join(chunks) == text


def test_split_preserves_all_blocks():
    blocks = [f"block-{i}" * 200 for i in range(20)]
    text = "\n\n".join(blocks)
    chunks = split_message(text)
    rejoined = "\n\n".join(chunks)
    for b in blocks:
        assert b in rejoined


def test_glue_modules_import_without_token():
    # Импорт склейки не должен требовать BOT_TOKEN (load_config вызывается только в main()).
    for name in ("mmrbot.bot", "mmrbot.scheduler", "mmrbot.service", "mmrbot.__main__"):
        importlib.import_module(name)
