"""Fact decks for /funfact and /notsofunfact.

Each server works through a deck in its own shuffled order, so no fact repeats until
every fact in the deck has been shown. Then it reshuffles and starts a new cycle.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from functools import lru_cache

from kelpbot.db import Database

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")


@dataclass(frozen=True)
class Fact:
    text: str
    category: str


@dataclass(frozen=True)
class Deck:
    key: str  # used to store each server's place in the deck
    facts: tuple[Fact, ...]


def load(filename: str) -> tuple[Fact, ...]:
    """Read a fact file: '# Header' lines start a category; other '#' lines are comments."""
    facts, category = [], "Misc"
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                header = line.lstrip("#").strip()
                # Category headers are short titles; longer lines are comments.
                if header and len(header) <= 40 and not header.endswith("."):
                    category = header
                continue
            facts.append(Fact(line, category))
    return tuple(facts)


FUN = Deck("funfact", load("fun_facts.txt"))
NOT_FUN = Deck("notfunfact", load("not_fun_facts.txt"))


@lru_cache(maxsize=64)
def _order(seed: int, size: int) -> tuple[int, ...]:
    return tuple(random.Random(seed).sample(range(size), size))


def next_fact(db: Database, guild_id: int, deck: Deck, rng: random.Random | None = None) -> tuple[Fact, int]:
    """The next fact for this server, and its position (1-based) in the current cycle."""
    rng = rng or random.Random()
    size = len(deck.facts)
    raw = db.config(guild_id)
    seed_key, pos_key, size_key = f"_{deck.key}_seed", f"_{deck.key}_pos", f"_{deck.key}_size"
    seed = raw.get(seed_key)
    pos = int(raw.get(pos_key, 0))
    if seed is None or int(raw.get(size_key, 0)) != size or pos >= size:
        # First use, the list was edited, or the cycle is finished: shuffle a fresh order.
        previous = _order(int(seed), int(raw.get(size_key, size)))[-1] if seed is not None and pos >= size else None
        seed = rng.randrange(2**31)
        if previous is not None and _order(seed, size)[0] == previous and size > 1:
            seed += 1  # don't open the new cycle with the fact that just closed the last one
        pos = 0
        db.set_config(guild_id, size_key, size)
    seed = int(seed)
    fact = deck.facts[_order(seed, size)[pos]]
    db.set_config(guild_id, seed_key, seed)
    db.set_config(guild_id, pos_key, pos + 1)
    return fact, pos + 1
