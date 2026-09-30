from kelpbot import achievements
from kelpbot.achievements import ACHIEVEMENTS
from kelpbot.db import Database

G, U = 1, 42


def make():
    return Database(":memory:", starting_balance=1000)


def test_unlock_pays_once():
    db = make()
    first = achievements.unlock(db, G, U, "jackpot")
    assert [a.key for a in first] == ["jackpot"]
    assert achievements.unlock(db, G, U, "jackpot") == []
    assert db.balance(G, U) == 1000 + ACHIEVEMENTS["jackpot"].reward


def test_counter_goal():
    db = make()
    for _ in range(9):
        assert achievements.bump(db, G, U, "rob_success") == []
    assert [a.key for a in achievements.bump(db, G, U, "rob_success")] == ["master_thief"]
    assert achievements.bump(db, G, U, "rob_success") == []


def test_bulk_counter_bump():
    db = make()
    assert [a.key for a in achievements.bump(db, G, U, "items_bought", 12)] == ["shopaholic"]


def test_after_game():
    db = make()
    assert achievements.after_game(db, G, U, 100, 0) == []
    keys = [a.key for a in achievements.after_game(db, G, U, 10_000, 20_000)]
    assert keys == ["first_win", "high_roller"]


def test_wealth_checks():
    db = make()
    db.set_bank(G, U, 10_000, 0)
    db.credit(G, U, 1_000_000)
    assert {a.key for a in achievements.check_wealth(db, G, U)} == {"saver", "millionaire"}


def test_achievements_are_per_server():
    db = make()
    achievements.unlock(db, G, U, "duelist")
    assert achievements.unlock(db, 2, U, "duelist")
