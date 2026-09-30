"""Bonuses from items and pets, looked up wherever they apply."""

from __future__ import annotations

from kelpbot import config
from kelpbot.db import Database
from kelpbot.shop import CAT, DOG, LAPTOP, OCTOPUS, PARROT, PETS, TURTLE

LAPTOP_WORK_MULTIPLIER = 1.5
CAT_WORK_MULTIPLIER = 1.1
PARROT_DAILY_MULTIPLIER = 1.1
DOG_ROB_DEFENSE = 0.15
TURTLE_INTEREST_BONUS = 1
OCTOPUS_COOLDOWN_CUT = 15 * 60


def has(db: Database, guild_id: int, user_id: int, item_key: str) -> bool:
    return db.item_count(guild_id, user_id, item_key) > 0


def work_multiplier(db: Database, guild_id: int, user_id: int) -> float:
    m = 1.0
    if has(db, guild_id, user_id, LAPTOP.key):
        m *= LAPTOP_WORK_MULTIPLIER
    if has(db, guild_id, user_id, CAT.key):
        m *= CAT_WORK_MULTIPLIER
    return m


def work_cooldown(db: Database, guild_id: int, user_id: int) -> int:
    cut = OCTOPUS_COOLDOWN_CUT if has(db, guild_id, user_id, OCTOPUS.key) else 0
    return config.WORK_COOLDOWN - cut


def daily_multiplier(db: Database, guild_id: int, user_id: int) -> float:
    return PARROT_DAILY_MULTIPLIER if has(db, guild_id, user_id, PARROT.key) else 1.0


def rob_defense(db: Database, guild_id: int, user_id: int) -> float:
    return DOG_ROB_DEFENSE if has(db, guild_id, user_id, DOG.key) else 0.0


def interest_bonus(db: Database, guild_id: int, user_id: int) -> int:
    return TURTLE_INTEREST_BONUS if has(db, guild_id, user_id, TURTLE.key) else 0


def pets(db: Database, guild_id: int, user_id: int) -> list:
    owned = db.inventory(guild_id, user_id)
    return [p for p in PETS if owned.get(p.key)]
