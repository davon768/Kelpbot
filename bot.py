import asyncio
import logging
import os

import discord
from discord.ext import commands

from kelpbot import config
from kelpbot.db import Database

log = logging.getLogger("kelpbot")

EXTENSIONS = ("kelpbot.cogs.economy", "kelpbot.cogs.casino", "kelpbot.cogs.shop", "kelpbot.cogs.cleanup")


class KelpBot(commands.Bot):
    def __init__(self) -> None:
        # Slash commands only, so no privileged intents are needed.
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.db = Database(config.DATABASE_PATH, config.STARTING_BALANCE, config.AUTO_DELETE_DEFAULT_SECONDS)
        self._cleanup_tasks: set[asyncio.Task] = set()

    async def setup_hook(self) -> None:
        log.info("Using database at %s", config.DATABASE_PATH)
        if config.ON_RAILWAY and not os.getenv("RAILWAY_VOLUME_MOUNT_PATH") and not os.getenv("DATABASE_PATH"):
            log.warning(
                "No Railway volume attached! Balances will be WIPED on every redeploy. "
                "Attach a volume to this service (any mount path, e.g. /data)."
            )
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        if config.DEV_GUILD_ID:
            guild = discord.Object(id=config.DEV_GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to dev guild %s", len(synced), config.DEV_GUILD_ID)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (may take up to an hour to appear)", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user.id)
        await self.change_presence(activity=discord.Game("🎰 /slots • /blackjack"))

    def schedule_cleanup(self, guild_id: int, channel_id: int, message_id: int) -> None:
        """Delete one of our messages after the server's auto-delete delay, if enabled."""
        delay = self.db.auto_delete_seconds(guild_id)
        if delay <= 0:
            return
        task = asyncio.create_task(self._delete_later(channel_id, message_id, delay))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def _delete_later(self, channel_id: int, message_id: int, delay: int) -> None:
        await asyncio.sleep(delay)
        # Delete through the channel (not the interaction webhook), which keeps working
        # after the 15 minute interaction token expires. Bots can always delete their own messages.
        try:
            await self.get_partial_messageable(channel_id).get_partial_message(message_id).delete()
        except discord.HTTPException:
            pass  # already deleted, or we lost access to the channel

    async def close(self) -> None:
        await super().close()
        self.db.close()


def main() -> None:
    if not config.TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
    KelpBot().run(config.TOKEN, root_logger=True)


if __name__ == "__main__":
    main()
