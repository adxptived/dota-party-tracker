from mmrbot.config import load_config


def _cfg(monkeypatch, **env):
    monkeypatch.setenv("BOT_TOKEN", "1:test")
    monkeypatch.delenv("COMMAND_REFRESH_WAIT", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return load_config()


def test_command_refresh_wait_default(monkeypatch):
    assert _cfg(monkeypatch).command_refresh_wait == 4.0


def test_command_refresh_wait_from_env(monkeypatch):
    assert _cfg(monkeypatch, COMMAND_REFRESH_WAIT="2.5").command_refresh_wait == 2.5
    assert _cfg(monkeypatch, COMMAND_REFRESH_WAIT="0").command_refresh_wait == 0.0  # 0 — не ждать, отвечать из БД


def test_command_refresh_wait_garbage_falls_back_to_default(monkeypatch):
    assert _cfg(monkeypatch, COMMAND_REFRESH_WAIT="быстро").command_refresh_wait == 4.0
    assert _cfg(monkeypatch, COMMAND_REFRESH_WAIT="-3").command_refresh_wait == 0.0


# --- A6: OPENDOTA_PROXY ------------------------------------------------------------------------

def test_opendota_proxy_default_is_none(monkeypatch):
    monkeypatch.delenv("OPENDOTA_PROXY", raising=False)
    assert _cfg(monkeypatch).opendota_proxy is None


def test_opendota_proxy_from_env_is_trimmed(monkeypatch):
    assert _cfg(monkeypatch, OPENDOTA_PROXY="  socks5h://127.0.0.1:1080 ").opendota_proxy == "socks5h://127.0.0.1:1080"
    assert _cfg(monkeypatch, OPENDOTA_PROXY="   ").opendota_proxy is None


def test_opendota_proxy_with_unknown_scheme_fails_without_echoing_the_value(monkeypatch):
    import pytest
    with pytest.raises(RuntimeError) as err:
        _cfg(monkeypatch, OPENDOTA_PROXY="ftp://user:secret@host:1")
    assert "secret" not in str(err.value) and "OPENDOTA_PROXY" in str(err.value)


def test_inline_cache_chat(monkeypatch):
    monkeypatch.delenv("INLINE_CACHE_CHAT", raising=False)
    assert _cfg(monkeypatch).inline_cache_chat is None
    assert _cfg(monkeypatch, INLINE_CACHE_CHAT="-100123").inline_cache_chat == -100123
