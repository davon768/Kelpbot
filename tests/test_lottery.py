import random

from kelpbot import config, lottery
from kelpbot.db import Database
from kelpbot.lottery import BuyResult

G = 1


def make():
    return Database(":memory:", starting_balance=10_000)


def test_first_ticket_starts_round():
    db = make()
    assert db.lottery_round(G) is None
    assert lottery.buy(db, G, 1, 5, 100, channel_id=9, now=1000.0) is BuyResult.OK
    rnd = db.lottery_round(G)
    assert rnd.draw_at == 1000.0 + config.LOTTERY_ROUND_SECONDS and rnd.channel_id == 9 and rnd.pot == 500
    # later tickets don't push the draw back
    lottery.buy(db, G, 2, 1, 100, channel_id=8, now=5000.0)
    assert db.lottery_round(G).draw_at == rnd.draw_at and db.lottery_round(G).pot == 600
    assert db.balance(G, 1) == 9_500


def test_limits():
    db = make()
    assert lottery.buy(db, G, 1, config.LOTTERY_MAX_TICKETS + 1, 1, 0) is BuyResult.TOO_MANY
    assert lottery.buy(db, G, 1, 100, 1_000, 0) is BuyResult.CANT_AFFORD
    assert db.lottery_round(G) is None and db.balance(G, 1) == 10_000


def test_draw_pays_winner_minus_house_cut_and_resets():
    db = make()
    lottery.buy(db, G, 1, 10, 100, 0)
    lottery.buy(db, G, 2, 30, 100, 0)
    result = lottery.draw(db, G, random.Random(1))
    assert result.total_tickets == 40 and result.players == 2
    assert result.prize == 4_000 * (100 - config.LOTTERY_HOUSE_CUT_PERCENT) // 100
    assert db.balance(G, result.winner_id) == 10_000 - result.winner_tickets * 100 + result.prize
    assert db.lottery_round(G) is None and db.lottery_tickets(G) == {}


def test_draw_is_weighted_by_tickets():
    wins = {1: 0, 2: 0}
    rng = random.Random(7)
    for _ in range(2000):
        db = make()
        lottery.buy(db, G, 1, 1, 1, 0)
        lottery.buy(db, G, 2, 9, 1, 0)
        wins[lottery.draw(db, G, rng).winner_id] += 1
    assert 0.05 < wins[1] / 2000 < 0.15


def test_due_rounds():
    db = make()
    lottery.buy(db, G, 1, 1, 1, 0, now=0.0)
    assert db.due_lottery_rounds(config.LOTTERY_ROUND_SECONDS - 1) == []
    assert [r.guild_id for r in db.due_lottery_rounds(config.LOTTERY_ROUND_SECONDS)] == [G]
