"""Bank savings: safe from robbers and earning daily interest."""

from __future__ import annotations

import time

from kelpbot import config, perks
from kelpbot.db import Database

DAY = 24 * 60 * 60


def accrue(db: Database, guild_id: int, user_id: int, rate_percent: int, now: float | None = None) -> int:
    """Pay interest for every full day since the last payout. Returns the interest added."""
    now = time.time() if now is None else now
    acct = db.account(guild_id, user_id)
    if acct.bank_interest_at == 0:
        db.set_bank(guild_id, user_id, acct.bank, now)
        return 0
    days = int((now - acct.bank_interest_at) // DAY)
    if days <= 0:
        return 0
    bank = acct.bank
    rate_percent += perks.interest_bonus(db, guild_id, user_id)
    for _ in range(min(days, 365)):
        bank += min(config.BANK_INTEREST_CAP, bank * rate_percent // 100)
    db.set_bank(guild_id, user_id, bank, acct.bank_interest_at + days * DAY)
    return bank - acct.bank


def accrue_all(db: Database, guild_id: int, rate_percent: int, now: float | None = None) -> None:
    for acct in db.accounts(guild_id):
        if acct.bank:
            accrue(db, guild_id, acct.user_id, rate_percent, now)


def deposit(db: Database, guild_id: int, user_id: int, amount: int, rate_percent: int) -> bool:
    accrue(db, guild_id, user_id, rate_percent)
    with db.transaction():
        if amount <= 0 or not db.try_debit(guild_id, user_id, amount):
            return False
        acct = db.account(guild_id, user_id)
        db.set_bank(guild_id, user_id, acct.bank + amount, acct.bank_interest_at)
    return True


def withdraw(db: Database, guild_id: int, user_id: int, amount: int, rate_percent: int) -> bool:
    accrue(db, guild_id, user_id, rate_percent)
    acct = db.account(guild_id, user_id)
    if amount <= 0 or amount > acct.bank:
        return False
    with db.transaction():
        db.set_bank(guild_id, user_id, acct.bank - amount, acct.bank_interest_at)
        db.credit(guild_id, user_id, amount)
    return True


def parse_amount(text: str, available: int) -> int | None:
    """Accepts a number, 'all' or 'half' (commas allowed)."""
    text = text.strip().lower().replace(",", "")
    if text in ("all", "max"):
        return available
    if text == "half":
        return available // 2
    try:
        value = int(text)
    except ValueError:
        return None
    return value if value > 0 else None
