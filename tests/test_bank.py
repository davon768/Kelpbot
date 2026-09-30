import random

from kelpbot import bank, config
from kelpbot.bank import DAY
from kelpbot.db import Database
from kelpbot.robbery import attempt_rob

G, U = 1, 42


def make():
    return Database(":memory:", starting_balance=100_000)


def test_deposit_and_withdraw():
    db = make()
    assert bank.deposit(db, G, U, 40_000, 1)
    acct = db.account(G, U)
    assert (acct.balance, acct.bank, acct.net_worth) == (60_000, 40_000, 100_000)
    assert not bank.deposit(db, G, U, 70_000, 1)
    assert not bank.withdraw(db, G, U, 50_000, 1)
    assert bank.withdraw(db, G, U, 15_000, 1)
    acct = db.account(G, U)
    assert (acct.balance, acct.bank) == (75_000, 25_000)


def test_interest_per_full_day_compounds():
    db = make()
    t0 = 1_000_000.0
    bank.accrue(db, G, U, 1, now=t0)  # starts the timer
    db.set_bank(G, U, 10_000, t0)
    assert bank.accrue(db, G, U, 1, now=t0 + DAY - 1) == 0
    assert bank.accrue(db, G, U, 1, now=t0 + 2 * DAY + 5) == 100 + 101
    assert db.account(G, U).bank == 10_201
    # the leftover 5 seconds carry over rather than being lost
    assert bank.accrue(db, G, U, 1, now=t0 + 3 * DAY) == 102


def test_interest_is_capped_per_day():
    db = make()
    db.set_bank(G, U, 10_000_000, 1.0)
    assert bank.accrue(db, G, U, 10, now=1.0 + DAY) == config.BANK_INTEREST_CAP


def test_zero_rate_pays_nothing():
    db = make()
    db.set_bank(G, U, 10_000, 1.0)
    assert bank.accrue(db, G, U, 0, now=1.0 + 10 * DAY) == 0


def test_banked_money_is_safe_from_robbers():
    db = make()
    bank.deposit(db, G, 2, 100_000, 1)  # victim banks everything
    out = attempt_rob(db, G, U, 2, random.Random(0))
    assert out.result.value == "target_too_poor"
    assert db.account(G, 2).bank == 100_000


def test_parse_amount():
    assert bank.parse_amount("all", 500) == 500
    assert bank.parse_amount("half", 501) == 250
    assert bank.parse_amount("1,200", 0) == 1200
    assert bank.parse_amount("-5", 100) is None
    assert bank.parse_amount("lots", 100) is None
