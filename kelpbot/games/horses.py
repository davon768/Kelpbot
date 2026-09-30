"""Horse racing: five horses with different odds, and a race you can watch."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

HOUSE_EDGE = 0.95
TRACK_LENGTH = 16
FRAMES = 6


@dataclass(frozen=True)
class Horse:
    number: int
    name: str
    chance: float

    @property
    def payout(self) -> float:
        return math.floor(HOUSE_EDGE / self.chance * 10) / 10


HORSES: tuple[Horse, ...] = (
    Horse(1, "Seaweed Sprinter", 0.35),
    Horse(2, "Barnacle Bolt", 0.25),
    Horse(3, "Tidal Thunder", 0.20),
    Horse(4, "Coral Comet", 0.12),
    Horse(5, "Lucky Limpet", 0.08),
)


def pick_winner(rng: random.Random | None = None) -> Horse:
    return (rng or random).choices(HORSES, weights=[h.chance for h in HORSES])[0]


def race_frames(winner: Horse, rng: random.Random | None = None) -> list[list[int]]:
    """Positions of each horse for every frame. The winner crosses the line first, in the last frame."""
    rng = rng or random
    finish = {h.number: (TRACK_LENGTH if h == winner else rng.randint(TRACK_LENGTH * 5 // 8, TRACK_LENGTH - 1))
              for h in HORSES}
    frames = []
    for f in range(1, FRAMES + 1):
        frame = []
        for h in HORSES:
            share = f / FRAMES
            wobble = 0 if f == FRAMES else rng.randint(-1, 1)
            frame.append(max(0, min(finish[h.number] - (f < FRAMES), round(finish[h.number] * share) + wobble)))
        frames.append(frame)
    return frames


def render_track(positions: list[int]) -> str:
    lines = []
    for horse, pos in zip(HORSES, positions):
        track = "·" * pos + "🏇" + "·" * (TRACK_LENGTH - pos)
        lines.append(f"`{horse.number}` {track}🏁")
    return "\n".join(lines)
