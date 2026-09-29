import pytest

from mmrbot.ids import parse_account_id

STEAMID64_BASE = 76561197960265728


def test_dotabuff_url():
    assert parse_account_id("https://www.dotabuff.com/players/123456789") == 123456789


def test_opendota_url():
    assert parse_account_id("https://www.opendota.com/players/123456789") == 123456789


def test_stratz_url():
    assert parse_account_id("https://stratz.com/players/123456789") == 123456789


def test_url_with_trailing_path_and_query():
    assert parse_account_id("https://www.dotabuff.com/players/123456789/matches?enhance=overview") == 123456789


def test_raw_account_id():
    assert parse_account_id("123456789") == 123456789


def test_raw_account_id_with_whitespace():
    assert parse_account_id("  123456789  ") == 123456789


def test_steamid64_converted_to_account_id():
    steamid64 = STEAMID64_BASE + 555
    assert parse_account_id(str(steamid64)) == 555


def test_steam_profile_url_converted():
    steamid64 = STEAMID64_BASE + 987654
    assert parse_account_id(f"https://steamcommunity.com/profiles/{steamid64}") == 987654


def test_vanity_steam_url_raises_helpful_error():
    with pytest.raises(ValueError) as exc:
        parse_account_id("https://steamcommunity.com/id/some_custom_name")
    assert "id/" in str(exc.value).lower() or "кастом" in str(exc.value).lower()


def test_garbage_raises():
    with pytest.raises(ValueError):
        parse_account_id("не ссылка и не число")


def test_empty_raises():
    with pytest.raises(ValueError):
        parse_account_id("   ")
