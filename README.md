# Kelpbot 🎰

A Discord casino bot with **fake money**. Players earn coins through daily rewards, jobs,
daily quests, robbing each other and begging. They save coins in the bank, trade stocks,
gamble on over a dozen games (some played together), and spend them on items, pets and roles.
Every server has its own separate economy, and admins can tune it with `/settings`.
Everything is stored in a local SQLite file. New here? `/help` lists every command.

**Website:** <https://davon768.github.io/Kelpbot/> (the page lives in [`docs/index.html`](docs/index.html)).

The numbers below are the defaults. Server admins can change the ones marked ⚙️ with `/settings`.

## Commands

### Earning and saving
| Command | What it does |
| --- | --- |
| `/daily` | ⚙️ 500 coins, +100 per consecutive day (streak caps at 7 days). Claimable every 20h; the streak resets if you skip more than 48h. |
| `/work` | ⚙️ Earn 100–300 coins times your job's multiplier, plus XP. Once per hour. |
| `/job` | Your job and level. XP from `/work` unlocks better jobs: Kelp Farmer (1x) → Fisher (level 3, 1.2x) → Lifeguard (5, 1.4x) → Marine Biologist (8, 1.7x) → Ship Captain (12, 2x) → Casino Manager (18, 2.5x) → Kelp Tycoon (25, 3x). |
| `/quests` | Three random daily quests (like "play 3 hands of blackjack" or "deposit 1,000"). Each pays 300–800 when done, plus 1,000 for finishing all three. New quests every day at 00:00 UTC. |
| `/rob @user` | ⚙️ 50% chance to steal 10–30% of another player's **wallet**. If you get caught, you pay *them* a 150–400 fine. Once every 2 hours. You need at least 200 to try, the target needs at least 200, and someone who was just robbed is safe for an hour. Admins can turn robbing off. |
| `/beg` | 20–80 coins, only if your wallet + bank is 100 or less. Every 5 minutes. |
| `/give @user amount` | Send coins to another player. |
| `/deposit amount` / `/withdraw amount` | Move money between wallet and bank. Accepts a number, `half` or `all`. Banked money **can't be robbed** and earns ⚙️ 1% interest per day (at most 2,500/day). You gamble from your wallet. |

### Games
Bets must be between the server's ⚙️ minimum (10) and maximum (50,000) bet.

| Command | How it works |
| --- | --- |
| `/games` | Every game in one list. Pick one from the menu, enter your bet in the pop-up, and it starts, no typing needed. |
| `/slots bet` | 3 reels, up to 500x for 7️⃣7️⃣7️⃣ (about 88% return to player) |
| `/blackjack bet` | Hit / Stand / Double buttons. Win 2x, blackjack 2.5x, push returns the bet. |
| `/coinflip bet heads\|tails` | 2x |
| `/roulette bet choice` | red/black/odd/even/low/high 2x, dozens 3x, single number 36x |
| `/dice bet [chance]` | Roll 1–100; win if you roll at or under your chance. 50% pays 1.96x, 10% pays 9.8x. |
| `/crash bet [auto_cashout]` | A multiplier climbs until it crashes. Hit **Cash Out** in time, or set an automatic cash-out. Goes up to 100x. |
| `/mines bet [mines]` | 20 tiles with 1–15 hidden mines. Each gem raises your multiplier; a mine loses everything. |
| `/highlow bet` | Guess whether the next card is higher or lower (ties lose). Each right guess grows your multiplier. |
| `/duel @user bet` | Challenge another player. You both put up the bet and the winner takes both. |
| `/heist bet` | Start a heist; others join with the same buy-in for 60s (up to 10). A crew of 2 has a 50% chance and each gets 1.9x back; bigger crews are safer (up to 80%) but split the loot more ways. |
| `/race horse bet` | The first bet opens a 45s betting window for everyone, then the race plays out live. Five horses from 35% (2.7x) to 8% (11.8x). |
| `/lottery buy [tickets]` / `/lottery info` | ⚙️ 100 per ticket, up to 100 tickets each. The draw happens 24h after the first ticket of a round; the winner gets 90% of the pot. |
| `/paytable` | Shows all payouts |

In crash, mines and higher or lower, walking away cashes you out with whatever you've won so far.
If the bot restarts in the middle of any game, heist, race or pending duel, the bet is refunded when it comes back.

### Shop
| Command | What it does |
| --- | --- |
| `/shop` | List items, roles and prices |
| `/buy item [quantity]` / `/sell item [quantity]` | Buy an item, or sell it back for half price |
| `/use item` | Use an item such as the Energy Drink |
| `/inventory [@user]` | See what someone owns |
| `/buyrole role` | Buy a role an admin has put up for sale |

| Item | Price | Effect |
| --- | --- | --- |
| 🔒 Padlock | 800 | Blocks the next `/rob` against you, then breaks (hold up to 3) |
| 🪓 Crowbar | 600 | +25% success chance on your next `/rob` (hold up to 5) |
| 🥤 Energy Drink | 250 | `/use` it to reset your `/work` cooldown |
| 💻 Laptop | 7,500 | Permanently +50% `/work` pay |
| 🐱 Cat | 5,000 | Pet: +10% `/work` pay |
| 🦜 Parrot | 6,000 | Pet: +10% `/daily` |
| 🐶 Guard Dog | 8,000 | Pet: robberies against you are 15% less likely to succeed |
| 🐢 Turtle | 12,000 | Pet: +1% daily bank interest |
| 🐙 Octopus | 20,000 | Pet: `/work` cooldown 15 minutes shorter |
| 🐉 Dragon | 250,000 | Pet: no perk, pure glory |
| 🏆 Golden Trophy, 🏎️ Sports Car, 🛥️ Kelp Yacht | 25k / 100k / 500k | Collectibles for showing off |

Items are defined in [`kelpbot/shop.py`](kelpbot/shop.py). Add a new `Item(...)` there to put it in the shop.

### Stock market
| Command | What it does |
| --- | --- |
| `/stocks market` | Prices, 24h change and a price chart for KELP, SHEL, PRL and CRAB (CRAB is the wild one) |
| `/stocks buy stock shares` / `/stocks sell stock shares` | Trade shares from your wallet. Each trade has a 1% fee. |
| `/stocks portfolio [@user]` | Your shares, their value and your profit or loss |

Prices move every hour and drift back toward their starting price over time. Hourly moves of 10% or more show up in the tracker.

### Progress and bragging rights
| Command | What it does |
| --- | --- |
| `/help` | Every command, grouped by category |
| `/profile [@user]` | Profile card: net worth and rank, wallet, bank, stocks, job and level, win rate and favourite game (last 30 days), streak, pets and achievement badges |
| `/balance [@user]` | Wallet, bank and net worth |
| `/leaderboard [wealth\|weekly]` | Richest players, or this week's biggest gambling profits. Every Monday at 00:00 UTC the weekly top 3 win 5,000 / 2,500 / 1,000 and the board resets. |
| `/achievements [@user]` | 20 achievements, like hitting the jackpot, clearing a mines board, pulling off a heist or owning every pet. Most pay a one-time reward. |
| `/halloffame` | Top 3 of every past season |
| `/stats [@user]` | Games played, wagered, profit, biggest win |

### Facts
| Command | What it does |
| --- | --- |
| `/funfact` | Posts a fun fact in the channel, from a list of 529 across 16 topics (animals, space, history, kelp and more) |
| `/notsofunfact` | Posts a fact that's sad 😢, dark 💀 or completely uninteresting 😐, from a list of 301 |

Each server works through each list in its own shuffled order, so no fact repeats until every one has been shown; then it reshuffles. Facts stay in the channel (they're not auto-deleted), and there's a 10-second cooldown per person. To add facts, put new lines in [`kelpbot/data/fun_facts.txt`](kelpbot/data/fun_facts.txt) or [`kelpbot/data/not_fun_facts.txt`](kelpbot/data/not_fun_facts.txt).

### Admin
| Command | What it does |
| --- | --- |
| `/settings view` | Show this server's economy settings |
| `/settings set setting value` | Change currency name/emoji, starting balance, daily and work pay, min/max bet, robbing on/off, bank interest, lottery ticket price, auto-delete delay, or the alt-account limits below |
| `/settings game game on/off` | Turn any game off (or back on) in this server: slots, blackjack, coinflip, roulette, dice, crash, mines, higher or lower, duel, heist, horse race, lottery or stocks |
| `/settings reset setting` | Put a setting back to its default |
| `/settings channel log\|announce\|tracker [#channel]` | **Log channel:** a private feed of big wins, robberies, large transfers and admin actions. **Announce channel:** where lottery draws, weekly winners and season results go. If no announce channel is set, they go wherever the bot was last used. **Tracker channel:** a live tracker message (see below). |
| `/event start event [minutes]` / `/event stop` | Run a timed event (5 minutes to 24 hours): 💼 **Double Pay** (`/work` and `/daily` pay double), 🍀 **Lucky Hour** (every win pays 10% extra) or ⭐ **XP Boost** (double job XP). It's announced when it starts and ends, and shown on the tracker. |
| `/shoprole add role price` / `/shoprole remove role` | Sell roles in the shop. Roles with moderator permissions are refused, and the bot's own role must be above the role it sells. |
| `/addmoney @user amount` | Add money, or remove it with a negative amount |
| `/reseteconomy [@user]` | Wipe everyone's (or one player's) money, items and progress. Settings, shop roles and achievements are kept. Asks for confirmation. |
| `/endseason` | Save the top 3 to `/halloffame`, give first place the Season Champion achievement, and reset the economy for a fresh season. Asks for confirmation. |
| `/autoclean [seconds]` | Shortcut for the auto-delete delay |
| `/cleanup [scan]` | Delete the bot's messages from the last `scan` messages in this channel (default 100). Handy after a restart, since pending auto-deletes don't survive one. |
| `/backup` | **Bot owner only:** download a copy of the whole database. Other admins are refused, because the file holds every server's data. |

**Alt-account protection:** by default, Discord accounts younger than ⚙️ 7 days, or members who joined
less than ⚙️ 1 day ago, can't use `/give` and can't be robbed. That stops someone farming `/daily` and `/work`
on throwaway accounts and funnelling the money to their main. Set either limit to 0 to turn it off.

`/settings`, `/event`, `/addmoney`, `/reseteconomy`, `/endseason` and `/autoclean` need **Manage Server**. `/shoprole` needs **Manage Roles** and `/cleanup` needs **Manage Messages**. You can change who sees them under Server Settings → Integrations → Kelpbot.

## Live tracker

`/settings channel tracker #casino-stats` posts one message that the bot keeps up to date and never auto-deletes:

- **Overview:** players, money in circulation, the lottery jackpot and draw time, the season, and when weekly prizes pay out
- **Leaderboards:** top 5 richest and top 5 this week
- **Today's highlights** (UTC day): games played, total wagered, whether the house is up or down, biggest win, luckiest multiplier, biggest loss, top earner, most active player, robberies, and yesterday's top earner
- **Recent history:** the last 8 big wins (2,500+ profit, or 10x+ with 500+ profit), robberies, duels, heists, job promotions, big stock moves, lottery wins, achievements, weekly winners, seasons and role purchases; a 7-day activity chart; and last season's champion
- Any running server event is shown at the top

It's edited in place at most once a minute, and only when something changed. If it gets buried under
10+ messages, it moves back to the bottom once the channel has been quiet for 2 minutes. If someone
deletes it, it comes back within a minute. `/cleanup` never touches it. Run the command again to
re-post it, or leave the channel empty to remove it. A dedicated channel works best. History older than 30 days is
trimmed automatically.

## Keeping channels tidy

- Public replies delete themselves after 2 minutes. Blackjack, crash, mines, higher or lower and duels stay until the game is over, then start their own timer.
- Errors, "you're on cooldown" notices and `/paytable` are only visible to the person who used the command, so they never clutter the channel.
- To keep the casino in one place, go to Server Settings → Integrations → Kelpbot and allow its commands only in a `#casino` channel.
- If the bot has **Manage Messages**, `/cleanup` deletes in bulk. Without it, `/cleanup` still works, just slower.

## Setup

1. **Create the bot.** Go to <https://discord.com/developers/applications>, click
   **New Application**, open the **Bot** tab and click **Reset Token**. Copy the token.
2. **Invite it.** Under **OAuth2 → URL Generator**, tick the `bot` and
   `applications.commands` scopes and the **View Channels**, **Send Messages**, **Embed Links**,
   **Read Message History**, **Manage Messages** and **Manage Roles** permissions, then open the
   generated URL and pick your server. (Manage Roles is only needed for `/buyrole`.)
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

## Hosting on Railway

The repo includes `railway.json` (start command and auto-restart) and `.python-version`, so Railway builds it without extra setup.

1. On <https://railway.com>, create a project with **Deploy from GitHub repo** and pick this repo.
2. In the service's **Variables**, add `DISCORD_TOKEN` (and optionally `DEV_GUILD_ID`).
3. **Attach a volume** to the service (mount path `/data`). The bot stores its database
   there automatically. Without a volume, every redeploy wipes all balances, and the logs
   will warn you.
4. Keep the service at **1 replica**. Two copies would answer every command twice.

Pushing to the deployed branch redeploys automatically. Balances survive because they live on the volume.

## Backups

Once a day, the bot copies its database to a `backups/` folder next to the database file (on Railway, that's `/data/backups`) and keeps the last 7 days.
Those copies live on the same volume, so to keep a copy somewhere else, the bot's owner can run `/backup` to download one.
To restore, stop the bot, replace `kelpbot.db` with a backup file, and start it again.

## Tweaking the economy

Server admins change most numbers with `/settings`. The defaults for those, plus everything
else (cooldowns, robbery odds, weekly prizes, lottery rules, bank interest cap), are in
[`kelpbot/config.py`](kelpbot/config.py). Achievements are in
[`kelpbot/achievements.py`](kelpbot/achievements.py). Slot symbols, weights and payouts are in
[`kelpbot/games/slots.py`](kelpbot/games/slots.py). The tests check that every game still
favours the house after you change it.

## Project layout

```
bot.py                     entry point, shared helpers (settings, logging, announcements)
kelpbot/config.py          defaults and fixed numbers
kelpbot/settings.py        per-server settings
kelpbot/db.py              SQLite storage (upgrades older databases automatically)
kelpbot/gambling.py        bet limits, payouts and button views shared by every game
kelpbot/bank.py            deposits, withdrawals and interest
kelpbot/achievements.py    achievement list and unlock rules
kelpbot/lottery.py         ticket sales and draws
kelpbot/weekly.py          weekly prizes and seasons
kelpbot/jobs.py            jobs and levels
kelpbot/quests.py          daily quests
kelpbot/perks.py           item and pet bonuses
kelpbot/stocks.py          stock prices and trading
kelpbot/server_events.py   timed events (double pay, lucky hour, XP boost)
kelpbot/trust.py           alt-account protection
kelpbot/backup.py          daily database backups
kelpbot/tracker.py         builds the tracker's leaderboards, highlights and history
kelpbot/robbery.py         /rob rules
kelpbot/shop.py            shop items
kelpbot/games/             game rules with no Discord code
kelpbot/cogs/              the slash commands:
  economy.py               earning, bank, leaderboards, achievements
  casino.py                slots, blackjack, coinflip, roulette, dice
  arcade.py                crash, mines, higher or lower
  duels.py                 player-vs-player duels
  heist.py                 group heists
  race.py                  horse races
  stocks.py                /stocks commands
  profile.py               /profile, /job, /quests
  help.py                  /help
  lottery.py               lottery commands
  scheduler.py             lottery draws, weekly payouts, stock prices, event endings,
                           backups and history trimming (runs every minute)
  tracker.py               the live tracker message
  shop.py                  items and roles
  admin.py                 settings, events, resets, seasons, shop roles, backups
  cleanup.py               auto-delete and /cleanup
tests/                     run with `pip install pytest && pytest`
```
