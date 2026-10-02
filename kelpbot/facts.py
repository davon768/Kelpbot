"""Fact decks for /funfact and /notsofunfact.

Each server works through a deck in its own shuffled order, so no fact repeats until
every fact in the deck has been shown. Then it reshuffles and starts a new cycle.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from kelpbot import decks
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


def next_fact(db: Database, guild_id: int, deck: Deck, rng: random.Random | None = None) -> tuple[Fact, int]:
    """The next fact for this server, and its position (1-based) in the current cycle."""
    index, position = decks.next_index(db, guild_id, deck.key, len(deck.facts), rng)
    return deck.facts[index], position
