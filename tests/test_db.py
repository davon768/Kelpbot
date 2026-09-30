from kelpbot.db import Database


def make():
    return Database(":memory:", starting_balance=1000)


def test_new_account_gets_starting_balance():
    assert make().balance(1, 42) == 1000


def test_debit_refuses_overdraft():
    db = make()
    assert db.try_debit(1, 42, 600)
    assert not db.try_debit(1, 42, 600)
    assert db.balance(1, 42) == 400


def test_credit_never_goes_negative():
    db = make()
    assert db.credit(1, 42, -5000) == 0


def test_transfer():
    db = make()
    assert db.transfer(1, 1, 2, 300)
    assert db.balance(1, 1) == 700 and db.balance(1, 2) == 1300
    assert not db.transfer(1, 1, 2, 5000)
    assert db.balance(1, 1) == 700


def test_balances_are_per_server():
    db = make()
    db.credit(1, 42, 500)
    assert db.balance(1, 42) == 1500 and db.balance(2, 42) == 1000


def test_cooldowns_and_stats():
    db = make()
    assert db.cooldown_remaining(1, 42, "work", 3600) == 0
    db.mark_used(1, 42, "work")
    assert 3590 < db.cooldown_remaining(1, 42, "work", 3600) <= 3600
    db.record_game(1, 42, 100, 300)
    db.record_game(1, 42, 100, 0)
    a = db.account(1, 42)
    assert (a.games_played, a.total_wagered, a.biggest_win, a.net) == (2, 200, 200, 100)


def test_leaderboard_order():
    db = make()
    db.credit(1, 1, 50)
    db.credit(1, 2, 500)
    db.credit(1, 3, -100)
    assert [a.user_id for a in db.leaderboard(1)] == [2, 1, 3]
