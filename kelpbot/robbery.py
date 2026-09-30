"""Player-vs-player robbery rules, kept out of the cog so they can be tested."""

from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from kelpbot import config
from kelpbot.db import Database
from kelpbot.shop import CROWBAR, CROWBAR_BONUS, PADLOCK


class RobResult(Enum):
    SUCCESS = "success"
    CAUGHT = "caught"
    ROBBER_TOO_POOR = "robber_too_poor"
    TARGET_TOO_POOR = "target_too_poor"
    TARGET_PROTECTED = "target_protected"
    BLOCKED = "blocked"  # victim's padlock stopped it


@dataclass
class RobOutcome:
    result: RobResult
    amount: int = 0  # stolen on success, fine paid on failure
    protected_for: float = 0.0
    used_crowbar: bool = False


def attempt_rob(db: Database, guild_id: int, robber: int, victim: int, rng: random.Random | None = None) -> RobOutcome:
    """Validate and resolve a robbery. SUCCESS, CAUGHT and BLOCKED count as an attempt."""
    rng = rng or random
    if db.balance(guild_id, robber) < config.ROB_MIN_BALANCE:
        return RobOutcome(RobResult.ROBBER_TOO_POOR)
    victim_balance = db.balance(guild_id, victim)
    if victim_balance < config.ROB_MIN_TARGET_BALANCE:
        return RobOutcome(RobResult.TARGET_TOO_POOR)
    protected = db.cooldown_remaining(guild_id, victim, "robbed", config.ROB_VICTIM_PROTECTION)
    if protected:
        return RobOutcome(RobResult.TARGET_PROTECTED, protected_for=protected)

    if db.remove_item(guild_id, victim, PADLOCK.key):
        return RobOutcome(RobResult.BLOCKED)

    chance = config.ROB_SUCCESS_CHANCE
    used_crowbar = db.remove_item(guild_id, robber, CROWBAR.key)
    if used_crowbar:
        chance += CROWBAR_BONUS

    if rng.random() < chance:
        amount = max(1, victim_balance * rng.randint(*config.ROB_STEAL_PERCENT) // 100)
        db.transfer(guild_id, victim, robber, amount)
        db.mark_used(guild_id, victim, "robbed")
        return RobOutcome(RobResult.SUCCESS, amount, used_crowbar=used_crowbar)

    fine = min(rng.randint(*config.ROB_FINE), db.balance(guild_id, robber))
    db.transfer(guild_id, robber, victim, fine)
    return RobOutcome(RobResult.CAUGHT, fine, used_crowbar=used_crowbar)
