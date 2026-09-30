"""Achievements: one-time goals that pay a reward the first time they're reached."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from kelpbot.db import Database


@dataclass(frozen=True)
class Achievement:
    key: str
    name: str
    emoji: str
    description: str
    reward: int
    badge: ClassVar[str] = "🏅 Achievement"


ACHIEVEMENTS: dict[str, Achievement] = {a.key: a for a in (
    Achievement("first_win", "Beginner's Luck", "🍀", "Win your first game", 250),
    Achievement("high_roller", "High Roller", "💸", "Place a bet of 10,000 or more", 1_000),
    Achievement("jackpot", "Jackpot!", "7️⃣", "Hit 7️⃣7️⃣7️⃣ on the slots", 5_000),
    Achievement("natural", "Natural", "🃏", "Get dealt a blackjack", 500),
    Achievement("to_the_moon", "To The Moon", "🚀", "Cash out of crash at 10x or higher", 2_500),
    Achievement("minesweeper", "Minesweeper", "💣", "Clear every safe tile in mines", 5_000),
    Achievement("card_counter", "Card Counter", "🔮", "Guess right 5 times in a row in higher or lower", 1_500),
    Achievement("duelist", "Duelist", "⚔️", "Win a duel", 500),
    Achievement("lottery_winner", "Lucky Ticket", "🎟️", "Win the lottery", 1_000),
    Achievement("master_thief", "Master Thief", "🦹", "Pull off 10 successful robberies", 2_000),
    Achievement("dedicated", "Dedicated", "📅", "Reach a 7 day /daily streak", 2_000),
    Achievement("shopaholic", "Shopaholic", "🛍️", "Buy 10 items from the shop", 1_000),
    Achievement("saver", "Saver", "🏦", "Have 10,000 in the bank", 500),
    Achievement("millionaire", "Millionaire", "💎", "Reach a net worth of 1,000,000", 10_000),
    Achievement("champion", "Season Champion", "👑", "Finish a season in first place", 0),
    Achievement("getaway", "Clean Getaway", "💰", "Pull off a successful heist", 1_000),
    Achievement("long_shot", "Long Shot", "🐎", "Win a horse race betting on a 12% or lower horse", 2_000),
    Achievement("tycoon", "Kelp Tycoon", "🏭", "Reach the top job", 5_000),
    Achievement("wolf", "Wolf of Kelp Street", "📈", "Make 10,000 profit selling stock in one trade", 2_500),
    Achievement("zookeeper", "Zookeeper", "🦁", "Own every pet at once", 5_000),
)}

# counter name -> (goal, achievement unlocked when the counter reaches it)
COUNTER_GOALS = {
    "rob_success": (10, "master_thief"),
    "items_bought": (10, "shopaholic"),
}

HIGH_ROLLER_BET = 10_000
SAVER_BANK = 10_000
MILLIONAIRE_NET_WORTH = 1_000_000


def unlock(db: Database, guild_id: int, user_id: int, key: str) -> list[Achievement]:
    """Unlock and pay out an achievement. Returns it in a list if it's new, else an empty list."""
    if not db.add_achievement(guild_id, user_id, key):
        return []
    achievement = ACHIEVEMENTS[key]
    db.add_event(guild_id, "achievement", user_id, achievement.reward, detail=key)
    if achievement.reward:
        db.credit(guild_id, user_id, achievement.reward)
    return [achievement]


def bump(db: Database, guild_id: int, user_id: int, counter: str, amount: int = 1) -> list[Achievement]:
    value = db.bump_counter(guild_id, user_id, counter, amount)
    goal, key = COUNTER_GOALS[counter]
    return unlock(db, guild_id, user_id, key) if value >= goal else []


def check_wealth(db: Database, guild_id: int, user_id: int) -> list[Achievement]:
    acct = db.account(guild_id, user_id)
    unlocked = []
    if acct.bank >= SAVER_BANK:
        unlocked += unlock(db, guild_id, user_id, "saver")
    if acct.net_worth >= MILLIONAIRE_NET_WORTH:
        unlocked += unlock(db, guild_id, user_id, "millionaire")
    return unlocked


def after_game(db: Database, guild_id: int, user_id: int, bet: int, returned: int) -> list[Achievement]:
    """Checks shared by every game."""
    unlocked = []
    if returned > bet:
        unlocked += unlock(db, guild_id, user_id, "first_win")
    if bet >= HIGH_ROLLER_BET:
        unlocked += unlock(db, guild_id, user_id, "high_roller")
    return unlocked + check_wealth(db, guild_id, user_id)
