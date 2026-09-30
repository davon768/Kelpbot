"""Weekly gambling-profit leaderboard with prizes, and end-of-season resets."""

from __future__ import annotations

import datetime as dt

from kelpbot import config
from kelpbot.db import Database

WEEK_KEY = "_weekly_key"
SEASON_KEY = "_season"


def week_key(now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def roll_week(db: Database, guild_id: int, current_key: str) -> list[tuple[int, int, int]] | None:
    """If a new week started, pay the top 3 of last week and reset.

    Returns [(user_id, profit, prize), ...] when a week was closed, otherwise None.
    """
    stored = db.config(guild_id).get(WEEK_KEY)
    if stored == current_key:
        return None
    winners: list[tuple[int, int, int]] = []
    with db.transaction():
        if stored is not None:  # first time we see this server: just start tracking
            top = [a for a in db.leaderboard(guild_id, len(config.WEEKLY_PRIZES), by="weekly") if a.weekly_profit > 0]
            for acct, prize in zip(top, config.WEEKLY_PRIZES):
                db.credit(guild_id, acct.user_id, prize)
                winners.append((acct.user_id, acct.weekly_profit, prize))
            db.reset_weekly(guild_id)
        db.set_config(guild_id, WEEK_KEY, current_key)
    return winners if stored is not None else None


def current_season(db: Database, guild_id: int) -> int:
    return int(db.config(guild_id).get(SEASON_KEY, 1))


def end_season(db: Database, guild_id: int) -> tuple[int, list[tuple[int, int]]]:
    """Record the top 3 by net worth, wipe the economy, and start the next season."""
    season = current_season(db, guild_id)
    top = [(a.user_id, a.net_worth) for a in db.leaderboard(guild_id, 3)]
    with db.transaction():
        db.add_hall_of_fame(guild_id, season, top)
        db.reset_economy(guild_id)
        db.set_config(guild_id, SEASON_KEY, season + 1)
    return season, top
