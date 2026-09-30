import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")
# Railway sets RAILWAY_VOLUME_MOUNT_PATH when a volume is attached; keep the database there
# so balances survive redeploys.
_VOLUME = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
DATABASE_PATH = os.getenv("DATABASE_PATH") or (os.path.join(_VOLUME, "kelpbot.db") if _VOLUME else "kelpbot.db")
ON_RAILWAY = any(key.startswith("RAILWAY_") for key in os.environ)
# If set, slash commands sync instantly to this server (handy while developing).
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0")) or None

CURRENCY = "🪙"
STARTING_BALANCE = 1_000
MIN_BET = 10

DAILY_BASE = 500
DAILY_STREAK_BONUS = 100  # extra per consecutive day
DAILY_STREAK_MAX = 7
DAILY_COOLDOWN = 20 * 60 * 60  # 20h so people can claim at roughly the same time each day
DAILY_STREAK_WINDOW = 48 * 60 * 60  # miss more than this and the streak resets

WORK_COOLDOWN = 60 * 60
WORK_PAY = (100, 300)

ROB_COOLDOWN = 2 * 60 * 60
ROB_SUCCESS_CHANCE = 0.5
ROB_STEAL_PERCENT = (10, 30)  # share of the victim's wallet taken on success
ROB_FINE = (150, 400)  # paid to the victim if you get caught
ROB_MIN_BALANCE = 200  # robber needs this much so there's something to lose
ROB_MIN_TARGET_BALANCE = 200  # don't bother robbing broke players
ROB_VICTIM_PROTECTION = 60 * 60  # can't be robbed again this soon after a successful robbery

BEG_COOLDOWN = 5 * 60
BEG_MAX_BALANCE = 100  # only broke players can beg
BEG_PAY = (20, 80)

# Public bot replies delete themselves after this many seconds (0 = keep forever).
# Servers can override this with /autoclean.
AUTO_DELETE_DEFAULT_SECONDS = 120
AUTO_DELETE_MAX_SECONDS = 24 * 60 * 60


def money(amount: int) -> str:
    return f"{CURRENCY} {amount:,}"
