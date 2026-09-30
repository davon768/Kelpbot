"""Per-server settings. Each server can override the defaults in config.py."""

from __future__ import annotations

from dataclasses import dataclass, fields

from kelpbot import config
from kelpbot.db import Database


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    kind: type  # int, bool or str
    default: object
    help: str
    min: int = 0
    max: int = 1_000_000_000


SETTINGS: dict[str, Setting] = {s.key: s for s in (
    Setting("currency_name", "Currency name", str, config.CURRENCY_NAME, "What the money is called, e.g. Shells"),
    Setting("currency_emoji", "Currency emoji", str, config.CURRENCY, "Shown next to amounts, e.g. 🐚"),
    Setting("starting_balance", "Starting balance", int, config.STARTING_BALANCE, "Money new players start with"),
    Setting("daily_base", "Daily reward", int, config.DAILY_BASE, "Base /daily payout"),
    Setting("daily_streak_bonus", "Daily streak bonus", int, config.DAILY_STREAK_BONUS, "Extra /daily pay per streak day"),
    Setting("work_min", "Work pay (min)", int, config.WORK_PAY[0], "Lowest /work payout"),
    Setting("work_max", "Work pay (max)", int, config.WORK_PAY[1], "Highest /work payout"),
    Setting("min_bet", "Minimum bet", int, config.MIN_BET, "Smallest bet allowed", min=1),
    Setting("max_bet", "Maximum bet", int, config.MAX_BET, "Largest bet allowed (0 = no limit)"),
    Setting("rob_enabled", "Robbing", bool, True, "Whether /rob is allowed"),
    Setting("bank_interest_percent", "Bank interest %", int, config.BANK_INTEREST_PERCENT,
            "Daily interest on bank savings", max=10),
    Setting("lottery_ticket_price", "Lottery ticket price", int, config.LOTTERY_TICKET_PRICE,
            "Cost of one lottery ticket", min=1),
    Setting("auto_delete_seconds", "Auto-delete delay", int, config.AUTO_DELETE_DEFAULT_SECONDS,
            "Seconds before bot replies delete themselves (0 = off)", max=config.AUTO_DELETE_MAX_SECONDS),
    Setting("min_account_age_days", "Min account age (days)", int, config.MIN_ACCOUNT_AGE_DAYS,
            "Younger Discord accounts can't /give or be robbed (0 = off)", max=365),
    Setting("min_server_days", "Min days in server", int, config.MIN_SERVER_DAYS,
            "Newer members can't /give or be robbed (0 = off)", max=365),
)}

# Games admins can switch off with /settings game.
GAMES = ("slots", "blackjack", "coinflip", "roulette", "dice", "crash", "mines", "higher or lower",
         "duel", "heist", "horse race", "lottery", "stocks")
DISABLED_GAMES_KEY = "disabled_games"

# Stored in the same table but set through /settings channel, not /settings set.
CHANNEL_SETTINGS = {
    "log_channel_id": "Log channel (big wins, robberies, admin actions)",
    "announce_channel_id": "Announcement channel (lottery draws, weekly winners, seasons)",
    "tracker_channel_id": "Tracker channel (live leaderboards, highlights and history)",
}

TRUE_WORDS = {"on", "true", "yes", "y", "1", "enable", "enabled"}
FALSE_WORDS = {"off", "false", "no", "n", "0", "disable", "disabled"}


@dataclass(frozen=True)
class GuildConfig:
    currency_name: str
    currency_emoji: str
    starting_balance: int
    daily_base: int
    daily_streak_bonus: int
    work_min: int
    work_max: int
    min_bet: int
    max_bet: int
    rob_enabled: bool
    bank_interest_percent: int
    lottery_ticket_price: int
    auto_delete_seconds: int
    log_channel_id: int
    announce_channel_id: int
    tracker_channel_id: int
    min_account_age_days: int
    min_server_days: int
    disabled_games: frozenset[str]

    def money(self, amount: int) -> str:
        return f"{self.currency_emoji} {amount:,}"

    @property
    def work_range(self) -> tuple[int, int]:
        return min(self.work_min, self.work_max), max(self.work_min, self.work_max)


def _decode(setting: Setting, raw: str) -> object:
    if setting.kind is bool:
        return raw == "1"
    return setting.kind(raw)


def _encode(setting: Setting, value: object) -> str:
    if setting.kind is bool:
        return "1" if value else "0"
    return str(value)


def load(db: Database, guild_id: int) -> GuildConfig:
    raw = db.config(guild_id)
    values: dict[str, object] = {}
    for f in fields(GuildConfig):
        if f.name == DISABLED_GAMES_KEY:
            values[f.name] = frozenset(g for g in raw.get(f.name, "").split(",") if g)
        elif f.name in SETTINGS:
            s = SETTINGS[f.name]
            values[f.name] = _decode(s, raw[f.name]) if f.name in raw else s.default
        else:  # channel ids
            values[f.name] = int(raw.get(f.name, 0))
    return GuildConfig(**values)


def parse(setting: Setting, text: str) -> object:
    """Turn what an admin typed into a value, or raise ValueError with a friendly message."""
    text = text.strip()
    if setting.kind is bool:
        if text.lower() in TRUE_WORDS:
            return True
        if text.lower() in FALSE_WORDS:
            return False
        raise ValueError("Use `on` or `off`.")
    if setting.kind is int:
        try:
            value = int(text.replace(",", "").replace("_", ""))
        except ValueError:
            raise ValueError("That needs to be a whole number.") from None
        if not setting.min <= value <= setting.max:
            raise ValueError(f"Must be between {setting.min:,} and {setting.max:,}.")
        return value
    if not text:
        raise ValueError("Can't be empty.")
    limit = 24 if setting.key == "currency_name" else 64  # custom emoji look like <:name:id>
    if len(text) > limit:
        raise ValueError(f"Keep it under {limit} characters.")
    return text


def save(db: Database, guild_id: int, key: str, value: object | None) -> None:
    """Store a setting, or reset it to the default when value is None."""
    db.set_config(guild_id, key, None if value is None else _encode(SETTINGS[key], value))


def display(setting: Setting, value: object) -> str:
    if setting.kind is bool:
        return "on" if value else "off"
    if setting.kind is int:
        if setting.key == "max_bet" and value == 0:
            return "no limit"
        if setting.key == "auto_delete_seconds" and value == 0:
            return "off"
        return f"{value:,}"
    return str(value)


def set_game_enabled(db: Database, guild_id: int, game: str, enabled: bool) -> None:
    disabled = set(load(db, guild_id).disabled_games)
    (disabled.discard if enabled else disabled.add)(game)
    db.set_config(guild_id, DISABLED_GAMES_KEY, ",".join(sorted(disabled)) or None)
