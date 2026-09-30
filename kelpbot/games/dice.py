"""Dice: roll 1-100 and win if the roll is at or under your chosen win chance."""

from __future__ import annotations

import math
import random

HOUSE_EDGE = 0.98
MIN_CHANCE, MAX_CHANCE = 1, 95


def multiplier(chance: int) -> float:
    return math.floor(HOUSE_EDGE * 100 / chance * 100) / 100


def roll(rng: random.Random | None = None) -> int:
    return (rng or random).randint(1, 100)


def payout(bet: int, chance: int, rolled: int) -> int:
    return int(bet * multiplier(chance)) if rolled <= chance else 0
