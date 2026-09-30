"""Daily database backups, stored in a backups/ folder next to the database."""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import time

from kelpbot import config
from kelpbot.db import Database


def backup_dir(db_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), "backups")


def make_backup(db: Database, dest: str) -> None:
    """Copy the live database safely (works while the bot is running)."""
    target = sqlite3.connect(dest)
    try:
        db.conn.backup(target)
    finally:
        target.close()


def daily_backup(db: Database, db_path: str, now: float | None = None) -> str | None:
    """Make today's backup if it doesn't exist yet and drop old ones. Returns the new file's path."""
    if db_path == ":memory:":
        return None
    folder = backup_dir(db_path)
    os.makedirs(folder, exist_ok=True)
    day = dt.datetime.fromtimestamp(time.time() if now is None else now, dt.timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(folder, f"kelpbot-{day}.db")
    if os.path.exists(path):
        return None
    make_backup(db, path)
    backups = sorted(f for f in os.listdir(folder) if f.startswith("kelpbot-") and f.endswith(".db"))
    for old in backups[:-config.BACKUP_KEEP_DAYS]:
        os.remove(os.path.join(folder, old))
    return path
