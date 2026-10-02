"""Shuffled no-repeat decks shared by /funfact, /notsofunfact and /trivia.

Each server works through a deck in its own shuffled order, so nothing repeats until every
item has been used. Then it reshuffles. The order and position are saved per server.
"""

from __future__ import annotations

import random
from functools import lru_cache

from kelpbot.db import Database


@lru_cache(maxsize=64)
def _order(seed: int, size: int) -> tuple[int, ...]:
    return tuple(random.Random(seed).sample(range(size), size))


def next_index(db: Database, guild_id: int, key: str, size: int,
               rng: random.Random | None = None) -> tuple[int, int]:
    """(index of the next item, its 1-based position in the current cycle)."""
    rng = rng or random.Random()
    raw = db.config(guild_id)
    seed_key, pos_key, size_key = f"_{key}_seed", f"_{key}_pos", f"_{key}_size"
    seed = raw.get(seed_key)
    pos = int(raw.get(pos_key, 0))
    if seed is None or int(raw.get(size_key, 0)) != size or pos >= size:
        # First use, the list changed, or the cycle is finished: shuffle a fresh order.
        previous = _order(int(seed), size)[-1] if seed is not None and pos >= size else None
        seed = rng.randrange(2**31)
        if previous is not None and size > 1 and _order(seed, size)[0] == previous:
            seed += 1  # don't open the new cycle with the item that just closed the last one
        pos = 0
        db.set_config(guild_id, size_key, size)
    seed = int(seed)
    db.set_config(guild_id, seed_key, seed)
    db.set_config(guild_id, pos_key, pos + 1)
    return _order(seed, size)[pos], pos + 1
