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
