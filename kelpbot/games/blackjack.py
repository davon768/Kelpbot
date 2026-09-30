"""Blackjack game state, independent of Discord."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum

SUITS = ("♠", "♥", "♦", "♣")
RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
DECKS_IN_SHOE = 6


@dataclass(frozen=True)
class Card:
    rank: str
    suit: str

    @property
    def value(self) -> int:
        if self.rank == "A":
            return 11
        if self.rank in ("J", "Q", "K"):
            return 10
        return int(self.rank)

    def __str__(self) -> str:
        return f"{self.rank}{self.suit}"


def new_shoe(rng: random.Random | None = None) -> list[Card]:
    cards = [Card(r, s) for _ in range(DECKS_IN_SHOE) for s in SUITS for r in RANKS]
    (rng or random).shuffle(cards)
    return cards


def hand_value(cards: list[Card]) -> int:
    total = sum(c.value for c in cards)
    aces = sum(c.rank == "A" for c in cards)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def is_blackjack(cards: list[Card]) -> bool:
    return len(cards) == 2 and hand_value(cards) == 21


def format_hand(cards: list[Card], hide_hole: bool = False) -> str:
    if hide_hole:
        return f"{cards[0]} 🂠"
    return " ".join(str(c) for c in cards)


class Outcome(Enum):
    BLACKJACK = "Blackjack!"
    WIN = "You win!"
    PUSH = "Push"
    LOSE = "You lose"
    BUST = "Bust!"
    DEALER_BLACKJACK = "Dealer has blackjack"


@dataclass
class BlackjackGame:
    bet: int
    rng: random.Random | None = None
    shoe: list[Card] = field(default_factory=list)
    player: list[Card] = field(default_factory=list)
    dealer: list[Card] = field(default_factory=list)
    doubled: bool = False
    outcome: Outcome | None = None

    def __post_init__(self) -> None:
        if not self.shoe:
            self.shoe = new_shoe(self.rng)
        if not self.player:
            self.player = [self._draw(), self._draw()]
            self.dealer = [self._draw(), self._draw()]
        if is_blackjack(self.player) or is_blackjack(self.dealer):
            self._settle()

    @property
    def finished(self) -> bool:
        return self.outcome is not None

    @property
    def can_double(self) -> bool:
        return not self.finished and len(self.player) == 2

    def _draw(self) -> Card:
        return self.shoe.pop()

    def hit(self) -> None:
        if self.finished:
            return
        self.player.append(self._draw())
        if hand_value(self.player) > 21:
            self.outcome = Outcome.BUST
        elif hand_value(self.player) == 21:
            self.stand()

    def stand(self) -> None:
        if self.finished:
            return
        while hand_value(self.dealer) < 17:
            self.dealer.append(self._draw())
        self._settle()

    def double_down(self) -> None:
        """Caller is responsible for charging the extra bet before calling this."""
        if not self.can_double:
            return
        self.bet *= 2
        self.doubled = True
        self.player.append(self._draw())
        if hand_value(self.player) > 21:
            self.outcome = Outcome.BUST
        else:
            self.stand()

    def _settle(self) -> None:
        p, d = hand_value(self.player), hand_value(self.dealer)
        if is_blackjack(self.player) and is_blackjack(self.dealer):
            self.outcome = Outcome.PUSH
        elif is_blackjack(self.player):
            self.outcome = Outcome.BLACKJACK
        elif is_blackjack(self.dealer):
            self.outcome = Outcome.DEALER_BLACKJACK
        elif p > 21:
            self.outcome = Outcome.BUST
        elif d > 21 or p > d:
            self.outcome = Outcome.WIN
        elif p == d:
            self.outcome = Outcome.PUSH
        else:
            self.outcome = Outcome.LOSE

    def payout(self) -> int:
        """Total amount returned to the player (includes their stake)."""
        return {
            Outcome.BLACKJACK: self.bet + self.bet * 3 // 2,
            Outcome.WIN: self.bet * 2,
            Outcome.PUSH: self.bet,
        }.get(self.outcome, 0)
