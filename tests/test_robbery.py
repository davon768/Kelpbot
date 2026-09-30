import random

from kelpbot import config
from kelpbot.db import Database
from kelpbot.robbery import RobResult, attempt_rob

G, ROBBER, VICTIM = 1, 10, 20


class FixedRng(random.Random):
    """roll < chance means success; randint returns the low end of the range."""

    def __init__(self, roll):
        super().__init__(0)
        self.roll = roll

    def random(self):
        return self.roll

    def randint(self, a, b):
        return a


def make():
    return Database(":memory:", starting_balance=1000)


def test_successful_rob_moves_money_from_victim():
    db = make()
    out = attempt_rob(db, G, ROBBER, VICTIM, FixedRng(0.0))
    stolen = 1000 * config.ROB_STEAL_PERCENT[0] // 100
    assert out.result is RobResult.SUCCESS and out.amount == stolen
    assert db.balance(G, ROBBER) == 1000 + stolen
    assert db.balance(G, VICTIM) == 1000 - stolen


def test_caught_robber_pays_victim():
    db = make()
    out = attempt_rob(db, G, ROBBER, VICTIM, FixedRng(0.99))
    fine = config.ROB_FINE[0]
    assert out.result is RobResult.CAUGHT and out.amount == fine
    assert db.balance(G, ROBBER) == 1000 - fine
    assert db.balance(G, VICTIM) == 1000 + fine


def test_fine_is_capped_at_robbers_balance():
    db = make()
    db.credit(G, ROBBER, config.ROB_MIN_BALANCE - 1000)  # exactly the minimum
    rng = FixedRng(0.99)
    rng.randint = lambda a, b: b  # biggest possible fine
    out = attempt_rob(db, G, ROBBER, VICTIM, rng)
    assert out.amount == min(config.ROB_FINE[1], config.ROB_MIN_BALANCE)
    assert db.balance(G, ROBBER) == config.ROB_MIN_BALANCE - out.amount


def test_money_is_conserved():
    db = make()
    rng = random.Random(3)
    for _ in range(200):
        db.conn.execute("DELETE FROM cooldowns")
        attempt_rob(db, G, ROBBER, VICTIM, rng)
    assert db.balance(G, ROBBER) + db.balance(G, VICTIM) == 2000


def test_poor_players_cannot_rob_or_be_robbed():
    db = make()
    db.credit(G, ROBBER, -1000)
    assert attempt_rob(db, G, ROBBER, VICTIM).result is RobResult.ROBBER_TOO_POOR
    db.credit(G, ROBBER, 1000)
    db.credit(G, VICTIM, -1000)
    assert attempt_rob(db, G, ROBBER, VICTIM).result is RobResult.TARGET_TOO_POOR
    assert db.balance(G, ROBBER) == 1000 and db.balance(G, VICTIM) == 0


def test_victim_protected_after_being_robbed():
    db = make()
    attempt_rob(db, G, ROBBER, VICTIM, FixedRng(0.0))
    out = attempt_rob(db, G, 30, VICTIM, FixedRng(0.0))
    assert out.result is RobResult.TARGET_PROTECTED and out.protected_for > 0


def test_padlock_blocks_and_breaks():
    db = make()
    db.add_item(G, VICTIM, "padlock")
    out = attempt_rob(db, G, ROBBER, VICTIM, FixedRng(0.0))
    assert out.result is RobResult.BLOCKED
    assert db.balance(G, ROBBER) == 1000 and db.balance(G, VICTIM) == 1000
    assert db.item_count(G, VICTIM, "padlock") == 0


def test_crowbar_raises_success_chance_and_is_used_up():
    db = make()
    db.add_item(G, ROBBER, "crowbar")
    roll = config.ROB_SUCCESS_CHANCE + 0.1  # would fail without the crowbar
    out = attempt_rob(db, G, ROBBER, VICTIM, FixedRng(roll))
    assert out.result is RobResult.SUCCESS and out.used_crowbar
    assert db.item_count(G, ROBBER, "crowbar") == 0
