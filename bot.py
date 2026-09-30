import logging

import discord
from discord.ext import commands

from kelpbot import config
from kelpbot.db import Database

log = logging.getLogger("kelpbot")

EXTENSIONS = ("kelpbot.cogs.economy", "kelpbot.cogs.casino", "kelpbot.cogs.shop")


class KelpBot(commands.Bot):
    def __init__(self) -> None:
        # Slash commands only, so no privileged intents are needed.
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.db = Database(config.DATABASE_PATH, config.STARTING_BALANCE)

    async def setup_hook(self) -> None:
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

    async def close(self) -> None:
        await super().close()
        self.db.close()


def main() -> None:
    if not config.TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
    KelpBot().run(config.TOKEN, root_logger=True)


if __name__ == "__main__":
    main()
