"""Heist odds: bigger crews are safer, but the loot is split more ways."""

from __future__ import annotations

import math
import random

MIN_CREW = 2
HOUSE_EDGE = 0.95


def success_chance(crew: int) -> float:
    return min(0.8, 0.3 + 0.1 * crew)


def multiplier(crew: int) -> float:
    """What each member gets back per coin bet if the heist works."""
    return math.floor(HOUSE_EDGE / success_chance(crew) * 100) / 100


def attempt(crew: int, rng: random.Random | None = None) -> bool:
    return (rng or random).random() < success_chance(crew)
