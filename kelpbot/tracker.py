"""Builds the live tracker: overview, leaderboards, today's highlights and recent history."""

from __future__ import annotations

import datetime as dt
import time

import discord

from kelpbot import bank, config, weekly
from kelpbot.achievements import ACHIEVEMENTS
from kelpbot.db import Database, Event
from kelpbot.settings import GuildConfig

MESSAGE_KEY = "_tracker_message_id"
DAY = 24 * 60 * 60
MEDALS = ["🥇", "🥈", "🥉", "`4.`", "`5.`"]
SPARKS = "▁▂▃▄▅▆▇█"
HISTORY_LINES = 8
WEEKDAYS = "MTWTFSS"


def day_start(now: float) -> float:
    """Midnight UTC at the start of the day containing `now`."""
    d = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    return d.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def next_monday(now: float) -> int:
    start = day_start(now)
    weekday = dt.datetime.fromtimestamp(start, dt.timezone.utc).weekday()
    return int(start + (7 - weekday) * DAY)


def sparkline(values: list[int]) -> str:
    top = max(values, default=0)
    if top == 0:
        return SPARKS[0] * len(values)
    return "".join(SPARKS[min(len(SPARKS) - 1, v * (len(SPARKS) - 1) // top)] if v else SPARKS[0] for v in values)


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def signed(cfg: GuildConfig, amount: int) -> str:
    return f"{'+' if amount >= 0 else '-'}{cfg.money(abs(amount))}"


def event_line(cfg: GuildConfig, e: Event) -> str | None:
    when = f"<t:{int(e.ts)}:R>"
    if e.kind == "big_win":
        mult = (e.amount + e.amount2) / e.amount2 if e.amount2 else 0
        text = f"🎉 <@{e.user_id}> won **{cfg.money(e.amount)}** on {e.detail} ({mult:.1f}x)"
    elif e.kind == "rob":
        text = f"🦹 <@{e.user_id}> robbed <@{e.other_id}> of {cfg.money(e.amount)}"
    elif e.kind == "lottery":
        text = f"🎟️ <@{e.user_id}> won the lottery: **{cfg.money(e.amount)}**"
    elif e.kind == "duel":
        text = f"⚔️ <@{e.user_id}> beat <@{e.other_id}> in a {cfg.money(e.amount)} duel"
    elif e.kind == "achievement" and e.detail in ACHIEVEMENTS:
        a = ACHIEVEMENTS[e.detail]
        text = f"{a.emoji} <@{e.user_id}> unlocked **{a.name}**"
    elif e.kind == "weekly":
        text = f"📈 <@{e.user_id}> won the week with {signed(cfg, e.amount)}"
    elif e.kind == "season":
        champ = f"👑 <@{e.user_id}> finished first with {cfg.money(e.amount)}" if e.user_id else "no players"
        text = f"🏁 Season {e.amount2} ended: {champ}"
    elif e.kind == "role":
        text = f"🎭 <@{e.user_id}> bought <@&{e.other_id}>"
    else:
        return None
    return f"{text} · {when}"


def overview_embed(db: Database, guild_id: int, cfg: GuildConfig, now: float, title: str) -> discord.Embed:
    players, supply = db.money_supply(guild_id)
    rnd = db.lottery_round(guild_id)
    if rnd:
        jackpot = rnd.pot * (100 - config.LOTTERY_HOUSE_CUT_PERCENT) // 100
        lottery = f"🎟️ Lottery jackpot **{cfg.money(jackpot)}**, drawn <t:{int(rnd.draw_at)}:R>"
    else:
        lottery = "🎟️ No lottery running. `/lottery buy` starts one"
    lines = [
        f"👥 **{players:,}** players · 💰 **{cfg.money(supply)}** in circulation",
        lottery,
        f"🏁 Season **{weekly.current_season(db, guild_id)}** · weekly prizes <t:{next_monday(now)}:R>",
    ]
    return discord.Embed(title=title, description="\n".join(lines), color=discord.Color.gold())


def leaderboard_embed(db: Database, guild_id: int, cfg: GuildConfig) -> discord.Embed:
    rich = db.leaderboard(guild_id, 5)
    week = [a for a in db.leaderboard(guild_id, 5, by="weekly") if a.weekly_profit > 0]
    e = discord.Embed(title="🏆 Leaderboards", color=discord.Color.gold())
    e.add_field(
        name="💰 Richest",
        value="\n".join(f"{MEDALS[i]} <@{a.user_id}> {cfg.money(a.net_worth)}" for i, a in enumerate(rich))
        or "Nobody yet",
    )
    e.add_field(
        name="📈 This week",
        value="\n".join(f"{MEDALS[i]} <@{a.user_id}> {signed(cfg, a.weekly_profit)}" for i, a in enumerate(week))
        or "No winners yet",
    )
    return e


def today_embed(db: Database, guild_id: int, cfg: GuildConfig, now: float) -> discord.Embed:
    start = day_start(now)
    end = start + DAY
    games, wagered, returned = db.game_totals(guild_id, start, end)
    e = discord.Embed(title="☀️ Today's highlights", color=discord.Color.orange())
    lines = [f"-# Since <t:{int(start)}:t> your time. Resets daily."]
    if games:
        house = wagered - returned
        lines.append(f"🎲 **{plural(games, 'game')}** · {cfg.money(wagered)} wagered · "
                     f"the house is {'up' if house >= 0 else 'down'} {cfg.money(abs(house))}")
        if (g := db.top_game(guild_id, start, end, "profit")):
            lines.append(f"🔥 Biggest win: <@{g.user_id}> **{signed(cfg, g.profit)}** on {g.game}")
        if (g := db.top_game(guild_id, start, end, "multiplier")):
            lines.append(f"🎯 Luckiest hit: <@{g.user_id}> **{g.multiplier:.1f}x** on {g.game}")
        if (g := db.top_game(guild_id, start, end, "loss")):
            lines.append(f"💀 Biggest loss: <@{g.user_id}> lost {cfg.money(g.bet)} on {g.game}")
        if (p := db.top_player(guild_id, start, end, "profit")) and p[1] > 0:
            lines.append(f"📈 Top earner: <@{p[0]}> {signed(cfg, p[1])}")
        if (p := db.top_player(guild_id, start, end, "games")):
            lines.append(f"🏃 Most active: <@{p[0]}> ({plural(p[1], 'game')})")
    else:
        lines.append("No games yet today. Be the first!")
    robs = db.events_between(guild_id, "rob", start, end)
    if robs:
        robberies = "1 robbery" if len(robs) == 1 else f"{len(robs)} robberies"
        lines.append(f"🦹 **{robberies}**, {cfg.money(sum(r.amount for r in robs))} stolen")
    if (p := db.top_player(guild_id, start - DAY, start, "profit")) and p[1] > 0:
        lines.append(f"🌙 Yesterday's top earner: <@{p[0]}> {signed(cfg, p[1])}")
    e.description = "\n".join(lines)
    return e


def history_embed(db: Database, guild_id: int, cfg: GuildConfig, now: float) -> discord.Embed:
    lines = [line for ev in db.recent_events(guild_id, HISTORY_LINES * 2) if (line := event_line(cfg, ev))]
    e = discord.Embed(
        title="📜 Recent history",
        description="\n".join(lines[:HISTORY_LINES]) or "Nothing yet. Big wins, robberies, duels and more show up here.",
        color=discord.Color.blurple(),
    )
    today = day_start(now)
    days = [today - DAY * i for i in range(6, -1, -1)]
    totals = [db.game_totals(guild_id, d, d + DAY) for d in days]
    counts = [t[0] for t in totals]
    labels = "".join(WEEKDAYS[dt.datetime.fromtimestamp(d, dt.timezone.utc).weekday()] for d in days)
    e.add_field(
        name="Last 7 days",
        value=f"`{sparkline(counts)}` {sum(counts):,} games · {cfg.money(sum(t[1] for t in totals))} wagered\n"
              f"-# `{labels}` (games per day, oldest to today)",
        inline=False,
    )
    seasons = db.hall_of_fame(guild_id)
    if seasons:
        last = max(seasons)
        uid, worth = seasons[last][0]
        e.add_field(name="Last season", value=f"👑 Season {last}: <@{uid}> with {cfg.money(worth)}", inline=False)
    return e


def render(db: Database, guild_id: int, cfg: GuildConfig, guild_name: str = "Casino",
           now: float | None = None) -> list[discord.Embed]:
    """All tracker embeds. The last one carries the 'updated' footer."""
    now = time.time() if now is None else now
    bank.accrue_all(db, guild_id, cfg.bank_interest_percent, now)
    embeds = [
        overview_embed(db, guild_id, cfg, now, f"📊 {guild_name} Tracker"),
        leaderboard_embed(db, guild_id, cfg),
        today_embed(db, guild_id, cfg, now),
        history_embed(db, guild_id, cfg, now),
    ]
    embeds[-1].set_footer(text="Updates automatically · last change")
    return embeds


def fingerprint(embeds: list[discord.Embed]) -> int:
    """Changes only when the visible content changes (ignores the timestamp)."""
    return hash(repr([{k: v for k, v in e.to_dict().items() if k != "timestamp"} for e in embeds]))
