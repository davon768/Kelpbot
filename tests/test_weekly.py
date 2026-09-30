import datetime as dt

from kelpbot import config, weekly
from kelpbot.db import Database

G = 1


def make():
    return Database(":memory:", starting_balance=1000)


def test_week_key_changes_on_monday():
    sunday = dt.datetime(2026, 10, 4, 23, 59, tzinfo=dt.timezone.utc)
    monday = dt.datetime(2026, 10, 5, 0, 0, tzinfo=dt.timezone.utc)
    assert weekly.week_key(sunday) != weekly.week_key(monday)


def test_first_sight_just_starts_tracking():
    db = make()
    db.record_game(G, 1, 100, 500)
    assert weekly.roll_week(db, G, "2026-W40") is None
    assert db.account(G, 1).weekly_profit == 400  # not reset
    assert weekly.roll_week(db, G, "2026-W40") is None  # same week: nothing


def test_new_week_pays_top_three_winners_and_resets():
    db = make()
    weekly.roll_week(db, G, "2026-W40")
    for uid, profit in [(1, 300), (2, 900), (3, -50), (4, 100), (5, 50)]:
        db.record_game(G, uid, 100, 100 + profit)
    winners = weekly.roll_week(db, G, "2026-W41")
    assert [(u, p) for u, p, _ in winners] == [(2, 900), (1, 300), (4, 100)]
    assert [prize for *_, prize in winners] == list(config.WEEKLY_PRIZES)
    assert db.balance(G, 2) == 1000 + config.WEEKLY_PRIZES[0]
    assert all(a.weekly_profit == 0 for a in db.accounts(G))


def test_losers_dont_win_prizes():
    db = make()
    weekly.roll_week(db, G, "a")
    db.record_game(G, 1, 100, 0)
    assert weekly.roll_week(db, G, "b") == []


def test_end_season_records_and_wipes():
    db = make()
    db.credit(G, 1, 5_000)
    db.set_bank(G, 2, 9_000, 0)
    db.add_item(G, 1, "padlock")
    db.add_achievement(G, 1, "duelist")
    db.set_config(G, "max_bet", "123")
    season, top = weekly.end_season(db, G)
    assert season == 1 and top[:2] == [(2, 10_000), (1, 6_000)]
    assert db.hall_of_fame(G)[1][0] == (2, 10_000)
    assert db.accounts(G) == [] and db.inventory(G, 1) == {}
    assert db.achievements(G, 1) == {"duelist"} and db.config(G)["max_bet"] == "123"
    assert weekly.current_season(db, G) == 2


def test_reset_one_player_only():
    db = make()
    db.credit(G, 1, 500)
    db.credit(G, 2, 500)
    db.reset_economy(G, 1)
    assert db.balance(G, 1) == 1000 and db.balance(G, 2) == 1500
