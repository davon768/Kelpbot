import os

from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "kelpbot.db")
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

CRIME_COOLDOWN = 2 * 60 * 60
CRIME_SUCCESS_CHANCE = 0.55
CRIME_REWARD = (300, 800)
CRIME_FINE = (150, 400)

BEG_COOLDOWN = 5 * 60
BEG_MAX_BALANCE = 100  # only broke players can beg
BEG_PAY = (20, 80)


def money(amount: int) -> str:
    return f"{CURRENCY} {amount:,}"
