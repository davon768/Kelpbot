import asyncio
import logging
import os
from collections.abc import Coroutine

import discord
from discord.ext import commands

from kelpbot import config, settings
from kelpbot.db import Database
from kelpbot.settings import GuildConfig

log = logging.getLogger("kelpbot")

EXTENSIONS = (
    "kelpbot.cogs.economy",
    "kelpbot.cogs.casino",
    "kelpbot.cogs.arcade",
    "kelpbot.cogs.duels",
    "kelpbot.cogs.lottery",
    "kelpbot.cogs.scheduler",
    "kelpbot.cogs.tracker",
    "kelpbot.cogs.heist",
    "kelpbot.cogs.race",
    "kelpbot.cogs.stocks",
    "kelpbot.cogs.profile",
    "kelpbot.cogs.help",
    "kelpbot.cogs.games",
    "kelpbot.cogs.facts",
    "kelpbot.cogs.trivia",
    "kelpbot.cogs.shop",
    "kelpbot.cogs.admin",
    "kelpbot.cogs.cleanup",
)
LAST_CHANNEL_KEY = "_last_channel_id"


class KelpBot(commands.Bot):
    def __init__(self) -> None:
        # Slash commands only, so no privileged intents are needed.
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.db = Database(config.DATABASE_PATH, config.STARTING_BALANCE, config.AUTO_DELETE_DEFAULT_SECONDS)
        self.active_games: set[tuple[int, int, str]] = set()
        self._background: set[asyncio.Task] = set()
        self._refunds: list[tuple[int, int, str, int]] = []

    async def setup_hook(self) -> None:
        log.info("Using database at %s", config.DATABASE_PATH)
        # Nothing survives a restart, so any stake still held belongs to a game that was cut off.
        self._refunds = self.db.refund_open_bets()
        if self._refunds:
            log.info("Refunded %d bets from games interrupted by a restart", len(self._refunds))
        if config.ON_RAILWAY and not os.getenv("RAILWAY_VOLUME_MOUNT_PATH") and not os.getenv("DATABASE_PATH"):
            log.warning(
                "No Railway volume attached! Balances will be WIPED on every redeploy. "
                "Attach a volume to this service (any mount path, e.g. /data)."
            )
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        self.lock_commands_to_servers()
        if config.DEV_GUILD_ID:
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to dev guild %s", len(synced), config.DEV_GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (may take up to an hour to appear)", len(synced))

    def lock_commands_to_servers(self) -> None:
        """Every economy is tied to a server, so no command may run in DMs."""
        for command in self.tree.get_commands():
            command.guild_only = True

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        refunds, self._refunds = self._refunds, []
        for guild_id, user_id, game, amount in refunds:
            cfg = self.cfg(guild_id)
            self.log_event(guild_id, f"↩️ Refunded <@{user_id}> {cfg.money(amount)} from a {game} game "
                                     "interrupted by a restart.")
        await self.change_presence(activity=discord.Game("🎰 /slots • /blackjack • /crash"))

    def cfg(self, guild_id: int) -> GuildConfig:
        return settings.load(self.db, guild_id)

    def fire(self, coro: Coroutine) -> None:
        """Run a coroutine in the background without losing track of it."""
        task = asyncio.create_task(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    # ---- auto-delete ---------------------------------------------------------------

    def schedule_cleanup(self, guild_id: int, channel_id: int, message_id: int) -> None:
        """Delete one of our messages after the server's auto-delete delay, if enabled."""
        delay = self.db.auto_delete_seconds(guild_id)
        if delay > 0:
            self.fire(self._delete_later(channel_id, message_id, delay))

    async def _delete_later(self, channel_id: int, message_id: int, delay: int) -> None:
        await asyncio.sleep(delay)
        # Delete through the channel (not the interaction webhook), which keeps working
        # after the 15 minute interaction token expires. Bots can always delete their own messages.
        try:
            await self.get_partial_messageable(channel_id).get_partial_message(message_id).delete()
        except discord.HTTPException:
            pass  # already deleted, or we lost access to the channel

    # ---- log & announcement channels -------------------------------------------------

    def log_event(self, guild_id: int, text: str) -> None:
        """Post to the server's log channel, if one is set. Never raises."""
        channel_id = self.cfg(guild_id).log_channel_id
        if channel_id:
            embed = discord.Embed(description=text, color=discord.Color.dark_grey(), timestamp=discord.utils.utcnow())
            self.fire(self._send(channel_id, embed))

    async def announce(self, guild_id: int, embed: discord.Embed, fallback_channel_id: int = 0) -> None:
        """Post to the announcement channel, else the given fallback, else wherever the bot was last used."""
        channel_id = (
            self.cfg(guild_id).announce_channel_id
            or fallback_channel_id
            or int(self.db.config(guild_id).get(LAST_CHANNEL_KEY, 0))
        )
        if channel_id:
            await self._send(channel_id, embed)

    async def _send(self, channel_id: int, embed: discord.Embed) -> None:
        try:
            await self.get_partial_messageable(channel_id).send(
                embed=embed, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException as exc:
            log.warning("Couldn't post to channel %s: %s", channel_id, exc)

    def remember_channel(self, guild_id: int, channel_id: int) -> None:
        if self.db.config(guild_id).get(LAST_CHANNEL_KEY) != str(channel_id):
            self.db.set_config(guild_id, LAST_CHANNEL_KEY, channel_id)

    # ---- achievements --------------------------------------------------------------

    def rewards_embed(self, guild_id: int, user: discord.abc.User, rewards: list) -> discord.Embed:
        """Achievements, quests and bonuses (anything with badge/emoji/name/description/reward)."""
        cfg = self.cfg(guild_id)
        lines = [
            f"{r.badge} · {r.emoji} **{r.name}**: {r.description}" + (f" (+{cfg.money(r.reward)})" if r.reward else "")
            for r in rewards
        ]
        return discord.Embed(
            title=f"🎉 Nice one, {user.display_name}!",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )

    async def award(self, interaction: discord.Interaction, rewards: list,
                    user: discord.abc.User | None = None) -> None:
        """Announce achievements, finished quests and bonuses as a follow-up to an interaction."""
        if not rewards:
            return
        embed = self.rewards_embed(interaction.guild_id, user or interaction.user, rewards)
        try:
            if interaction.response.is_done():
                msg = await interaction.followup.send(embed=embed, wait=True)
            else:
                await interaction.response.send_message(embed=embed)
                msg = await interaction.original_response()
            self.schedule_cleanup(interaction.guild_id, msg.channel.id, msg.id)
        except discord.HTTPException:
            pass

    async def close(self) -> None:
        await super().close()
        self.db.close()


def main() -> None:
    if not config.TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
    KelpBot().run(config.TOKEN, root_logger=True)


if __name__ == "__main__":
    main()
