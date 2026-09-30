"""Alt-account protection: brand-new accounts can't send money or be robbed."""

from __future__ import annotations

import datetime as dt

from kelpbot.settings import GuildConfig


def trust_problem(member, cfg: GuildConfig, now: dt.datetime | None = None) -> str | None:
    """Why this member is too new, or None if they're fine."""
    now = now or dt.datetime.now(dt.timezone.utc)
    account_days = (now - member.created_at).days
    if cfg.min_account_age_days and account_days < cfg.min_account_age_days:
        return f"Discord accounts must be at least {cfg.min_account_age_days} days old"
    joined = getattr(member, "joined_at", None)
    if cfg.min_server_days and joined is not None and (now - joined).days < cfg.min_server_days:
        days = "1 day" if cfg.min_server_days == 1 else f"{cfg.min_server_days} days"
        return f"members must have been in this server for at least {days}"
    return None
