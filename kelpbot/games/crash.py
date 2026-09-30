"""Crash: a multiplier climbs until it crashes. Cash out before it does."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

GROWTH_PER_SECOND = 0.12  # 2x after ~6s, 10x after ~19s
MAX_MULTIPLIER = 100.0
HOUSE_EDGE = 0.01  # P(crash point >= x) = 0.99 / x, so any strategy returns 99%


def crash_point(rng: random.Random | None = None) -> float:
    u = (rng or random).random()
    point = (1 - HOUSE_EDGE) / (1 - u)
    return max(1.0, min(MAX_MULTIPLIER, math.floor(point * 100) / 100))


def multiplier_at(elapsed: float) -> float:
    return math.floor(math.exp(GROWTH_PER_SECOND * max(0.0, elapsed)) * 100) / 100


@dataclass
class CrashGame:
    bet: int
    crash_at: float
    started: float
    auto_cashout: float | None = None
    cashed_out: float | None = None
    crashed: bool = False

    @property
    def finished(self) -> bool:
        return self.crashed or self.cashed_out is not None

    def current(self, now: float) -> float:
        return min(multiplier_at(now - self.started), self.crash_at)

    def tick(self, now: float) -> None:
        """Advance the game: trigger auto cash-out or the crash if their time has come."""
        if self.finished:
            return
        m = multiplier_at(now - self.started)
        if self.auto_cashout is not None and self.auto_cashout <= self.crash_at and m >= self.auto_cashout:
            self.cashed_out = self.auto_cashout
        elif m >= self.crash_at:
            self.crashed = True

    def cash_out(self, now: float) -> bool:
        self.tick(now)
        if self.finished:
            return False
        self.cashed_out = multiplier_at(now - self.started)
        return True

    def payout(self) -> int:
        return int(self.bet * self.cashed_out) if self.cashed_out else 0
