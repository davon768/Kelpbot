"""SQLite storage for balances, cooldowns, items, settings and everything else.

discord.py runs everything on one event loop and these calls never await, so each
method runs atomically with respect to other commands.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
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
    bank         INTEGER NOT NULL DEFAULT 0,
    bank_interest_at REAL NOT NULL DEFAULT 0,
    weekly_profit INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS cooldowns (
    guild_id  INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    action    TEXT NOT NULL,
    last_used REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id, action)
);
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    TEXT NOT NULL,
    PRIMARY KEY (guild_id, key)
);
CREATE TABLE IF NOT EXISTS inventory (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    item     TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, item)
);
CREATE TABLE IF NOT EXISTS counters (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    key      TEXT NOT NULL,
    value    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id, key)
);
CREATE TABLE IF NOT EXISTS achievements (
    guild_id    INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    key         TEXT NOT NULL,
    unlocked_at REAL NOT NULL,
    PRIMARY KEY (guild_id, user_id, key)
);
CREATE TABLE IF NOT EXISTS lottery_rounds (
    guild_id   INTEGER PRIMARY KEY,
    draw_at    REAL NOT NULL,
    channel_id INTEGER NOT NULL,
    pot        INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS lottery_tickets (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    tickets  INTEGER NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE IF NOT EXISTS shop_roles (
    guild_id INTEGER NOT NULL,
    role_id  INTEGER NOT NULL,
    price    INTEGER NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);
CREATE TABLE IF NOT EXISTS game_log (
    guild_id INTEGER NOT NULL,
    user_id  INTEGER NOT NULL,
    ts       REAL NOT NULL,
    game     TEXT NOT NULL,
    bet      INTEGER NOT NULL,
    returned INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS game_log_guild_ts ON game_log (guild_id, ts);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    ts       REAL NOT NULL,
    kind     TEXT NOT NULL,
    user_id  INTEGER NOT NULL DEFAULT 0,
    other_id INTEGER NOT NULL DEFAULT 0,
    amount   INTEGER NOT NULL DEFAULT 0,
    amount2  INTEGER NOT NULL DEFAULT 0,
    detail   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_guild_ts ON events (guild_id, ts);
CREATE TABLE IF NOT EXISTS hall_of_fame (
    guild_id  INTEGER NOT NULL,
    season    INTEGER NOT NULL,
    place     INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    net_worth INTEGER NOT NULL,
    ended_at  REAL NOT NULL,
    PRIMARY KEY (guild_id, season, place)
);
"""

# Columns added after the first release, so older databases get upgraded in place.
ACCOUNT_MIGRATIONS = {
    "bank": "INTEGER NOT NULL DEFAULT 0",
    "bank_interest_at": "REAL NOT NULL DEFAULT 0",
    "weekly_profit": "INTEGER NOT NULL DEFAULT 0",
}

# Tables that make up a server's economy (wiped by a reset). Settings, shop roles,
# achievements and the hall of fame are deliberately kept.
ECONOMY_TABLES = ("accounts", "cooldowns", "inventory", "counters", "lottery_tickets")


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
    bank: int
    bank_interest_at: float
    weekly_profit: int

    @property
    def net(self) -> int:
        return self.total_won - self.total_wagered

    @property
    def net_worth(self) -> int:
        return self.balance + self.bank


@dataclass
class Event:
    id: int
    guild_id: int
    ts: float
    kind: str
    user_id: int
    other_id: int
    amount: int
    amount2: int
    detail: str


@dataclass
class GameRow:
    user_id: int
    game: str
    bet: int
    returned: int

    @property
    def profit(self) -> int:
        return self.returned - self.bet

    @property
    def multiplier(self) -> float:
        return self.returned / self.bet if self.bet else 0.0


@dataclass
class LotteryRound:
    guild_id: int
    draw_at: float
    channel_id: int
    pot: int


class Database:
    def __init__(self, path: str, starting_balance: int, auto_delete_default: int = 0) -> None:
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()
        # Fallbacks used when a server hasn't changed the matching setting.
        self.starting_balance = starting_balance
        self.auto_delete_default = auto_delete_default
        self._config_cache: dict[int, dict[str, str]] = {}

    def _migrate(self) -> None:
        existing = {r["name"] for r in self.conn.execute("PRAGMA table_info(accounts)")}
        for column, ddl in ACCOUNT_MIGRATIONS.items():
            if column not in existing:
                self.conn.execute(f"ALTER TABLE accounts ADD COLUMN {column} {ddl}")
        # The first version kept auto-delete in its own table.
        old = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'guild_settings'"
        ).fetchone()
        if old:
            self.conn.execute(
                "INSERT OR IGNORE INTO guild_config (guild_id, key, value) "
                "SELECT guild_id, 'auto_delete_seconds', auto_delete_seconds FROM guild_settings "
                "WHERE auto_delete_seconds IS NOT NULL"
            )
            self.conn.execute("DROP TABLE guild_settings")

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self):
        """Group several writes so they all happen or none do."""
        if self.conn.in_transaction:
            yield
            return
        self.conn.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # ---- server config ----------------------------------------------------------

    def config(self, guild_id: int) -> dict[str, str]:
        """Raw stored overrides for a server (settings and internal state)."""
        if guild_id not in self._config_cache:
            rows = self.conn.execute("SELECT key, value FROM guild_config WHERE guild_id = ?", (guild_id,))
            self._config_cache[guild_id] = {r["key"]: r["value"] for r in rows}
        return self._config_cache[guild_id]

    def set_config(self, guild_id: int, key: str, value: str | int | None) -> None:
        """Store an override, or remove it (back to default) when value is None."""
        if value is None:
            self.conn.execute("DELETE FROM guild_config WHERE guild_id = ? AND key = ?", (guild_id, key))
        else:
            self.conn.execute(
                "INSERT INTO guild_config (guild_id, key, value) VALUES (?, ?, ?) "
                "ON CONFLICT (guild_id, key) DO UPDATE SET value = excluded.value",
                (guild_id, key, str(value)),
            )
        self._config_cache.pop(guild_id, None)

    def _config_int(self, guild_id: int, key: str, default: int) -> int:
        raw = self.config(guild_id).get(key)
        return int(raw) if raw is not None else default

    def auto_delete_seconds(self, guild_id: int) -> int:
        return self._config_int(guild_id, "auto_delete_seconds", self.auto_delete_default)

    def set_auto_delete_seconds(self, guild_id: int, seconds: int) -> None:
        self.set_config(guild_id, "auto_delete_seconds", seconds)

    # ---- accounts ------------------------------------------------------------------

    def _ensure(self, guild_id: int, user_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO accounts (guild_id, user_id, balance) VALUES (?, ?, ?)",
            (guild_id, user_id, self._config_int(guild_id, "starting_balance", self.starting_balance)),
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
        """Add (or, if negative, remove) wallet money, never going below zero. Returns new balance."""
        self._ensure(guild_id, user_id)
        self.conn.execute(
            "UPDATE accounts SET balance = MAX(0, balance + ?) WHERE guild_id = ? AND user_id = ?",
            (amount, guild_id, user_id),
        )
        return self.balance(guild_id, user_id)

    def try_debit(self, guild_id: int, user_id: int, amount: int) -> bool:
        """Remove wallet money only if the user can afford it."""
        self._ensure(guild_id, user_id)
        cur = self.conn.execute(
            "UPDATE accounts SET balance = balance - ? "
            "WHERE guild_id = ? AND user_id = ? AND balance >= ?",
            (amount, guild_id, user_id, amount),
        )
        return cur.rowcount == 1

    def transfer(self, guild_id: int, sender: int, recipient: int, amount: int) -> bool:
        self._ensure(guild_id, recipient)
        with self.transaction():
            if not self.try_debit(guild_id, sender, amount):
                return False
            self.credit(guild_id, recipient, amount)
        return True

    def record_game(self, guild_id: int, user_id: int, wagered: int, returned: int) -> None:
        self._ensure(guild_id, user_id)
        self.conn.execute(
            "UPDATE accounts SET total_wagered = total_wagered + ?, total_won = total_won + ?, "
            "games_played = games_played + 1, biggest_win = MAX(biggest_win, ?), "
            "weekly_profit = weekly_profit + ? "
            "WHERE guild_id = ? AND user_id = ?",
            (wagered, returned, returned - wagered, returned - wagered, guild_id, user_id),
        )

    def set_streak(self, guild_id: int, user_id: int, streak: int) -> None:
        self._ensure(guild_id, user_id)
        self.conn.execute(
            "UPDATE accounts SET daily_streak = ? WHERE guild_id = ? AND user_id = ?",
            (streak, guild_id, user_id),
        )

    def set_bank(self, guild_id: int, user_id: int, bank: int, interest_at: float) -> None:
        self._ensure(guild_id, user_id)
        self.conn.execute(
            "UPDATE accounts SET bank = ?, bank_interest_at = ? WHERE guild_id = ? AND user_id = ?",
            (bank, interest_at, guild_id, user_id),
        )

    def accounts(self, guild_id: int) -> list[Account]:
        rows = self.conn.execute("SELECT * FROM accounts WHERE guild_id = ?", (guild_id,)).fetchall()
        return [Account(**dict(r)) for r in rows]

    def leaderboard(self, guild_id: int, limit: int = 10, by: str = "wealth") -> list[Account]:
        if by == "weekly":
            order, where = "weekly_profit DESC", "AND weekly_profit != 0"
        else:
            order, where = "balance + bank DESC", ""
        rows = self.conn.execute(
            f"SELECT * FROM accounts WHERE guild_id = ? {where} ORDER BY {order} LIMIT ?",
            (guild_id, limit),
        ).fetchall()
        return [Account(**dict(r)) for r in rows]

    def reset_weekly(self, guild_id: int) -> None:
        self.conn.execute("UPDATE accounts SET weekly_profit = 0 WHERE guild_id = ?", (guild_id,))

    def guild_ids(self) -> list[int]:
        rows = self.conn.execute(
            "SELECT DISTINCT guild_id FROM accounts UNION SELECT DISTINCT guild_id FROM guild_config"
        )
        return [r[0] for r in rows]

    def reset_economy(self, guild_id: int, user_id: int | None = None) -> None:
        """Wipe money, items, cooldowns and progress for a whole server or one player."""
        with self.transaction():
            for table in ECONOMY_TABLES:
                if user_id is None:
                    self.conn.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
                else:
                    self.conn.execute(f"DELETE FROM {table} WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
            if user_id is None:
                self.conn.execute("DELETE FROM lottery_rounds WHERE guild_id = ?", (guild_id,))

    # ---- cooldowns -----------------------------------------------------------------

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

    # ---- inventory -----------------------------------------------------------------

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

    # ---- counters & achievements ---------------------------------------------------------

    def bump_counter(self, guild_id: int, user_id: int, key: str, amount: int = 1) -> int:
        self.conn.execute(
            "INSERT INTO counters (guild_id, user_id, key, value) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (guild_id, user_id, key) DO UPDATE SET value = value + excluded.value",
            (guild_id, user_id, key, amount),
        )
        return self.counter(guild_id, user_id, key)

    def counter(self, guild_id: int, user_id: int, key: str) -> int:
        row = self.conn.execute(
            "SELECT value FROM counters WHERE guild_id = ? AND user_id = ? AND key = ?", (guild_id, user_id, key)
        ).fetchone()
        return row["value"] if row else 0

    def add_achievement(self, guild_id: int, user_id: int, key: str) -> bool:
        """Returns True only the first time."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO achievements (guild_id, user_id, key, unlocked_at) VALUES (?, ?, ?, ?)",
            (guild_id, user_id, key, time.time()),
        )
        return cur.rowcount == 1

    def achievements(self, guild_id: int, user_id: int) -> set[str]:
        rows = self.conn.execute(
            "SELECT key FROM achievements WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        return {r["key"] for r in rows}

    # ---- lottery -------------------------------------------------------------------

    def lottery_round(self, guild_id: int) -> LotteryRound | None:
        row = self.conn.execute("SELECT * FROM lottery_rounds WHERE guild_id = ?", (guild_id,)).fetchone()
        return LotteryRound(**dict(row)) if row else None

    def start_lottery_round(self, guild_id: int, draw_at: float, channel_id: int) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO lottery_rounds (guild_id, draw_at, channel_id, pot) VALUES (?, ?, ?, 0)",
            (guild_id, draw_at, channel_id),
        )

    def add_lottery_tickets(self, guild_id: int, user_id: int, tickets: int, cost: int) -> None:
        self.conn.execute(
            "INSERT INTO lottery_tickets (guild_id, user_id, tickets) VALUES (?, ?, ?) "
            "ON CONFLICT (guild_id, user_id) DO UPDATE SET tickets = tickets + excluded.tickets",
            (guild_id, user_id, tickets),
        )
        self.conn.execute("UPDATE lottery_rounds SET pot = pot + ? WHERE guild_id = ?", (cost, guild_id))

    def lottery_tickets(self, guild_id: int) -> dict[int, int]:
        rows = self.conn.execute("SELECT user_id, tickets FROM lottery_tickets WHERE guild_id = ?", (guild_id,))
        return {r["user_id"]: r["tickets"] for r in rows}

    def end_lottery_round(self, guild_id: int) -> None:
        self.conn.execute("DELETE FROM lottery_rounds WHERE guild_id = ?", (guild_id,))
        self.conn.execute("DELETE FROM lottery_tickets WHERE guild_id = ?", (guild_id,))

    def due_lottery_rounds(self, now: float) -> list[LotteryRound]:
        rows = self.conn.execute("SELECT * FROM lottery_rounds WHERE draw_at <= ?", (now,)).fetchall()
        return [LotteryRound(**dict(r)) for r in rows]

    # ---- shop roles ------------------------------------------------------------------

    def shop_roles(self, guild_id: int) -> dict[int, int]:
        rows = self.conn.execute(
            "SELECT role_id, price FROM shop_roles WHERE guild_id = ? ORDER BY price", (guild_id,)
        )
        return {r["role_id"]: r["price"] for r in rows}

    def set_shop_role(self, guild_id: int, role_id: int, price: int | None) -> None:
        if price is None:
            self.conn.execute("DELETE FROM shop_roles WHERE guild_id = ? AND role_id = ?", (guild_id, role_id))
        else:
            self.conn.execute(
                "INSERT INTO shop_roles (guild_id, role_id, price) VALUES (?, ?, ?) "
                "ON CONFLICT (guild_id, role_id) DO UPDATE SET price = excluded.price",
                (guild_id, role_id, price),
            )

    # ---- hall of fame ------------------------------------------------------------------

    def add_hall_of_fame(self, guild_id: int, season: int, entries: list[tuple[int, int]]) -> None:
        now = time.time()
        self.conn.executemany(
            "INSERT OR REPLACE INTO hall_of_fame (guild_id, season, place, user_id, net_worth, ended_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(guild_id, season, place, uid, worth, now) for place, (uid, worth) in enumerate(entries, 1)],
        )

    def hall_of_fame(self, guild_id: int) -> dict[int, list[tuple[int, int]]]:
        rows = self.conn.execute(
            "SELECT season, user_id, net_worth FROM hall_of_fame WHERE guild_id = ? ORDER BY season DESC, place",
            (guild_id,),
        )
        seasons: dict[int, list[tuple[int, int]]] = {}
        for r in rows:
            seasons.setdefault(r["season"], []).append((r["user_id"], r["net_worth"]))
        return seasons

    def config_values(self, key: str) -> list[tuple[int, str]]:
        """(guild_id, value) for every server that has set this key."""
        rows = self.conn.execute("SELECT guild_id, value FROM guild_config WHERE key = ?", (key,))
        return [(r["guild_id"], r["value"]) for r in rows]

    # ---- history (for the tracker) ---------------------------------------------------

    def log_game(self, guild_id: int, user_id: int, game: str, bet: int, returned: int,
                 ts: float | None = None) -> None:
        self.conn.execute(
            "INSERT INTO game_log (guild_id, user_id, ts, game, bet, returned) VALUES (?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, time.time() if ts is None else ts, game, bet, returned),
        )

    def add_event(self, guild_id: int, kind: str, user_id: int = 0, amount: int = 0, *, other_id: int = 0,
                  amount2: int = 0, detail: str = "", ts: float | None = None) -> None:
        self.conn.execute(
            "INSERT INTO events (guild_id, ts, kind, user_id, other_id, amount, amount2, detail) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (guild_id, time.time() if ts is None else ts, kind, user_id, other_id, amount, amount2, detail),
        )

    def recent_events(self, guild_id: int, limit: int = 10) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE guild_id = ? ORDER BY ts DESC, id DESC LIMIT ?", (guild_id, limit)
        ).fetchall()
        return [Event(**dict(r)) for r in rows]

    def events_between(self, guild_id: int, kind: str, start: float, end: float) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE guild_id = ? AND kind = ? AND ts >= ? AND ts < ?",
            (guild_id, kind, start, end),
        ).fetchall()
        return [Event(**dict(r)) for r in rows]

    def game_totals(self, guild_id: int, start: float, end: float) -> tuple[int, int, int]:
        """(games played, total wagered, total paid back) in a time range."""
        row = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(bet), 0), COALESCE(SUM(returned), 0) FROM game_log "
            "WHERE guild_id = ? AND ts >= ? AND ts < ?",
            (guild_id, start, end),
        ).fetchone()
        return row[0], row[1], row[2]

    def top_game(self, guild_id: int, start: float, end: float, by: str) -> GameRow | None:
        """The single most notable game in a range: by 'profit', 'multiplier' or 'loss'."""
        order, where = {
            "profit": ("returned - bet DESC", "returned > bet"),
            "multiplier": ("CAST(returned AS REAL) / bet DESC", "returned > bet"),
            "loss": ("bet DESC", "returned = 0"),
        }[by]
        row = self.conn.execute(
            f"SELECT user_id, game, bet, returned FROM game_log WHERE guild_id = ? AND ts >= ? AND ts < ? "
            f"AND {where} ORDER BY {order}, ts LIMIT 1",
            (guild_id, start, end),
        ).fetchone()
        return GameRow(**dict(row)) if row else None

    def top_player(self, guild_id: int, start: float, end: float, by: str) -> tuple[int, int] | None:
        """(user_id, value) of the player with the most 'profit' or 'games' in a range."""
        expr = {"profit": "SUM(returned - bet)", "games": "COUNT(*)"}[by]
        row = self.conn.execute(
            f"SELECT user_id, {expr} AS value FROM game_log WHERE guild_id = ? AND ts >= ? AND ts < ? "
            f"GROUP BY user_id ORDER BY value DESC LIMIT 1",
            (guild_id, start, end),
        ).fetchone()
        return (row["user_id"], row["value"]) if row else None

    def money_supply(self, guild_id: int) -> tuple[int, int]:
        """(number of players, total money in wallets and banks)."""
        row = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(balance + bank), 0) FROM accounts WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        return row[0], row[1]

    def prune_history(self, before: float) -> None:
        self.conn.execute("DELETE FROM game_log WHERE ts < ?", (before,))
        self.conn.execute("DELETE FROM events WHERE ts < ?", (before,))
