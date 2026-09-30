"""Mines: reveal safe tiles for a growing multiplier, but hit a mine and lose it all."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

TILES = 20  # 4 rows of 5 buttons; the 5th row holds Cash Out
HOUSE_EDGE = 0.97


def multiplier(mines: int, safe_revealed: int) -> float:
    """Fair odds of surviving that many picks, minus the house edge."""
    if safe_revealed == 0:
        return 1.0
    m = 1.0
    for i in range(safe_revealed):
        m *= (TILES - i) / (TILES - mines - i)
    return round(m * HOUSE_EDGE, 2)


@dataclass
class MinesGame:
    bet: int
    mines: int
    rng: random.Random | None = None
    mine_tiles: set[int] = field(default_factory=set)
    revealed: set[int] = field(default_factory=set)
    exploded: bool = False
    cashed_out: bool = False

    def __post_init__(self) -> None:
        if not self.mine_tiles:
            self.mine_tiles = set((self.rng or random).sample(range(TILES), self.mines))

    @property
    def finished(self) -> bool:
        return self.exploded or self.cashed_out

    @property
    def current_multiplier(self) -> float:
        return multiplier(self.mines, len(self.revealed))

    @property
    def next_multiplier(self) -> float:
        return multiplier(self.mines, len(self.revealed) + 1)

    @property
    def cleared(self) -> bool:
        return len(self.revealed) == TILES - self.mines

    def reveal(self, tile: int) -> bool:
        """Returns True if the tile was safe."""
        if self.finished or tile in self.revealed:
            return not self.exploded
        if tile in self.mine_tiles:
            self.exploded = True
            return False
        self.revealed.add(tile)
        if self.cleared:
            self.cashed_out = True
        return True

    def cash_out(self) -> bool:
        if self.finished or not self.revealed:
            return False
        self.cashed_out = True
        return True

    def payout(self) -> int:
        return int(self.bet * self.current_multiplier) if self.cashed_out else 0
