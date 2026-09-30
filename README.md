# Kelpbot 🎰

A Discord casino bot with **fake money**. Players earn coins through daily rewards,
work, robbing each other and begging, then gamble them on slots, blackjack, roulette and coinflips, or spend them in the shop.
Balances are per-server and stored in a local SQLite file.

## Commands

### Earning money
| Command | What it does |
| --- | --- |
| `/daily` | 500 coins, +100 per consecutive day (streak caps at 7 days). Claimable every 20h; the streak resets if you skip more than 48h. |
| `/work` | Earn 100–300 coins. Once per hour. |
| `/rob @user` | 50% chance to steal 10–30% of another player's wallet. If you get caught, you pay *them* a 150–400 fine. Once every 2 hours. You need at least 200 to try, the target needs at least 200, and someone who was just robbed is safe for an hour. |
| `/beg` | 20–80 coins, only if you have 100 or less. Every 5 minutes. |
| `/give @user amount` | Send coins to another player. |

### Games (minimum bet 10)
| Command | Payout |
| --- | --- |
| `/slots bet` | 3 reels, up to 500x for 7️⃣7️⃣7️⃣ (about 88% return to player) |
| `/blackjack bet` | Interactive Hit / Stand / Double buttons. Win 2x, blackjack 2.5x, push returns the bet. |
| `/coinflip bet heads\|tails` | 2x |
| `/roulette bet choice` | red/black/odd/even/low/high 2x, dozens 3x, single number 36x |
| `/paytable` | Shows all payouts |

### Shop
| Command | What it does |
| --- | --- |
| `/shop` | List items and prices |
| `/buy item [quantity]` / `/sell item [quantity]` | Buy an item, or sell it back for half price |
| `/use item` | Use an item such as the Energy Drink |
| `/inventory [@user]` | See what someone owns |

| Item | Price | Effect |
| --- | --- | --- |
| 🔒 Padlock | 800 | Blocks the next `/rob` against you, then breaks (hold up to 3) |
| 🪓 Crowbar | 600 | +25% success chance on your next `/rob` (hold up to 5) |
| 🥤 Energy Drink | 250 | `/use` it to reset your `/work` cooldown |
| 💻 Laptop | 7,500 | Permanently +50% `/work` pay |
| 🏆 Golden Trophy, 🏎️ Sports Car, 🛥️ Kelp Yacht | 25k / 100k / 500k | Collectibles for showing off |

Items are defined in [`kelpbot/shop.py`](kelpbot/shop.py). Add a new `Item(...)` there to put it in the shop.

### Info
`/balance [@user]`, `/stats [@user]`, `/leaderboard`

### Admin
`/addmoney @user amount`: add money, or remove it with a negative amount. Only people with the **Manage Server** permission can see it.

## Setup

1. **Create the bot.** Go to <https://discord.com/developers/applications>, click
   **New Application**, open the **Bot** tab and click **Reset Token**. Copy the token.
2. **Invite it.** Under **OAuth2 → URL Generator**, tick the `bot` and
   `applications.commands` scopes and the **Send Messages** and **Embed Links**
   permissions, then open the generated URL and pick your server.
3. **Install and run** (Python 3.10+):
   ```bash
   python -m venv .venv
   source .venv/bin/activate        # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env             # then paste your token into .env
   python bot.py
   ```

   Set `DEV_GUILD_ID` in `.env` to your server's ID while testing. Commands then
   show up right away instead of taking up to an hour. To get the ID, turn on
   Developer Mode in Discord's settings, then right-click the server and choose **Copy Server ID**.

## Tweaking the economy

All the numbers (starting balance, cooldowns, pay ranges, minimum bet, streak bonus)
are in [`kelpbot/config.py`](kelpbot/config.py). Slot symbols, weights and payouts are
in [`kelpbot/games/slots.py`](kelpbot/games/slots.py). The tests check that slots still
favour the house after you change them.

## Project layout

```
bot.py                  entry point
kelpbot/config.py       settings and economy numbers
kelpbot/db.py           SQLite balances, cooldowns, stats
kelpbot/cogs/economy.py earning and info commands
kelpbot/cogs/casino.py  game commands and the blackjack buttons
kelpbot/games/          game rules with no Discord code (unit tested)
tests/                  run with `pip install pytest && pytest`
```
