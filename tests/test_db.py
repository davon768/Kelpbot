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


def test_upgrades_a_first_release_database(tmp_path):
    import sqlite3

    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE accounts (guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, balance INTEGER NOT NULL,
            daily_streak INTEGER NOT NULL DEFAULT 0, total_wagered INTEGER NOT NULL DEFAULT 0,
            total_won INTEGER NOT NULL DEFAULT 0, games_played INTEGER NOT NULL DEFAULT 0,
            biggest_win INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (guild_id, user_id));
        CREATE TABLE guild_settings (guild_id INTEGER PRIMARY KEY, auto_delete_seconds INTEGER);
        INSERT INTO accounts (guild_id, user_id, balance) VALUES (1, 42, 4321);
        INSERT INTO guild_settings VALUES (1, 30);
    """)
    old.commit()
    old.close()
    db = Database(path, 1000, auto_delete_default=120)
    acct = db.account(1, 42)
    assert (acct.balance, acct.bank, acct.work_xp, acct.weekly_profit) == (4321, 0, 0, 0)
    assert db.auto_delete_seconds(1) == 30
    db.log_game(1, 42, "dice", 10, 0)
    db.open_bet(1, 42, "crash", 5)
    assert db.refund_open_bets() == [(1, 42, "crash", 5)]
