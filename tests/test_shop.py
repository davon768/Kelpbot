from kelpbot import shop
from kelpbot.db import Database
from kelpbot.shop import LAPTOP, PADLOCK, TROPHY, TradeResult

G, U = 1, 42


def make(balance=1000):
    return Database(":memory:", starting_balance=balance)


def test_buy_charges_and_adds_item():
    db = make()
    assert shop.buy(db, G, U, PADLOCK.key) is TradeResult.OK
    assert db.balance(G, U) == 1000 - PADLOCK.price
    assert db.inventory(G, U) == {PADLOCK.key: 1}


def test_cant_afford_changes_nothing():
    db = make()
    assert shop.buy(db, G, U, TROPHY.key) is TradeResult.CANT_AFFORD
    assert db.balance(G, U) == 1000 and db.inventory(G, U) == {}


def test_max_owned_enforced():
    db = make(100_000)
    assert shop.buy(db, G, U, LAPTOP.key) is TradeResult.OK
    assert shop.buy(db, G, U, LAPTOP.key) is TradeResult.MAX_OWNED
    assert shop.buy(db, G, U, PADLOCK.key, 4) is TradeResult.MAX_OWNED
    assert db.balance(G, U) == 100_000 - LAPTOP.price


def test_sell_refunds_half_and_removes_row():
    db = make(100_000)
    shop.buy(db, G, U, PADLOCK.key, 2)
    assert shop.sell(db, G, U, PADLOCK.key, 2) is TradeResult.OK
    assert db.balance(G, U) == 100_000 - PADLOCK.price
    assert db.inventory(G, U) == {}
    assert shop.sell(db, G, U, PADLOCK.key) is TradeResult.NOT_OWNED


def test_unknown_item():
    assert shop.buy(make(), G, U, "nope") is TradeResult.UNKNOWN_ITEM
