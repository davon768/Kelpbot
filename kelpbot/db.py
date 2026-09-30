"""SQLite storage for balances, cooldowns and stats.

discord.py runs everything on one event loop and these calls never await, so each
method runs atomically with respect to other commands.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    guild_id     INTEGER NOT NULL,
    user_id      INTEGER NOT NULL,
    balance      INTEGER NOT NULL,
    daily_streak INTEGER NOT NULL DEFAULT 0,
    total_wagered INTEGER NOT NULL DEFAULT 0,
    total_won    INTEGER NOT NULL DEFAULT 0,
    games_played INTEGER NOT NULL DEFAULT 0,
    biggest_win  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS cooldowns (
    guild_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    action    TEXT NOT NULL,
    last_used REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id, action)
);
CREATE TABLE IF NOT EXISTS inventory (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    item     TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, item)
);
"""


@dataclass
class Account:
    guild_id: int
    user_id: int
    balance: int
    daily_streak: int
    total_wagered: int
    total_won: int
    games_played: int
    biggest_win: int

    @property
    def net(self) -> int:
        return self.total_won - self.total_wagered


class Database:
    def __init__(self, path: str, starting_balance: int) -> None:
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.starting_balance = starting_balance

    def close(self) -> None:
        self.conn.close()

    def _ensure(self, guild_id: int, user_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO accounts (guild_id, user_id, balance) VALUES (?, ?, ?)",
            (guild_id, user_id, self.starting_balance),
        )

    def account(self, guild_id: int, user_id: int) -> Account:
        self._ensure(guild_id, user_id)
        row = self.conn.execute(
            "SELECT * FROM accounts WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ).fetchone()
        return Account(**dict(row))

    def balance(self, guild_id: int, user_id: int) -> int:
        return self.account(guild_id, user_id).balance

    def credit(self, guild_id: int, user_id: int, amount: int) -> int:
        """Add (or, if negative, remove) money, never going below zero. Returns new balance."""
        self._ensure(guild_id, user_id)
        self.conn.execute(
            "UPDATE accounts SET balance = MAX(0, balance + ?) WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, user_id),
        )
        return self.balance(guild_id, user_id)

    def try_debit(self, guild_id: int, user_id: int, amount: int) -> bool:
        """Remove money only if the user can afford it."""
        self._ensure(guild_id, user_id)
        cur = self.conn.execute(
            "UPDATE accounts SET balance = balance - ? "
            "WHERE guild_id = ? AND user_id = ? AND balance >= ?",
            (amount, guild_id, user_id, amount),
        )
        return cur.rowcount == 1

    def transfer(self, guild_id: int, sender: int, recipient: int, amount: int) -> bool:
        self._ensure(guild_id, recipient)
        with self.conn:  # single transaction
            if not self.try_debit(guild_id, sender, amount):
                return False
            self.credit(guild_id, recipient, amount)
        return True

    def record_game(self, guild_id: int, user_id: int, wagered: int, returned: int) -> None:
        self._ensure(guild_id, user_id)
        self.conn.execute(
            "UPDATE accounts SET total_wagered = total_wagered + ?, total_won = total_won + ?, "
            "games_played = games_played + 1, biggest_win = MAX(biggest_win, ?) "
            "WHERE guild_id = ? AND user_id = ?",
            (wagered, returned, returned - wagered, guild_id, user_id),
        )

    def set_streak(self, guild_id: int, user_id: int, streak: int) -> None:
        self._ensure(guild_id, user_id)
        self.conn.execute(
            "UPDATE accounts SET daily_streak = ? WHERE guild_id = ? AND user_id = ?",
            (streak, guild_id, user_id),
        )

    def last_used(self, guild_id: int, user_id: int, action: str) -> float | None:
        row = self.conn.execute(
            "SELECT last_used FROM cooldowns WHERE guild_id = ? AND user_id = ? AND action = ?",
            (guild_id, user_id, action),
        ).fetchone()
        return row["last_used"] if row else None

    def cooldown_remaining(self, guild_id: int, user_id: int, action: str, cooldown: float) -> float:
        last = self.last_used(guild_id, user_id, action)
        if last is None:
            return 0.0
        return max(0.0, last + cooldown - time.time())

    def mark_used(self, guild_id: int, user_id: int, action: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO cooldowns (guild_id, user_id, action, last_used) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, action, time.time()),
        )

    def clear_cooldown(self, guild_id: int, user_id: int, action: str) -> None:
        self.conn.execute(
            "DELETE FROM cooldowns WHERE guild_id = ? AND user_id = ? AND action = ?", (guild_id, user_id, action)
        )

    def leaderboard(self, guild_id: int, limit: int = 10) -> list[Account]:
        rows = self.conn.execute(
            "SELECT * FROM accounts WHERE guild_id = ? ORDER BY balance DESC LIMIT ?",
            (guild_id, limit),
        ).fetchall()
        return [Account(**dict(r)) for r in rows]

    def item_count(self, guild_id: int, user_id: int, item: str) -> int:
        row = self.conn.execute(
            "SELECT quantity FROM inventory WHERE guild_id = ? AND user_id = ? AND item = ?",
            (guild_id, user_id, item),
        ).fetchone()
        return row["quantity"] if row else 0

    def add_item(self, guild_id: int, user_id: int, item: str, quantity: int = 1) -> None:
        self.conn.execute(
            "INSERT INTO inventory (guild_id, user_id, item, quantity) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (guild_id, user_id, item) DO UPDATE SET quantity = quantity + excluded.quantity",
            (guild_id, user_id, item, quantity),
        )

    def remove_item(self, guild_id: int, user_id: int, item: str, quantity: int = 1) -> bool:
        """Take items away only if the user has enough."""
        cur = self.conn.execute(
            "UPDATE inventory SET quantity = quantity - ? "
            "WHERE guild_id = ? AND user_id = ? AND item = ? AND quantity >= ?",
            (quantity, guild_id, user_id, item, quantity),
        )
        self.conn.execute("DELETE FROM inventory WHERE quantity <= 0")
        return cur.rowcount == 1

    def inventory(self, guild_id: int, user_id: int) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT item, quantity FROM inventory WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ).fetchall()
        return {r["item"]: r["quantity"] for r in rows}
