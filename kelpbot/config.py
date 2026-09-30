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

# Defaults for per-server settings (admins change them with /settings).
CURRENCY = "🪙"
CURRENCY_NAME = "Coins"
STARTING_BALANCE = 1_000
MIN_BET = 10
MAX_BET = 50_000  # 0 means no limit

DAILY_BASE = 500
DAILY_STREAK_BONUS = 100  # extra per consecutive day
DAILY_STREAK_MAX = 7
DAILY_COOLDOWN = 20 * 60 * 60  # 20h so people can claim at roughly the same time each day
DAILY_STREAK_WINDOW = 48 * 60 * 60  # miss more than this and the streak resets

WORK_COOLDOWN = 60 * 60
WORK_PAY = (100, 300)

BANK_INTEREST_PERCENT = 1  # per day
BANK_INTEREST_CAP = 2_500  # most interest anyone can earn per day

LOTTERY_TICKET_PRICE = 100
LOTTERY_ROUND_SECONDS = 24 * 60 * 60  # draw this long after the first ticket of a round
LOTTERY_MAX_TICKETS = 100  # per player per round
LOTTERY_HOUSE_CUT_PERCENT = 10  # removed from the pot so the lottery drains a little money

WEEKLY_PRIZES = (5_000, 2_500, 1_000)  # top 3 gambling profit each week (resets Monday 00:00 UTC)

BIG_WIN_LOG_THRESHOLD = 10_000  # profits this big get posted to the log channel
GIVE_LOG_THRESHOLD = 1_000

# Tracker history: which wins count as highlights, and how long history is kept.
HISTORY_BIG_WIN_PROFIT = 2_500
HISTORY_BIG_MULTIPLIER = 10.0
HISTORY_BIG_MULTIPLIER_MIN_PROFIT = 500
HISTORY_DAYS = 30  # /give transfers this big get logged (spots alt-account farming)

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

