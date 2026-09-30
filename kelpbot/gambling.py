"""Discord-side helpers shared by every game: taking bets, paying out, and player-only views."""

from __future__ import annotations

import discord

from kelpbot import achievements, config, quests, server_events
from kelpbot.rewards import Reward


async def game_allowed(bot, interaction: discord.Interaction, game: str) -> bool:
    """False (after telling the player) if an admin switched this game off."""
    if game in bot.cfg(interaction.guild_id).disabled_games:
        await interaction.response.send_message(f"🚫 {game.capitalize()} is turned off in this server.",
                                                ephemeral=True)
        return False
    return True


async def take_bet(bot, interaction: discord.Interaction, bet: int, game: str) -> bool:
    """Check the game is on and the bet is within limits, then take the stake from the wallet."""
    if not await game_allowed(bot, interaction, game):
        return False
    cfg = bot.cfg(interaction.guild_id)
    error = None
    if bet < cfg.min_bet:
        error = f"The minimum bet here is {cfg.money(cfg.min_bet)}."
    elif cfg.max_bet and bet > cfg.max_bet:
        error = f"The maximum bet here is {cfg.money(cfg.max_bet)}."
    elif not bot.db.try_debit(interaction.guild_id, interaction.user.id, bet):
        bal = bot.db.balance(interaction.guild_id, interaction.user.id)
        error = f"You only have {cfg.money(bal)} in your wallet. Try `/work`, `/daily`, `/withdraw` or `/beg`."
    if error:
        await interaction.response.send_message(error, ephemeral=True)
        return False
    return True


def settle(bot, guild_id: int, user_id: int, bet: int, returned: int, game: str) -> tuple[int, list]:
    """Pay out a finished game, record stats, and check achievements, quests and events.

    Returns (new balance, rewards earned), where rewards are shown with bot.award().
    """
    db = bot.db
    if returned:
        db.credit(guild_id, user_id, returned)
    rewards: list = []
    if returned > bet and server_events.is_active(db, guild_id, "lucky_hour"):
        bonus = returned * config.LUCKY_HOUR_BONUS_PERCENT // 100
        db.credit(guild_id, user_id, bonus)
        rewards.append(Reward("🍀 Lucky Hour", "🍀", "Bonus", f"+{config.LUCKY_HOUR_BONUS_PERCENT}% on your winnings",
                              bonus))
    db.record_game(guild_id, user_id, bet, returned)
    db.log_game(guild_id, user_id, game, bet, returned)
    rewards += achievements.after_game(db, guild_id, user_id, bet, returned)
    rewards += quests.on_game(db, guild_id, user_id, game, bet, returned)
    profit = returned - bet
    if is_highlight(bet, returned):
        db.add_event(guild_id, "big_win", user_id, profit, amount2=bet, detail=game)
    if profit >= config.BIG_WIN_LOG_THRESHOLD:
        cfg = bot.cfg(guild_id)
        bot.log_event(guild_id, f"🎉 <@{user_id}> won **{cfg.money(profit)}** on {game} (bet {cfg.money(bet)}).")
    return db.balance(guild_id, user_id), rewards


def is_highlight(bet: int, returned: int) -> bool:
    """Wins worth putting in the tracker's history."""
    profit = returned - bet
    if profit >= config.HISTORY_BIG_WIN_PROFIT:
        return True
    return (bet > 0 and returned / bet >= config.HISTORY_BIG_MULTIPLIER
            and profit >= config.HISTORY_BIG_MULTIPLIER_MIN_PROFIT)


def result_line(cfg, bet: int, returned: int) -> tuple[str, discord.Color]:
    if returned > bet:
        return f"🎉 You won **{cfg.money(returned - bet)}**!", discord.Color.green()
    if returned == bet:
        return "🤝 You got your bet back.", discord.Color.light_grey()
    return f"💀 You lost **{cfg.money(bet)}**.", discord.Color.red()


class PlayerView(discord.ui.View):
    """A view only one player can press, tracked so they can't run two of the same game."""

    game_name = "game"

    def __init__(self, bot, interaction: discord.Interaction, timeout: float = 120) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild_id = interaction.guild_id
        self.player = interaction.user
        self.cfg = bot.cfg(interaction.guild_id)
        self.message: discord.InteractionMessage | None = None
        self.settled = False
        self.bet_id: int | None = None

    def track_bet(self, amount: int) -> None:
        """Remember the stake so it's refunded if the bot restarts before the game ends."""
        if self.bet_id is None:
            self.bet_id = self.bot.db.open_bet(self.guild_id, self.player.id, self.game_name, amount)
        else:
            self.bot.db.update_open_bet(self.bet_id, amount)

    @property
    def key(self) -> tuple[int, int, str]:
        return (self.guild_id, self.player.id, self.game_name)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player.id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return False
        return True

    def disable_all(self) -> None:
        for child in self.children:
            child.disabled = True

    def finalize(self, bet: int, returned: int) -> list | None:
        """Settle exactly once. Returns rewards earned, or None if already settled."""
        if self.settled:
            return None
        self.settled = True
        self.bot.db.close_bet(self.bet_id)
        self.balance, unlocked = settle(self.bot, self.guild_id, self.player.id, bet, returned, self.game_name)
        self.bot.active_games.discard(self.key)
        self.disable_all()
        self.stop()
        if self.message:
            self.bot.schedule_cleanup(self.guild_id, self.message.channel.id, self.message.id)
        return unlocked


async def start_guard(bot, interaction: discord.Interaction, game: str) -> bool:
    """Refuse to start a second copy of an interactive game for the same player."""
    if (interaction.guild_id, interaction.user.id, game) in bot.active_games:
        await interaction.response.send_message(f"Finish your current {game} game first!", ephemeral=True)
        return False
    return True
