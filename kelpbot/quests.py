"""Daily quests: three random goals per player per (UTC) day, paid automatically when done."""

from __future__ import annotations

import datetime as dt
import random
import time
from dataclasses import dataclass

from kelpbot import config
from kelpbot.db import Database
from kelpbot.rewards import Reward


@dataclass(frozen=True)
class Quest:
    key: str
    name: str
    emoji: str
    description: str
    event: str  # what counts toward it (see on_game and the progress() callers)
    goal: int
    reward: int


POOL: tuple[Quest, ...] = (
    Quest("play_10", "Regular", "🎲", "Play 10 games", "game", 10, 500),
    Quest("win_5", "On a Roll", "🏆", "Win 5 games", "win", 5, 750),
    Quest("wager_5k", "Big Spender", "💸", "Wager 5,000 in total", "wager", 5_000, 600),
    Quest("mult_5x", "Lucky Break", "🎯", "Win 5x or more in a single game", "multiplier5", 1, 800),
    Quest("blackjack_3", "Card Shark", "🃏", "Play 3 hands of blackjack", "game:blackjack", 3, 400),
    Quest("slots_10", "Reel Deal", "🎰", "Spin the slots 10 times", "game:slots", 10, 400),
    Quest("crash_3", "Rocket Rider", "🚀", "Play 3 rounds of crash", "game:crash", 3, 400),
    Quest("mines_3", "Sweeper", "💣", "Play 3 rounds of mines", "game:mines", 3, 400),
    Quest("highlow_3", "Fortune Teller", "🔮", "Play 3 rounds of higher or lower", "game:higher or lower", 3, 400),
    Quest("roulette_5", "Round and Round", "🎡", "Spin roulette 5 times", "game:roulette", 5, 400),
    Quest("dice_5", "Dice Roller", "🎲", "Roll the dice 5 times", "game:dice", 5, 400),
    Quest("work_2", "Hard Worker", "💼", "Work 2 shifts", "work", 2, 300),
    Quest("rob_1", "Sticky Fingers", "🦹", "Pull off a robbery", "rob", 1, 500),
    Quest("deposit_1k", "Rainy Day Fund", "🏦", "Deposit 1,000 in the bank", "deposit", 1_000, 300),
    Quest("lottery_3", "Feeling Lucky", "🎟️", "Buy 3 lottery tickets", "lottery", 3, 300),
    Quest("duel_1", "Challenger", "⚔️", "Fight a duel", "game:duel", 1, 400),
    Quest("heist_1", "Crew Up", "💰", "Join a heist", "game:heist", 1, 500),
    Quest("race_1", "Day at the Races", "🐎", "Bet on a horse race", "game:horse race", 1, 400),
    Quest("stocks_1", "Investor", "📈", "Buy some stock", "stock_buy", 1, 300),
    Quest("trivia_3", "Smarty Pants", "🧠", "Answer 3 trivia questions correctly", "trivia", 3, 400),
)
QUESTS = {q.key: q for q in POOL}


def day_key(now: float | None = None) -> str:
    return dt.datetime.fromtimestamp(time.time() if now is None else now, dt.timezone.utc).strftime("%Y%m%d")


def todays_quests(guild_id: int, user_id: int, day: str) -> list[Quest]:
    """The same three quests all day for a player, different for each player and day."""
    return random.Random(f"{guild_id}:{user_id}:{day}").sample(POOL, config.QUESTS_PER_DAY)


def _key(day: str, quest: Quest) -> str:
    return f"q:{day}:{quest.key}"


def status(db: Database, guild_id: int, user_id: int, now: float | None = None) -> list[tuple[Quest, int, bool]]:
    """(quest, progress, done) for today's quests."""
    day = day_key(now)
    return [
        (q, min(db.counter(guild_id, user_id, _key(day, q)), q.goal), bool(db.counter(guild_id, user_id, _key(day, q) + ":done")))
        for q in todays_quests(guild_id, user_id, day)
    ]


def progress(db: Database, guild_id: int, user_id: int, event: str, amount: int = 1,
             now: float | None = None) -> list[Reward]:
    """Count something the player did toward today's quests; pays and returns any that just finished."""
    day = day_key(now)
    quests = todays_quests(guild_id, user_id, day)
    done: list[Reward] = []
    for q in quests:
        if q.event != event or db.counter(guild_id, user_id, _key(day, q) + ":done"):
            continue
        if db.bump_counter(guild_id, user_id, _key(day, q), amount) >= q.goal:
            db.bump_counter(guild_id, user_id, _key(day, q) + ":done")
            db.credit(guild_id, user_id, q.reward)
            done.append(Reward("📋 Daily quest", q.emoji, q.name, q.description, q.reward))
    if done and not db.counter(guild_id, user_id, f"q:{day}:bonus"):
        if all(db.counter(guild_id, user_id, _key(day, q) + ":done") for q in quests):
            db.bump_counter(guild_id, user_id, f"q:{day}:bonus")
            db.credit(guild_id, user_id, config.QUEST_ALL_DONE_BONUS)
            done.append(Reward("📋 Daily quest", "🌟", "All Done!", "Finished all of today's quests",
                               config.QUEST_ALL_DONE_BONUS))
    return done


def on_game(db: Database, guild_id: int, user_id: int, game: str, bet: int, returned: int,
            now: float | None = None) -> list[Reward]:
    done = progress(db, guild_id, user_id, "game", 1, now)
    done += progress(db, guild_id, user_id, f"game:{game}", 1, now)
    done += progress(db, guild_id, user_id, "wager", bet, now)
    if returned > bet:
        done += progress(db, guild_id, user_id, "win", 1, now)
    if bet and returned >= 5 * bet:
        done += progress(db, guild_id, user_id, "multiplier5", 1, now)
    return done
