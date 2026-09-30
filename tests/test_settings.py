import pytest

from kelpbot import config, settings
from kelpbot.db import Database
from kelpbot.settings import SETTINGS


def make():
    return Database(":memory:", starting_balance=config.STARTING_BALANCE)


def test_defaults():
    cfg = settings.load(make(), 1)
    assert cfg.starting_balance == config.STARTING_BALANCE
    assert cfg.max_bet == config.MAX_BET and cfg.rob_enabled is True
    assert cfg.money(1234) == f"{config.CURRENCY} 1,234"
    assert cfg.log_channel_id == 0


def test_overrides_are_per_server():
    db = make()
    settings.save(db, 1, "currency_emoji", "🐚")
    settings.save(db, 1, "rob_enabled", False)
    settings.save(db, 1, "max_bet", 0)
    a, b = settings.load(db, 1), settings.load(db, 2)
    assert a.money(5) == "🐚 5" and not a.rob_enabled and a.max_bet == 0
    assert b.money(5) == f"{config.CURRENCY} 5" and b.rob_enabled


def test_reset_to_default():
    db = make()
    settings.save(db, 1, "daily_base", 999)
    settings.save(db, 1, "daily_base", None)
    assert settings.load(db, 1).daily_base == config.DAILY_BASE


def test_starting_balance_setting_applies_to_new_players_only():
    db = make()
    db.account(1, 10)  # existing player
    settings.save(db, 1, "starting_balance", 50)
    assert db.balance(1, 10) == config.STARTING_BALANCE
    assert db.balance(1, 11) == 50
    assert db.balance(2, 11) == config.STARTING_BALANCE


@pytest.mark.parametrize("key,text,expected", [
    ("rob_enabled", "OFF", False),
    ("rob_enabled", "yes", True),
    ("max_bet", "25,000", 25_000),
    ("currency_name", " Shells ", "Shells"),
])
def test_parse_valid(key, text, expected):
    assert settings.parse(SETTINGS[key], text) == expected


@pytest.mark.parametrize("key,text", [
    ("rob_enabled", "maybe"),
    ("max_bet", "lots"),
    ("min_bet", "0"),
    ("bank_interest_percent", "50"),
    ("currency_name", ""),
    ("currency_name", "x" * 30),
])
def test_parse_invalid(key, text):
    with pytest.raises(ValueError):
        settings.parse(SETTINGS[key], text)


def test_work_range_tolerates_swapped_values():
    db = make()
    settings.save(db, 1, "work_min", 500)
    settings.save(db, 1, "work_max", 100)
    assert settings.load(db, 1).work_range == (100, 500)


def test_settings_fit_in_discord_choices():
    assert len(SETTINGS) <= 25
