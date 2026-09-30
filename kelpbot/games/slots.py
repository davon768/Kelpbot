"""Slot machine logic. Pure functions so it can be unit tested without Discord."""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class Symbol:
    emoji: str
    weight: int
    triple_payout: int  # total return multiplier for three of a kind


SYMBOLS: tuple[Symbol, ...] = (
    Symbol("🍒", 30, 5),
    Symbol("🍋", 25, 10),
    Symbol("🍊", 20, 15),
    Symbol("🍇", 14, 25),
    Symbol("🔔", 7, 50),
    Symbol("💎", 3, 100),
    Symbol("7️⃣", 1, 500),
)

CHERRY = SYMBOLS[0]
TWO_CHERRY_PAYOUT = 2
REELS = 3


def spin(rng: random.Random | None = None) -> list[Symbol]:
    rng = rng or random
    return rng.choices(SYMBOLS, weights=[s.weight for s in SYMBOLS], k=REELS)


def payout_multiplier(reels: list[Symbol]) -> int:
    """Total return as a multiple of the bet (0 means the bet is lost)."""
    if all(s == reels[0] for s in reels):
        return reels[0].triple_payout
    if sum(s == CHERRY for s in reels) == 2:
        return TWO_CHERRY_PAYOUT
    return 0


def paytable_lines() -> list[str]:
    lines = [f"{s.emoji}{s.emoji}{s.emoji} → **{s.triple_payout}x**" for s in reversed(SYMBOLS)]
    lines.append(f"Any two {CHERRY.emoji} → **{TWO_CHERRY_PAYOUT}x**")
    return lines
