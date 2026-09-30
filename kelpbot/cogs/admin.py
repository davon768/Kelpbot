"""Server admin tools: settings, money adjustments, resets, seasons and shop roles."""

from __future__ import annotations

from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import achievements, settings, weekly
from kelpbot.settings import CHANNEL_SETTINGS, SETTINGS

SETTING_CHOICES = [app_commands.Choice(name=s.label, value=s.key) for s in SETTINGS.values()]
# Roles with any of these can't be sold: buying one would hand out moderator powers.
DANGEROUS_PERMISSIONS = (
    "administrator", "manage_guild", "manage_roles", "manage_channels", "manage_messages", "manage_webhooks",
    "kick_members", "ban_members", "moderate_members", "mention_everyone", "manage_nicknames",
    "manage_expressions", "manage_events", "manage_threads",
)


class ConfirmView(discord.ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=30)
        self.user_id = user_id
        self.confirmed: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Yes, do it", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.confirmed = True
        await interaction.response.defer()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        self.confirmed = False
        await interaction.response.defer()
        self.stop()


async def confirm(interaction: discord.Interaction, warning: str) -> bool:
    view = ConfirmView(interaction.user.id)
    await interaction.response.send_message(f"⚠️ {warning}", view=view, ephemeral=True)
    await view.wait()
    if not view.confirmed:
        await interaction.edit_original_response(content="Cancelled.", view=None)
    return bool(view.confirmed)


@app_commands.guild_only()
@app_commands.default_permissions(manage_guild=True)
class SettingsGroup(app_commands.Group, name="settings", description="[Admin] Configure the economy for this server"):
    def __init__(self, bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(description="Show this server's economy settings.")
    async def view(self, interaction: discord.Interaction) -> None:
        cfg = self.bot.cfg(interaction.guild_id)
        lines = [f"**{s.label}**: {settings.display(s, getattr(cfg, s.key))}" for s in SETTINGS.values()]
        for key, label in CHANNEL_SETTINGS.items():
            channel_id = getattr(cfg, key)
            lines.append(f"**{label.split(' (')[0]}**: {f'<#{channel_id}>' if channel_id else 'not set'}")
        embed = discord.Embed(title="⚙️ Server settings", description="\n".join(lines), color=discord.Color.blurple())
        embed.set_footer(text="Change with /settings set, /settings channel or /settings reset")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="set", description="Change a setting.")
    @app_commands.choices(setting=SETTING_CHOICES)
    @app_commands.describe(value="New value. Numbers for amounts, on/off for switches.")
    async def set_setting(self, interaction: discord.Interaction, setting: str, value: str) -> None:
        s = SETTINGS[setting]
        try:
            parsed = settings.parse(s, value)
        except ValueError as exc:
            await interaction.response.send_message(f"❌ {s.label}: {exc}", ephemeral=True)
            return
        cfg = self.bot.cfg(interaction.guild_id)
        min_bet = parsed if setting == "min_bet" else cfg.min_bet
        max_bet = parsed if setting == "max_bet" else cfg.max_bet
        if max_bet and min_bet > max_bet:
            await interaction.response.send_message("❌ The minimum bet can't be above the maximum bet.", ephemeral=True)
            return
        settings.save(self.bot.db, interaction.guild_id, setting, parsed)
        shown = settings.display(s, parsed)
        self.bot.log_event(interaction.guild_id, f"⚙️ <@{interaction.user.id}> set **{s.label}** to {shown}.")
        await interaction.response.send_message(f"✅ **{s.label}** is now **{shown}**.", ephemeral=True)

    @app_commands.command(description="Put a setting back to its default.")
    @app_commands.choices(setting=SETTING_CHOICES)
    async def reset(self, interaction: discord.Interaction, setting: str) -> None:
        s = SETTINGS[setting]
        settings.save(self.bot.db, interaction.guild_id, setting, None)
        self.bot.log_event(interaction.guild_id, f"⚙️ <@{interaction.user.id}> reset **{s.label}** to the default.")
        await interaction.response.send_message(
            f"✅ **{s.label}** is back to the default (**{settings.display(s, s.default)}**).", ephemeral=True
        )

    @app_commands.command(description="Set (or clear) the log, announcement or tracker channel.")
    @app_commands.describe(kind="log = private mod log, announce = lottery/weekly/season posts, "
                                "tracker = live leaderboard message",
                           channel="Leave empty to clear it")
    async def channel(self, interaction: discord.Interaction, kind: Literal["log", "announce", "tracker"],
                      channel: discord.TextChannel | None = None) -> None:
        key = f"{kind}_channel_id"
        if channel:
            perms = channel.permissions_for(interaction.guild.me)
            if not (perms.view_channel and perms.send_messages and perms.embed_links):
                await interaction.response.send_message(
                    f"❌ I need **View Channel**, **Send Messages** and **Embed Links** in {channel.mention}.",
                    ephemeral=True,
                )
                return
        label = CHANNEL_SETTINGS[key].split(" (")[0]
        if kind == "tracker":
            await interaction.response.defer(ephemeral=True, thinking=True)
            old = self.bot.cfg(interaction.guild_id).tracker_channel_id
            await self.bot.get_cog("Tracker").move(interaction.guild_id, old, channel.id if channel else None)
            text = (f"✅ The tracker is live in {channel.mention}. It updates every minute and is never "
                    "auto-deleted. Run this again any time to re-post it." if channel else "✅ Tracker removed.")
            await interaction.followup.send(text, ephemeral=True)
        else:
            self.bot.db.set_config(interaction.guild_id, key, channel.id if channel else None)
            text = f"✅ {label} set to {channel.mention}." if channel else f"✅ {label} cleared."
            await interaction.response.send_message(text, ephemeral=True)
        self.bot.log_event(interaction.guild_id, f"⚙️ <@{interaction.user.id}> changed the {label.lower()}.")


@app_commands.guild_only()
@app_commands.default_permissions(manage_roles=True)
class ShopRoleGroup(app_commands.Group, name="shoprole", description="[Admin] Sell roles in the shop"):
    def __init__(self, bot) -> None:
        super().__init__()
        self.bot = bot

    @app_commands.command(description="Put a role up for sale (or change its price).")
    async def add(self, interaction: discord.Interaction, role: discord.Role,
                  price: app_commands.Range[int, 1]) -> None:
        me = interaction.guild.me
        dangerous = [p for p in DANGEROUS_PERMISSIONS if getattr(role.permissions, p, False)]
        error = None
        if role.is_default() or role.managed:
            error = "That role can't be sold."
        elif dangerous:
            error = f"{role.mention} has moderator permissions ({', '.join(dangerous)}), so it can't be sold."
        elif role >= me.top_role:
            error = f"My role needs to be above {role.mention} (Server Settings → Roles) so I can hand it out."
        elif not me.guild_permissions.manage_roles:
            error = "I need the **Manage Roles** permission to sell roles."
        if error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        self.bot.db.set_shop_role(interaction.guild_id, role.id, price)
        cfg = self.bot.cfg(interaction.guild_id)
        self.bot.log_event(interaction.guild_id, f"🎭 <@{interaction.user.id}> listed <@&{role.id}> for {cfg.money(price)}.")
        await interaction.response.send_message(f"✅ {role.mention} is now for sale for **{cfg.money(price)}**.",
                                                ephemeral=True)

    @app_commands.command(description="Stop selling a role. People who bought it keep it.")
    async def remove(self, interaction: discord.Interaction, role: discord.Role) -> None:
        self.bot.db.set_shop_role(interaction.guild_id, role.id, None)
        await interaction.response.send_message(f"✅ {role.mention} is no longer for sale.", ephemeral=True)


class Admin(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.bot.tree.add_command(SettingsGroup(bot))
        self.bot.tree.add_command(ShopRoleGroup(bot))

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command("settings")
        self.bot.tree.remove_command("shoprole")

    @app_commands.command(name="addmoney", description="[Admin] Add or remove money from a player's wallet.")
    @app_commands.default_permissions(manage_guild=True)
    async def add_money(self, interaction: discord.Interaction, user: discord.Member, amount: int) -> None:
        cfg = self.bot.cfg(interaction.guild_id)
        new_balance = self.bot.db.credit(interaction.guild_id, user.id, amount)
        self.bot.log_event(
            interaction.guild_id, f"🛠️ <@{interaction.user.id}> adjusted <@{user.id}>'s wallet by {amount:+,}."
        )
        await interaction.response.send_message(
            f"✅ Adjusted {user.mention} by {amount:+,}. New wallet: {cfg.money(new_balance)}", ephemeral=True
        )

    @app_commands.command(name="reseteconomy",
                          description="[Admin] Wipe everyone's money and items, or just one player's.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(user="Only reset this player (leave empty to reset everyone)")
    async def reset_economy(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        who = user.mention if user else "**everyone** in this server"
        if not await confirm(interaction, f"This wipes the wallet, bank, items, cooldowns and progress of {who}. "
                                          "Settings, shop roles and achievements are kept. This can't be undone."):
            return
        self.bot.db.reset_economy(interaction.guild_id, user.id if user else None)
        self.bot.log_event(interaction.guild_id, f"🧨 <@{interaction.user.id}> reset the economy for {who}.")
        await interaction.edit_original_response(content=f"✅ Economy reset for {who}.", view=None)

    @app_commands.command(name="endseason",
                          description="[Admin] Crown the top 3, save them to the hall of fame, and reset the economy.")
    @app_commands.default_permissions(manage_guild=True)
    async def end_season(self, interaction: discord.Interaction) -> None:
        gid = interaction.guild_id
        season = weekly.current_season(self.bot.db, gid)
        if not await confirm(interaction, f"This ends **Season {season}**: the top 3 go into `/halloffame` and "
                                          "everyone's money and items are wiped. This can't be undone."):
            return
        season, top = weekly.end_season(self.bot.db, gid)
        if top:
            achievements.unlock(self.bot.db, gid, top[0][0], "champion")
        champion, worth = top[0] if top else (0, 0)
        self.bot.db.add_event(gid, "season", champion, worth, amount2=season)
        cfg = self.bot.cfg(gid)
        medals = ["🥇", "🥈", "🥉"]
        podium = "\n".join(f"{medals[i]} <@{uid}>: {cfg.money(worth)}" for i, (uid, worth) in enumerate(top))
        embed = discord.Embed(
            title=f"🏁 Season {season} is over!",
            description=(podium or "Nobody played this season.") +
            f"\n\nEveryone starts fresh in **Season {season + 1}**. Good luck!",
            color=discord.Color.gold(),
        )
        await self.bot.announce(gid, embed, fallback_channel_id=interaction.channel_id)
        self.bot.log_event(gid, f"🏁 <@{interaction.user.id}> ended season {season}.")
        await interaction.edit_original_response(content=f"✅ Season {season} ended.", view=None)


async def setup(bot) -> None:
    await bot.add_cog(Admin(bot))
