"""Server lottery: tickets go into a pot and one ticket wins it when the round ends."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from enum import Enum

from kelpbot import config
from kelpbot.db import Database


class BuyResult(Enum):
    OK = "ok"
    CANT_AFFORD = "cant_afford"
    TOO_MANY = "too_many"


def buy(db: Database, guild_id: int, user_id: int, count: int, price: int, channel_id: int,
        now: float | None = None) -> BuyResult:
    now = time.time() if now is None else now
    owned = db.lottery_tickets(guild_id).get(user_id, 0)
    if owned + count > config.LOTTERY_MAX_TICKETS:
        return BuyResult.TOO_MANY
    cost = count * price
    with db.transaction():
        if not db.try_debit(guild_id, user_id, cost):
            return BuyResult.CANT_AFFORD
        db.start_lottery_round(guild_id, now + config.LOTTERY_ROUND_SECONDS, channel_id)
        db.add_lottery_tickets(guild_id, user_id, count, cost)
    return BuyResult.OK


@dataclass
class DrawResult:
    winner_id: int
    prize: int
    winner_tickets: int
    total_tickets: int
    players: int
    channel_id: int


def draw(db: Database, guild_id: int, rng: random.Random | None = None) -> DrawResult | None:
    """Pick a winner (weighted by tickets), pay them, and close the round."""
    rng = rng or random
    rnd = db.lottery_round(guild_id)
    tickets = db.lottery_tickets(guild_id)
    if rnd is None:
        return None
    with db.transaction():
        db.end_lottery_round(guild_id)
        if not tickets:
            return None
        winner = rng.choices(list(tickets), weights=list(tickets.values()))[0]
        prize = rnd.pot * (100 - config.LOTTERY_HOUSE_CUT_PERCENT) // 100
        db.credit(guild_id, winner, prize)
    return DrawResult(winner, prize, tickets[winner], sum(tickets.values()), len(tickets), rnd.channel_id)
