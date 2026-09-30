"""Horse races: the first bet opens a betting window, then everyone watches the race together."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import achievements, config
from kelpbot.gambling import game_allowed, settle
from kelpbot.games import horses

HORSE_CHOICES = [
    app_commands.Choice(name=f"{h.number}. {h.name} ({h.chance:.0%} · pays {h.payout}x)", value=h.number)
    for h in horses.HORSES
]
LONG_SHOT_CHANCE = 0.12
FRAME_SECONDS = 1.2


@dataclass
class Race:
    guild_id: int
    channel_id: int
    closes_at: float
    bets: dict[int, tuple[discord.abc.User, int, int, int]] = field(default_factory=dict)  # uid -> user, horse, bet, id
    message_id: int = 0


class RaceCog(commands.Cog, name="Race"):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.races: dict[int, Race] = {}

    def lobby_embed(self, race: Race) -> discord.Embed:
        cfg = self.bot.cfg(race.guild_id)
        field_lines = "\n".join(f"`{h.number}` **{h.name}**: {h.chance:.0%} to win, pays {h.payout}x"
                                for h in horses.HORSES)
        bets = "\n".join(f"{user.mention} → `{horse}` {cfg.money(bet)}" for user, horse, bet, _ in race.bets.values())
        return discord.Embed(
            title="🏇 Horse race: bets are open!",
            description=f"{field_lines}\n\n**Bets**\n{bets}\n\nPlace yours with `/race`. "
                        f"Race starts <t:{int(race.closes_at)}:R>.",
            color=discord.Color.dark_green(),
        )

    async def _edit(self, race: Race, embed: discord.Embed) -> None:
        try:
            await self.bot.get_partial_messageable(race.channel_id).get_partial_message(race.message_id).edit(
                embed=embed)
        except discord.HTTPException:
            pass

    @app_commands.command(description="Bet on a horse race. The first bet opens betting for everyone.",
                          extras={"manual_cleanup": True})
    @app_commands.choices(horse=HORSE_CHOICES)
    async def race(self, interaction: discord.Interaction, horse: int, bet: app_commands.Range[int, 1]) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        if not await game_allowed(self.bot, interaction, "horse race"):
            return
        cfg = self.bot.cfg(gid)
        current = self.races.get(gid)
        error = None
        if current and uid in current.bets:
            error = "You already have a bet on this race."
        elif current and time.time() >= current.closes_at:
            error = "Betting just closed. Catch the next race!"
        elif bet < cfg.min_bet or (cfg.max_bet and bet > cfg.max_bet):
            limit = cfg.money(cfg.max_bet) if cfg.max_bet else "any amount"
            error = f"Bets must be between {cfg.money(cfg.min_bet)} and {limit}."
        elif not self.bot.db.try_debit(gid, uid, bet):
            error = f"You need {cfg.money(bet)} in your wallet."
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        bet_id = self.bot.db.open_bet(gid, uid, "horse race", bet)
        name = horses.HORSES[horse - 1].name
        if current:
            current.bets[uid] = (interaction.user, horse, bet, bet_id)
            await interaction.response.send_message(
                f"🏇 You bet {cfg.money(bet)} on **{name}**. Good luck!", ephemeral=True
            )
            await self._edit(current, self.lobby_embed(current))
            return

        race = Race(gid, interaction.channel_id, time.time() + config.RACE_BETTING_SECONDS)
        race.bets[uid] = (interaction.user, horse, bet, bet_id)
        self.races[gid] = race
        try:
            await interaction.response.send_message(embed=self.lobby_embed(race))
            race.message_id = (await interaction.original_response()).id
            await asyncio.sleep(max(0.0, race.closes_at - time.time()))
            await self.run(race)
        finally:
            self.races.pop(gid, None)

    async def run(self, race: Race) -> None:
        winner = horses.pick_winner()
        for positions in horses.race_frames(winner):
            await self._edit(race, discord.Embed(title="🏇 And they're off!", description=horses.render_track(positions),
                                                 color=discord.Color.dark_green()))
            await asyncio.sleep(FRAME_SECONDS)

        cfg = self.bot.cfg(race.guild_id)
        lines = []
        for user, horse, bet, bet_id in race.bets.values():
            self.bot.db.close_bet(bet_id)
            won = horse == winner.number
            returned = int(bet * winner.payout) if won else 0
            _, rewards = settle(self.bot, race.guild_id, user.id, bet, returned, "horse race")
            if won and winner.chance <= LONG_SHOT_CHANCE:
                rewards += achievements.unlock(self.bot.db, race.guild_id, user.id, "long_shot")
            result = f"won **{cfg.money(returned)}**" if won else f"lost {cfg.money(bet)}"
            extras = "".join(f" {r.emoji}" for r in rewards)
            lines.append(f"{'✅' if won else '❌'} {user.mention} ({horses.HORSES[horse - 1].name}) {result}{extras}")
        embed = discord.Embed(
            title=f"🏆 {winner.name} wins!",
            description=f"`{winner.number}` **{winner.name}** crossed the line first (paid {winner.payout}x).\n\n"
                        + "\n".join(lines),
            color=discord.Color.gold(),
        )
        await self._edit(race, embed)
        self.bot.schedule_cleanup(race.guild_id, race.channel_id, race.message_id)


async def setup(bot) -> None:
    await bot.add_cog(RaceCog(bot))
