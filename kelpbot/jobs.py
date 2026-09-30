"""Jobs and levels: /work earns XP, and higher levels unlock better-paying jobs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    level: int
    name: str
    emoji: str
    multiplier: float
    shifts: tuple[str, ...]  # "You {shift} and earned ..."


JOBS: tuple[Job, ...] = (
    Job(1, "Kelp Farmer", "🌿", 1.0, ("harvested a row of kelp", "untangled the kelp nets", "sold kelp at the market")),
    Job(3, "Fisher", "🎣", 1.2, ("reeled in a big catch", "fixed your fishing nets", "sold fish at the docks")),
    Job(5, "Lifeguard", "🛟", 1.4, ("saved a swimmer", "watched the beach all day", "taught a swim class")),
    Job(8, "Marine Biologist", "🔬", 1.7, ("tagged a sea turtle", "published a paper on urchins", "counted fish")),
    Job(12, "Ship Captain", "⚓", 2.0, ("sailed a cargo run", "steered through a storm", "ran a harbor tour")),
    Job(18, "Casino Manager", "🎰", 2.5, ("ran the high-roller tables", "kicked out a card counter", "balanced the vault")),
    Job(25, "Kelp Tycoon", "🏭", 3.0, ("bought a rival kelp farm", "rang the stock market bell", "hosted a gala")),
)
TOP_JOB = JOBS[-1]


def xp_for_level(level: int) -> int:
    """Total XP needed to reach a level (level 1 needs none)."""
    return 25 * level * (level - 1)


def level_for(xp: int) -> int:
    level = 1
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


def job_for(level: int) -> Job:
    return [j for j in JOBS if j.level <= level][-1]


def next_job(level: int) -> Job | None:
    return next((j for j in JOBS if j.level > level), None)


def progress_bar(xp: int, width: int = 10) -> str:
    level = level_for(xp)
    start, end = xp_for_level(level), xp_for_level(level + 1)
    filled = int(width * (xp - start) / (end - start))
    return "▰" * filled + "▱" * (width - filled)
