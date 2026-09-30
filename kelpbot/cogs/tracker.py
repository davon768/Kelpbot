"""Keeps one live tracker message in the tracker channel: edited in place, never auto-deleted."""

from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands, tasks

from kelpbot import tracker

log = logging.getLogger("kelpbot.tracker")
CHANNEL_KEY = "tracker_channel_id"
# Re-post at the bottom once this many messages bury it and the channel has gone quiet,
# so it stays easy to find without jumping around mid-conversation.
BURIED_AFTER = 10
QUIET_SECONDS = 120


class Tracker(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.fingerprints: dict[int, int] = {}
        self.buried: dict[int, int] = {}
        self.last_activity: dict[int, float] = {}
        self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    def message_id(self, guild_id: int) -> int:
        return int(self.bot.db.config(guild_id).get(tracker.MESSAGE_KEY, 0))

    @tasks.loop(minutes=1)
    async def tick(self) -> None:
        for guild_id, _ in self.bot.db.config_values(CHANNEL_KEY):
            try:
                await self.refresh(guild_id)
            except Exception:
                log.exception("Tracker refresh failed for guild %s", guild_id)

    @tick.before_loop
    async def _wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    def _should_bump(self, guild_id: int) -> bool:
        quiet = time.monotonic() - self.last_activity.get(guild_id, 0) >= QUIET_SECONDS
        return self.buried.get(guild_id, 0) >= BURIED_AFTER and quiet

    async def refresh(self, guild_id: int, repost: bool = False) -> None:
        """Edit the tracker if its content changed; post a new one if it's missing, buried or `repost`."""
        channel_id = self.bot.cfg(guild_id).tracker_channel_id
        if not channel_id:
            return
        guild = self.bot.get_guild(guild_id)
        embeds = tracker.render(self.bot.db, guild_id, self.bot.cfg(guild_id), guild.name if guild else "Casino")
        fingerprint = tracker.fingerprint(embeds)
        embeds[-1].timestamp = discord.utils.utcnow()
        channel = self.bot.get_partial_messageable(channel_id)
        message_id = self.message_id(guild_id)

        if message_id and not repost and not self._should_bump(guild_id):
            if fingerprint == self.fingerprints.get(guild_id):
                return
            try:
                await channel.get_partial_message(message_id).edit(embeds=embeds)
                self.fingerprints[guild_id] = fingerprint
                return
            except discord.NotFound:
                pass  # someone deleted it: post a fresh one below
            except discord.HTTPException as exc:
                log.warning("Couldn't edit tracker in %s: %s", channel_id, exc)
                return

        await self.delete_message(guild_id)
        try:
            message = await channel.send(embeds=embeds, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as exc:
            log.warning("Couldn't post tracker in %s: %s", channel_id, exc)
            return
        self.bot.db.set_config(guild_id, tracker.MESSAGE_KEY, message.id)
        self.fingerprints[guild_id] = fingerprint
        self.buried[guild_id] = 0

    async def delete_message(self, guild_id: int, channel_id: int | None = None) -> None:
        """Remove the current tracker message, if any."""
        message_id = self.message_id(guild_id)
        if not message_id:
            return
        channel_id = channel_id or self.bot.cfg(guild_id).tracker_channel_id
        self.bot.db.set_config(guild_id, tracker.MESSAGE_KEY, None)
        self.fingerprints.pop(guild_id, None)
        if channel_id:
            try:
                await self.bot.get_partial_messageable(channel_id).get_partial_message(message_id).delete()
            except discord.HTTPException:
                pass

    async def move(self, guild_id: int, old_channel_id: int, new_channel_id: int | None) -> None:
        """Called when an admin sets or clears the tracker channel."""
        await self.delete_message(guild_id, old_channel_id)
        self.bot.db.set_config(guild_id, CHANNEL_KEY, new_channel_id)
        if new_channel_id:
            await self.refresh(guild_id, repost=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        raw = self.bot.db.config(message.guild.id)
        if raw.get(CHANNEL_KEY) != str(message.channel.id) or raw.get(tracker.MESSAGE_KEY) == str(message.id):
            return
        self.buried[message.guild.id] = self.buried.get(message.guild.id, 0) + 1
        self.last_activity[message.guild.id] = time.monotonic()

    def _on_deleted(self, guild_id: int | None, channel_id: int, message_ids: set[int]) -> None:
        if guild_id is None:
            return
        raw = self.bot.db.config(guild_id)
        if raw.get(CHANNEL_KEY) != str(channel_id):
            return
        if int(raw.get(tracker.MESSAGE_KEY, 0)) in message_ids:
            # Someone deleted the tracker: forget it so the next tick posts a new one.
            self.bot.db.set_config(guild_id, tracker.MESSAGE_KEY, None)
            self.fingerprints.pop(guild_id, None)
        else:
            self.buried[guild_id] = max(0, self.buried.get(guild_id, 0) - len(message_ids))

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        self._on_deleted(payload.guild_id, payload.channel_id, {payload.message_id})

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent) -> None:
        self._on_deleted(payload.guild_id, payload.channel_id, set(payload.message_ids))


async def setup(bot) -> None:
    await bot.add_cog(Tracker(bot))
