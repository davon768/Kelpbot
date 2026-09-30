"""Higher or lower: guess whether the next card beats the current one. Ties lose."""

from __future__ import annotations

import random
from dataclasses import dataclass

LABELS = {1: "A", 11: "J", 12: "Q", 13: "K"}
HOUSE_EDGE = 0.97
MAX_MULTIPLIER = 1_000.0


def label(card: int) -> str:
    return LABELS.get(card, str(card))


def winning_cards(card: int, higher: bool) -> int:
    return 13 - card if higher else card - 1


def guess_multiplier(card: int, higher: bool) -> float | None:
    wins = winning_cards(card, higher)
    return round(HOUSE_EDGE * 13 / wins, 2) if wins else None


@dataclass
class HighLowGame:
    bet: int
    rng: random.Random | None = None
    card: int = 0
    previous: int | None = None
    multiplier: float = 1.0
    streak: int = 0
    lost: bool = False
    cashed_out: bool = False

    def __post_init__(self) -> None:
        if not self.card:
            self.card = self._draw()

    def _draw(self) -> int:
        return (self.rng or random).randint(1, 13)

    @property
    def finished(self) -> bool:
        return self.lost or self.cashed_out

    def guess(self, higher: bool) -> bool:
        step = guess_multiplier(self.card, higher)
        if self.finished or step is None:
            return False
        nxt = self._draw()
        won = nxt > self.card if higher else nxt < self.card
        self.previous, self.card = self.card, nxt
        if not won:
            self.lost = True
            return False
        self.streak += 1
        self.multiplier = round(self.multiplier * step, 2)
        if self.multiplier >= MAX_MULTIPLIER:
            self.multiplier = MAX_MULTIPLIER
            self.cashed_out = True
        return True

    def cash_out(self) -> bool:
        if self.finished or self.streak == 0:
            return False
        self.cashed_out = True
        return True

    def payout(self) -> int:
        return int(self.bet * self.multiplier) if self.cashed_out else 0
