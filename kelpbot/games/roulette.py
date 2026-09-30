"""European roulette (single zero)."""

from __future__ import annotations

import random

RED_NUMBERS = frozenset({1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36})

# name -> (predicate, total return multiplier)
OUTSIDE_BETS = {
    "red": (lambda n: n in RED_NUMBERS, 2),
    "black": (lambda n: n != 0 and n not in RED_NUMBERS, 2),
    "odd": (lambda n: n != 0 and n % 2 == 1, 2),
    "even": (lambda n: n != 0 and n % 2 == 0, 2),
    "low": (lambda n: 1 <= n <= 18, 2),
    "high": (lambda n: 19 <= n <= 36, 2),
    "1st12": (lambda n: 1 <= n <= 12, 3),
    "2nd12": (lambda n: 13 <= n <= 24, 3),
    "3rd12": (lambda n: 25 <= n <= 36, 3),
}
STRAIGHT_UP_PAYOUT = 36


def color_of(n: int) -> str:
    if n == 0:
        return "green"
    return "red" if n in RED_NUMBERS else "black"


def color_emoji(n: int) -> str:
    return {"green": "🟢", "red": "🔴", "black": "⚫"}[color_of(n)]


def parse_choice(choice: str) -> str | int | None:
    """Normalise a user's bet choice. Returns None if it isn't a valid bet."""
    choice = choice.strip().lower().replace(" ", "")
    if choice in OUTSIDE_BETS:
        return choice
    if choice.isdigit() and 0 <= int(choice) <= 36:
        return int(choice)
    return None


def spin(rng: random.Random | None = None) -> int:
    return (rng or random).randint(0, 36)


def payout_multiplier(choice: str | int, result: int) -> int:
    if isinstance(choice, int):
        return STRAIGHT_UP_PAYOUT if choice == result else 0
    predicate, mult = OUTSIDE_BETS[choice]
    return mult if predicate(result) else 0
