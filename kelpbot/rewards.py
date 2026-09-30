"""Something a player just earned, shown in the follow-up "rewards" message."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reward:
    badge: str  # e.g. "📋 Daily quest"
    emoji: str
    name: str
    description: str
    reward: int = 0  # already paid by whoever created this
