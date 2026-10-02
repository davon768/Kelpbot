"""The trivia question bank: hand-written questions plus ones built from checked fact tables."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "trivia")
DIFFICULTIES = ("easy", "medium", "hard")

TOPICS: dict[str, str] = {
    "general": "General knowledge",
    "geography": "Geography",
    "flags": "Flags",
    "elements": "Chemical elements",
    "roman": "Roman numerals",
}


@dataclass(frozen=True)
class Question:
    topic: str  # a key of TOPICS
    category: str  # shown to players
    difficulty: str
    prompt: str
    answer: str
    wrong_pool: tuple[str, ...]  # three are picked each time the question is asked

    def options(self, rng: random.Random | None = None) -> tuple[list[str], int]:
        """Four shuffled options and the index of the right one."""
        rng = rng or random
        wrong = rng.sample(self.wrong_pool, 3)
        options = [self.answer, *wrong]
        rng.shuffle(options)
        return options, options.index(self.answer)


def _rows(filename: str) -> list[list[str]]:
    with open(os.path.join(DATA_DIR, filename), encoding="utf-8") as f:
        return [line.rstrip("\n").split("\t") for line in f if line.strip() and not line.startswith("#")]


# ---- hand-written --------------------------------------------------------------------

def load_general() -> list[Question]:
    questions, category = [], "General"
    with open(os.path.join(DATA_DIR, "general.txt"), encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#"):
                header = line.lstrip("#").strip()
                if header and len(header) <= 40 and "|" not in header and not header.endswith("."):
                    category = header
                continue
            difficulty, prompt, answer, *wrong = line.split("|")
            questions.append(Question("general", category, difficulty, prompt, answer, tuple(wrong)))
    return questions


# ---- countries -----------------------------------------------------------------------

# Well-known countries get "easy" capital and flag questions.
EASY_COUNTRIES = {
    "Argentina", "Australia", "Brazil", "Canada", "China", "Egypt", "France", "Germany", "Greece", "India",
    "Ireland", "Italy", "Japan", "Mexico", "Netherlands", "Norway", "Peru", "Portugal", "Russia",
    "South Korea", "Spain", "Sweden", "Thailand", "United Kingdom", "United States",
}
# Flags that look nearly identical at emoji size never appear as each other's wrong answers.
LOOKALIKE_FLAGS = [{"TD", "RO"}, {"ID", "MC"}, {"NL", "LU"}, {"IE", "CI"}, {"AU", "NZ"}]
CONTINENTS = ("Africa", "Asia", "Europe", "North America", "South America", "Oceania")


# Countries whose names read naturally with "the" in a sentence.
THE_COUNTRIES = {
    "United Kingdom", "United States", "Netherlands", "Bahamas", "Gambia", "Philippines", "Maldives",
    "Marshall Islands", "Solomon Islands", "Seychelles", "Comoros", "Central African Republic",
    "Dominican Republic", "Republic of the Congo", "Democratic Republic of the Congo", "United Arab Emirates",
}


def in_sentence(name: str) -> str:
    return f"the {name}" if name in THE_COUNTRIES else name


def flag_emoji(code: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper())


def _country_difficulty(name: str, continent: str) -> str:
    if name in EASY_COUNTRIES:
        return "easy"
    return "hard" if continent in ("Oceania", "-") else "medium"


def _overlaps(a: str, b: str) -> bool:
    return a.lower() in b.lower() or b.lower() in a.lower()


def load_countries() -> list[Question]:
    rows = _rows("countries.tsv")
    capitals = {name: cap for _, name, cap, _ in rows if cap != "-"}
    questions = []
    for code, name, capital, continent in rows:
        difficulty = _country_difficulty(name, continent)
        if capital != "-":
            other_caps = tuple(c for n, c in capitals.items() if n != name)
            questions.append(Question("geography", "Capitals", difficulty,
                                      f"What is the capital of {in_sentence(name)}?",
                                      capital, other_caps))
            if not _overlaps(name, capital):  # "What country is Kuwait City the capital of?" is too easy
                other_countries = tuple(n for n in capitals if n != name)
                questions.append(Question("geography", "Capitals", difficulty,
                                          f"{capital} is the capital of which country?", name, other_countries))
        lookalikes = set().union(*(g for g in LOOKALIKE_FLAGS if code in g)) - {code}
        flag_pool = tuple(n for c, n, _, _ in rows if c != code and c not in lookalikes)
        questions.append(Question("flags", "Flags", difficulty,
                                  f"Which country does this flag belong to? {flag_emoji(code)}", name, flag_pool))
        if continent != "-":
            questions.append(Question("geography", "Continents", "easy" if name in EASY_COUNTRIES else "medium",
                                      f"Which continent is {in_sentence(name)} in?", continent,
                                      tuple(c for c in CONTINENTS if c != continent)))
            outside = tuple(n for _, n, _, cont in rows if cont not in (continent, "-"))
            questions.append(Question("geography", "Continents", "medium",
                                      f"Which of these countries is in {continent}?", name, outside))
    return questions


def load_us_states() -> list[Question]:
    rows = _rows("us_states.tsv")
    questions = []
    for abbr, state, capital in rows:
        questions.append(Question("geography", "US states", "medium", f"What is the capital of {state}?", capital,
                                  tuple(c for _, s, c in rows if s != state)))
        questions.append(Question("geography", "US states", "medium",
                                  f"{capital} is the capital of which US state?", state,
                                  tuple(s for _, s, _ in rows if s != state)))
        questions.append(Question("geography", "US states", "hard",
                                  f"Which US state has the postal abbreviation {abbr}?", state,
                                  tuple(s for _, s, _ in rows if s != state)))
    return questions


# ---- elements ------------------------------------------------------------------------

def _element_difficulty(number: int) -> str:
    return "easy" if number <= 20 else "medium" if number <= 56 else "hard"


def load_elements() -> list[Question]:
    rows = [(int(n), sym, name) for n, sym, name in _rows("elements.tsv") if int(n) <= 100]
    questions = []
    for number, symbol, name in rows:
        difficulty = _element_difficulty(number)
        others = [(n, s, nm) for n, s, nm in rows if n != number]
        questions.append(Question("elements", "Elements", difficulty,
                                  f"Which element has the chemical symbol {symbol}?", name,
                                  tuple(nm for _, _, nm in others)))
        questions.append(Question("elements", "Elements", difficulty, f"What is the chemical symbol for {name}?",
                                  symbol, tuple(s for _, s, _ in others)))
        nearby = tuple(nm for n, _, nm in others if abs(n - number) <= 12)
        questions.append(Question("elements", "Elements", difficulty,
                                  f"Which element has atomic number {number}?", name, nearby))
        if number <= 60:
            numbers = tuple(str(n) for n in range(max(1, number - 6), number + 7) if n != number)
            questions.append(Question("elements", "Elements", difficulty,
                                      f"What is the atomic number of {name}?", str(number), numbers))
    return questions


# ---- Roman numerals ------------------------------------------------------------------------

ROMAN = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
         (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
YEARS = (1066, 1215, 1492, 1588, 1666, 1776, 1815, 1848, 1903, 1914, 1929, 1945, 1969, 1989, 1999, 2000, 2012)


def to_roman(n: int) -> str:
    out = []
    for value, letters in ROMAN:
        while n >= value:
            out.append(letters)
            n -= value
    return "".join(out)


def _near(n: int) -> tuple[int, ...]:
    """Believable wrong answers: numbers a small step away."""
    steps = (1, 2, 4, 5, 9, 10, 11, 40, 50, 90, 100, 400, 500)
    return tuple(sorted({m for s in steps for m in (n - s, n + s) if 0 < m < 4000 and m != n}))


def load_roman() -> list[Question]:
    questions = []
    for n in range(1, 251):
        difficulty = "easy" if n <= 20 else "medium"
        questions.append(Question("roman", "Roman numerals", difficulty, f"How is {n} written in Roman numerals?",
                                  to_roman(n), tuple(to_roman(m) for m in _near(n))))
    for n in [*range(251, 600, 5), *range(600, 4000, 97), *YEARS]:
        questions.append(Question("roman", "Roman numerals", "hard" if n > 400 else "medium",
                                  f"What number is {to_roman(n)} in Roman numerals?", f"{n:,}" if n >= 10_000 else str(n),
                                  tuple(str(m) for m in _near(n))))
    return questions


def build_bank() -> tuple[Question, ...]:
    bank = load_general() + load_countries() + load_us_states() + load_elements() + load_roman()
    seen, unique = set(), []
    for q in bank:  # identical prompts (e.g. a year also in the range) are asked once
        if q.prompt not in seen:
            seen.add(q.prompt)
            unique.append(q)
    return tuple(unique)


BANK: tuple[Question, ...] = build_bank()
BY_TOPIC: dict[str, tuple[Question, ...]] = {t: tuple(q for q in BANK if q.topic == t) for t in TOPICS}
# How often each topic comes up when a player doesn't pick one.
RANDOM_WEIGHTS = {"general": 35, "geography": 25, "flags": 15, "elements": 12.5, "roman": 12.5}


def pick_topic(rng: random.Random | None = None) -> str:
    return (rng or random).choices(list(RANDOM_WEIGHTS), weights=list(RANDOM_WEIGHTS.values()))[0]
