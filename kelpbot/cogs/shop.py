"""Buying, selling and using items, and buying roles."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from kelpbot import achievements, config
from kelpbot.shop import ENERGY_DRINK, ITEMS, Kind, TradeResult, buy, sell

ITEM_CHOICES = [app_commands.Choice(name=f"{i.name} ({i.price:,})", value=i.key) for i in ITEMS.values()]
USABLE_CHOICES = [app_commands.Choice(name=i.name, value=i.key) for i in ITEMS.values() if i.kind is Kind.USABLE]


class Shop(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    @app_commands.command(description="See what's for sale.")
    async def shop(self, interaction: discord.Interaction) -> None:
        cfg = self.bot.cfg(interaction.guild_id)
        embed = discord.Embed(title="🛒 Kelp Mart", color=discord.Color.teal())
        for item in ITEMS.values():
            limit = f" • max {item.max_owned}" if item.max_owned else ""
            embed.add_field(
                name=f"{item.label}: {cfg.money(item.price)}",
                value=f"{item.description}\n*{item.kind.value}{limit}*",
                inline=False,
            )
        roles = self.db.shop_roles(interaction.guild_id)
        if roles:
            embed.add_field(
                name="🎭 Roles (buy with /buyrole)",
                value="\n".join(f"<@&{rid}>: {cfg.money(price)}" for rid, price in roles.items()),
                inline=False,
            )
        balance = self.db.balance(interaction.guild_id, interaction.user.id)
        embed.set_footer(text=f"Buy with /buy • Items sell back for half price • Your wallet: {balance:,}")
        await interaction.response.send_message(embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @app_commands.command(description="Buy an item from the shop.")
    @app_commands.choices(item=ITEM_CHOICES)
    async def buy(
        self, interaction: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 100] = 1
    ) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        it = ITEMS[item]
        result = buy(self.db, gid, uid, item, quantity)
        if result is TradeResult.MAX_OWNED:
            await interaction.response.send_message(f"You can only hold {it.max_owned} {it.label}.", ephemeral=True)
        elif result is TradeResult.CANT_AFFORD:
            await interaction.response.send_message(
                f"That costs {cfg.money(it.price * quantity)} and your wallet has {cfg.money(self.db.balance(gid, uid))}.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"🛍️ You bought **{quantity}x {it.label}** for {cfg.money(it.price * quantity)}.\n"
                f"Wallet: {cfg.money(self.db.balance(gid, uid))}"
            )
            await self.bot.award(interaction, achievements.bump(self.db, gid, uid, "items_bought", quantity))

    @app_commands.command(description="Sell an item back to the shop for half what it cost.")
    @app_commands.choices(item=ITEM_CHOICES)
    async def sell(
        self, interaction: discord.Interaction, item: str, quantity: app_commands.Range[int, 1, 100] = 1
    ) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        it = ITEMS[item]
        if sell(self.db, gid, uid, item, quantity) is TradeResult.NOT_OWNED:
            await interaction.response.send_message(f"You don't have {quantity}x {it.label}.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"💰 You sold **{quantity}x {it.label}** for {cfg.money(it.sell_price * quantity)}.\n"
            f"Wallet: {cfg.money(self.db.balance(gid, uid))}"
        )

    @app_commands.command(name="use", description="Use an item from your inventory.")
    @app_commands.choices(item=USABLE_CHOICES)
    async def use_item(self, interaction: discord.Interaction, item: str) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        it = ITEMS[item]
        if item == ENERGY_DRINK.key and not self.db.cooldown_remaining(gid, uid, "work", config.WORK_COOLDOWN):
            await interaction.response.send_message("You can already `/work`. Save it for later!", ephemeral=True)
            return
        if not self.db.remove_item(gid, uid, item):
            await interaction.response.send_message(f"You don't have a {it.label}.", ephemeral=True)
            return
        if item == ENERGY_DRINK.key:
            self.db.clear_cooldown(gid, uid, "work")
            await interaction.response.send_message(f"{it.emoji} Glug glug. You're ready to `/work` again!")

    @app_commands.command(description="See what you (or someone else) own.")
    async def inventory(self, interaction: discord.Interaction, user: discord.Member | None = None) -> None:
        target = user or interaction.user
        owned = self.db.inventory(interaction.guild_id, target.id)
        lines = [f"{ITEMS[k].label} × **{q}**" for k, q in owned.items() if k in ITEMS]
        worth = sum(ITEMS[k].sell_price * q for k, q in owned.items() if k in ITEMS)
        embed = discord.Embed(
            title=f"🎒 {target.display_name}'s inventory",
            description="\n".join(lines) or "Empty. Check out `/shop`!",
            color=discord.Color.teal(),
        )
        if lines:
            embed.set_footer(text=f"Resale value: {worth:,}")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Buy a role from the shop. Roles are permanent and can't be sold back.")
    async def buyrole(self, interaction: discord.Interaction, role: discord.Role) -> None:
        gid, uid = interaction.guild_id, interaction.user.id
        cfg = self.bot.cfg(gid)
        price = self.db.shop_roles(gid).get(role.id)
        me = interaction.guild.me
        error = None
        if price is None:
            error = f"{role.mention} isn't for sale. See `/shop` for roles you can buy."
        elif role in interaction.user.roles:
            error = f"You already have {role.mention}."
        elif not me.guild_permissions.manage_roles or role >= me.top_role:
            error = ("I can't hand out that role. An admin needs to give me **Manage Roles** and put my role "
                     "above it in Server Settings → Roles.")
        elif not self.db.try_debit(gid, uid, price):
            error = f"{role.mention} costs {cfg.money(price)}. Your wallet has {cfg.money(self.db.balance(gid, uid))}."
        if error:
            await interaction.response.send_message(error, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        try:
            await interaction.user.add_roles(role, reason=f"Bought in the Kelpbot shop for {price:,}")
        except discord.HTTPException:
            self.db.credit(gid, uid, price)
            await interaction.response.send_message("Discord wouldn't let me give you that role. You weren't charged.",
                                                    ephemeral=True)
            return
        self.bot.log_event(gid, f"🎭 <@{uid}> bought <@&{role.id}> for {cfg.money(price)}.")
        self.db.add_event(gid, "role", uid, price, other_id=role.id)
        await interaction.response.send_message(
            f"🎭 You bought {role.mention} for **{cfg.money(price)}**!",
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self.bot.award(interaction, achievements.bump(self.db, gid, uid, "items_bought"))


async def setup(bot) -> None:
    await bot.add_cog(Shop(bot))
