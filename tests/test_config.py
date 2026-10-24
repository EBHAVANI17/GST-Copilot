import pytest

from gst_copilot.config import Settings


def test_settings_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "ci")
    monkeypatch.setenv("REDIS_URL", "redis://example:6379/1")
    s = Settings()
    assert s.app_env == "ci"
    assert s.redis_url == "redis://example:6379/1"


def test_invalid_environment_name_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod-typo")
    with pytest.raises(ValueError):
        Settings()
