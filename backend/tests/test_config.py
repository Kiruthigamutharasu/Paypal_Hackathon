import pytest

from app.config import ConfigError, Settings, assert_sandbox


def make(**kw) -> Settings:
    base = {"PAYPAL_ENVIRONMENT": "sandbox", "PAYPAL_BASE_URL": "https://api-m.sandbox.paypal.com"}
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_sandbox_config_is_accepted():
    assert_sandbox(make())


@pytest.mark.parametrize(
    "overrides",
    [
        {"PAYPAL_ENVIRONMENT": "live"},
        {"PAYPAL_ENVIRONMENT": "production"},
        {"PAYPAL_BASE_URL": "https://api-m.paypal.com"},
        {"PAYPAL_BASE_URL": "http://api-m.sandbox.paypal.com"},
        {"PAYPAL_BASE_URL": "https://api-m.sandbox.paypal.com.evil.example"},
    ],
)
def test_non_sandbox_config_refuses_to_start(overrides):  # AC1.4
    with pytest.raises(ConfigError):
        assert_sandbox(make(**overrides))


def test_create_app_refuses_live_config(monkeypatch):  # AC1.4 end to end
    from app import config, main

    monkeypatch.setenv("PAYPAL_ENVIRONMENT", "live")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(ConfigError):
            main.create_app()
    finally:
        monkeypatch.setenv("PAYPAL_ENVIRONMENT", "sandbox")
        config.get_settings.cache_clear()


@pytest.mark.parametrize(
    "url,expected_prefix",
    [
        ("postgres://u:p@h/db", "postgresql+psycopg://"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://"),
        ("", "sqlite:///"),
    ],
)
def test_database_url_normalisation(url, expected_prefix):
    assert make(DATABASE_URL=url).database_url.startswith(expected_prefix)


def test_blank_numeric_env_values_use_defaults():
    s = make(AI_CONFIDENCE_THRESHOLD="", SIGNATURE_THRESHOLD_USD="", AUTO_SUBMIT_EVIDENCE="")
    assert s.AI_CONFIDENCE_THRESHOLD == 0.7
    assert s.SIGNATURE_THRESHOLD_USD == 750.0
    assert s.AUTO_SUBMIT_EVIDENCE is False
