"""The games you bet on."""

from __future__ import annotations

import asyncio
import random
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import config
from kelpbot.config import money
from kelpbot.games import roulette as roulette_game
from kelpbot.games import slots as slot_machine
from kelpbot.games.blackjack import BlackjackGame, Outcome, format_hand, hand_value

Bet = app_commands.Range[int, config.MIN_BET]

WIN_COLOR = discord.Color.green()
LOSE_COLOR = discord.Color.red()
NEUTRAL_COLOR = discord.Color.light_grey()


def result_line(bet: int, returned: int) -> tuple[str, discord.Color]:
    if returned > bet:
        return f"🎉 You won **{money(returned - bet)}**!", WIN_COLOR
    if returned == bet:
        return "🤝 You got your bet back.", NEUTRAL_COLOR
    return f"💀 You lost **{money(bet)}**.", LOSE_COLOR


class BlackjackView(discord.ui.View):
    def __init__(self, cog: "Casino", interaction: discord.Interaction, game: BlackjackGame) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = interaction.guild_id
        self.player = interaction.user
        self.game = game
        self.message: discord.InteractionMessage | None = None
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        self.double.disabled = not self.game.can_double
        if self.game.finished:
            for child in self.children:
                child.disabled = True

    def embed(self) -> discord.Embed:
        g = self.game
        done = g.finished
        if done:
            text, color = result_line(g.bet, g.payout())
            title = f"🃏 Blackjack — {g.outcome.value}"
        else:
            text, color, title = "Hit, stand, or double down?", discord.Color.dark_green(), "🃏 Blackjack"
        dealer_value = hand_value(g.dealer) if done else "?"
        e = discord.Embed(title=title, description=text, color=color)
        e.add_field(name=f"Dealer ({dealer_value})", value=format_hand(g.dealer, hide_hole=not done), inline=False)
        e.add_field(name=f"{self.player.display_name} ({hand_value(g.player)})", value=format_hand(g.player), inline=False)
        footer = f"Bet: {g.bet:,}" + (" (doubled)" if g.doubled else "")
        if done:
            footer += f" • Balance: {self.cog.bot.db.balance(self.guild_id, self.player.id):,}"
        e.set_footer(text=footer)
        return e

    def finish_if_done(self) -> None:
        if self.game.finished:
            self.cog.settle(self.guild_id, self.player.id, self.game.bet, self.game.payout())
            self.cog.active_blackjack.discard((self.guild_id, self.player.id))
            self.stop()
            if self.message:
                self.cog.bot.schedule_cleanup(self.guild_id, self.message.channel.id, self.message.id)
        self._sync_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return False
        return True

    async def _update(self, interaction: discord.Interaction) -> None:
        self.finish_if_done()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.primary, emoji="➕")
    async def hit(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.game.hit()
        await self._update(interaction)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.game.stand()
        await self._update(interaction)

    @discord.ui.button(label="Double", style=discord.ButtonStyle.success, emoji="⏫")
    async def double(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if not self.game.can_double:
            await interaction.response.send_message("You can only double on your first two cards.", ephemeral=True)
            return
        if not self.cog.bot.db.try_debit(self.guild_id, self.player.id, self.game.bet):
            await interaction.response.send_message("You can't afford to double down.", ephemeral=True)
            return
        self.game.double_down()
        await self._update(interaction)

    async def on_timeout(self) -> None:
        # Player walked away: stand on whatever they have so the bet is resolved.
        if not self.game.finished:
            self.game.stand()
            self.finish_if_done()
            if self.message:
                try:
                    await self.message.edit(embed=self.embed(), view=self)
                except discord.HTTPException:
                    pass


@app_commands.guild_only()
class Casino(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.active_blackjack: set[tuple[int, int]] = set()

    @property
    def db(self):
        return self.bot.db

    async def take_bet(self, interaction: discord.Interaction, bet: int) -> bool:
        if self.db.try_debit(interaction.guild_id, interaction.user.id, bet):
            return True
        bal = self.db.balance(interaction.guild_id, interaction.user.id)
        await interaction.response.send_message(
            f"You only have {money(bal)}. Try `/work`, `/daily` or `/beg` to earn more.", ephemeral=True
        )
        return False

    def settle(self, guild_id: int, user_id: int, bet: int, returned: int) -> int:
        if returned:
            self.db.credit(guild_id, user_id, returned)
        self.db.record_game(guild_id, user_id, bet, returned)
        return self.db.balance(guild_id, user_id)

    @app_commands.command(description="Spin the slot machine.")
    async def slots(self, interaction: discord.Interaction, bet: Bet) -> None:
        if not await self.take_bet(interaction, bet):
            return
        reels = slot_machine.spin()
        returned = bet * slot_machine.payout_multiplier(reels)
        balance = self.settle(interaction.guild_id, interaction.user.id, bet, returned)

        # Little spinning animation, revealing one reel at a time.
        embed = discord.Embed(title="🎰 Slots", description="**[ ❓ | ❓ | ❓ ]**", color=discord.Color.purple())
        await interaction.response.send_message(embed=embed)
        for i in range(1, len(reels) + 1):
            await asyncio.sleep(0.7)
            shown = [s.emoji for s in reels[:i]] + ["❓"] * (len(reels) - i)
            embed.description = f"**[ {' | '.join(shown)} ]**"
            await interaction.edit_original_response(embed=embed)

        text, embed.color = result_line(bet, returned)
        embed.description += f"\n\n{text}"
        embed.set_footer(text=f"Bet: {bet:,} • Balance: {balance:,}")
        await interaction.edit_original_response(embed=embed)

    # Cleaned up by BlackjackView when the hand ends, not when the command returns.
    @app_commands.command(description="Play a hand of blackjack against the dealer.", extras={"manual_cleanup": True})
    async def blackjack(self, interaction: discord.Interaction, bet: Bet) -> None:
        key = (interaction.guild_id, interaction.user.id)
        if key in self.active_blackjack:
            await interaction.response.send_message("Finish your current blackjack game first!", ephemeral=True)
            return
        if not await self.take_bet(interaction, bet):
            return
        self.active_blackjack.add(key)
        view = BlackjackView(self, interaction, BlackjackGame(bet=bet))
        view.finish_if_done()  # natural blackjacks settle immediately
        await interaction.response.send_message(embed=view.embed(), view=view)
        view.message = await interaction.original_response()
        if view.game.finished:  # natural blackjack finished before the message existed
            self.bot.schedule_cleanup(interaction.guild_id, view.message.channel.id, view.message.id)

    @app_commands.command(description="Flip a coin. Double or nothing.")
    async def coinflip(
        self, interaction: discord.Interaction, bet: Bet, side: Literal["heads", "tails"]
    ) -> None:
        if not await self.take_bet(interaction, bet):
            return
        result = random.choice(["heads", "tails"])
        returned = bet * 2 if result == side else 0
        balance = self.settle(interaction.guild_id, interaction.user.id, bet, returned)
        text, color = result_line(bet, returned)
        embed = discord.Embed(title="🪙 Coinflip", description=f"It landed on **{result}**!\n\n{text}", color=color)
        embed.set_footer(text=f"You picked {side} • Bet: {bet:,} • Balance: {balance:,}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Bet on roulette: red/black, odd/even, low/high, 1st12/2nd12/3rd12, or a number 0-36.")
    @app_commands.describe(choice="red, black, odd, even, low, high, 1st12, 2nd12, 3rd12, or a number 0-36")
    async def roulette(self, interaction: discord.Interaction, bet: Bet, choice: str) -> None:
        parsed = roulette_game.parse_choice(choice)
        if parsed is None:
            await interaction.response.send_message(
                "Invalid choice. Use red, black, odd, even, low, high, 1st12, 2nd12, 3rd12 or a number 0-36.",
                ephemeral=True,
            )
            return
        if not await self.take_bet(interaction, bet):
            return
        n = roulette_game.spin()
        returned = bet * roulette_game.payout_multiplier(parsed, n)
        balance = self.settle(interaction.guild_id, interaction.user.id, bet, returned)
        text, color = result_line(bet, returned)
        embed = discord.Embed(
            title="🎡 Roulette",
            description=f"The ball landed on {roulette_game.color_emoji(n)} **{n}**\n\n{text}",
            color=color,
        )
        embed.set_footer(text=f"You bet on {parsed} • Bet: {bet:,} • Balance: {balance:,}")
        await interaction.response.send_message(embed=embed)

    @roulette.autocomplete("choice")
    async def _roulette_choices(self, _: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        options = list(roulette_game.OUTSIDE_BETS) + ["0", "7", "17", "36"]
        return [app_commands.Choice(name=o, value=o) for o in options if current.lower() in o][:25]

    @app_commands.command(description="How each game pays out.")
    async def paytable(self, interaction: discord.Interaction) -> None:
        e = discord.Embed(title="💰 Payouts", color=discord.Color.gold())
        e.add_field(name="🎰 Slots", value="\n".join(slot_machine.paytable_lines()), inline=False)
        e.add_field(
            name="🃏 Blackjack",
            value="Win → **2x** • Blackjack → **2.5x** • Push → bet back\nDealer stands on 17. Double down on your first two cards.",
            inline=False,
        )
        e.add_field(name="🪙 Coinflip", value="Correct call → **2x**", inline=False)
        e.add_field(
            name="🎡 Roulette",
            value="Red/black, odd/even, low/high → **2x**\nDozens (1st12/2nd12/3rd12) → **3x**\nSingle number → **36x**",
            inline=False,
        )
        e.set_footer(text=f"Minimum bet: {config.MIN_BET}. Payouts include your original bet.")
        await interaction.response.send_message(embed=e, ephemeral=True)


async def setup(bot) -> None:
    await bot.add_cog(Casino(bot))
