"""Timed server-wide events an admin can start, like double pay or a lucky hour."""

from __future__ import annotations

import time
from dataclasses import dataclass

from kelpbot import config
from kelpbot.db import Database

TYPE_KEY = "_event_type"
ENDS_KEY = "_event_ends"


@dataclass(frozen=True)
class ServerEvent:
    key: str
    name: str
    emoji: str
    description: str


EVENTS: dict[str, ServerEvent] = {e.key: e for e in (
    ServerEvent("double_pay", "Double Pay", "💼", "/work and /daily pay double"),
    ServerEvent("lucky_hour", "Lucky Hour", "🍀",
                f"Every winning game pays {config.LUCKY_HOUR_BONUS_PERCENT}% extra"),
    ServerEvent("xp_boost", "XP Boost", "⭐", "Double job XP from /work"),
)}


def active(db: Database, guild_id: int, now: float | None = None) -> tuple[ServerEvent, float] | None:
    """The running event and when it ends, or None."""
    raw = db.config(guild_id)
    key, ends = raw.get(TYPE_KEY), float(raw.get(ENDS_KEY, 0))
    now = time.time() if now is None else now
    if key in EVENTS and ends > now:
        return EVENTS[key], ends
    return None


def is_active(db: Database, guild_id: int, key: str, now: float | None = None) -> bool:
    current = active(db, guild_id, now)
    return current is not None and current[0].key == key


def start(db: Database, guild_id: int, key: str, minutes: int, now: float | None = None) -> float:
    ends = (time.time() if now is None else now) + minutes * 60
    db.set_config(guild_id, TYPE_KEY, key)
    db.set_config(guild_id, ENDS_KEY, ends)
    return ends


def stop(db: Database, guild_id: int) -> ServerEvent | None:
    key = db.config(guild_id).get(TYPE_KEY)
    db.set_config(guild_id, TYPE_KEY, None)
    db.set_config(guild_id, ENDS_KEY, None)
    return EVENTS.get(key)


def expired(db: Database, now: float | None = None) -> list[tuple[int, ServerEvent]]:
    """Events whose time is up (still stored, so the end can be announced once)."""
    now = time.time() if now is None else now
    out = []
    for guild_id, key in db.config_values(TYPE_KEY):
        ends = float(db.config(guild_id).get(ENDS_KEY, 0))
        if ends <= now and key in EVENTS:
            out.append((guild_id, EVENTS[key]))
    return out
