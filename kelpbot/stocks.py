"""A small fake stock market per server. Prices move every hour."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from enum import Enum

from kelpbot import config
from kelpbot.db import Database

REVERSION = 0.05  # pull back toward the base price so prices don't run away forever
MAX_CATCH_UP_HOURS = 24
MAX_SHARES_PER_TRADE = 10_000


@dataclass(frozen=True)
class Stock:
    symbol: str
    name: str
    emoji: str
    base: float
    volatility: float  # typical hourly move (0.03 = about 3%)


STOCKS: dict[str, Stock] = {s.symbol: s for s in (
    Stock("KELP", "Kelp Corp", "🌿", 100.0, 0.02),
    Stock("SHEL", "Shell Industries", "🐚", 250.0, 0.035),
    Stock("PRL", "Pearl Holdings", "🦪", 500.0, 0.03),
    Stock("CRAB", "Crab Coin", "🦀", 40.0, 0.08),
)}


class TradeResult(Enum):
    OK = "ok"
    CANT_AFFORD = "cant_afford"
    NOT_ENOUGH_SHARES = "not_enough_shares"


def ensure(db: Database, guild_id: int, now: float | None = None) -> dict[str, float]:
    """Current prices, creating the market the first time a server uses it."""
    now = time.time() if now is None else now
    prices = db.stock_prices(guild_id)
    for s in STOCKS.values():
        if s.symbol not in prices:
            db.set_stock_price(guild_id, s.symbol, s.base, now)
            prices[s.symbol] = (s.base, now)
    return {sym: p for sym, (p, _) in prices.items() if sym in STOCKS}


def step(stock: Stock, price: float, rng: random.Random) -> float:
    change = stock.volatility * rng.gauss(0, 1) + REVERSION * (math.log(stock.base) - math.log(price))
    return round(max(1.0, price * math.exp(change)), 2)


def update_due(db: Database, guild_id: int, now: float | None = None,
               rng: random.Random | None = None) -> list[tuple[str, float, float]]:
    """Move prices for every full hour that passed. Returns (symbol, old, new) for each stock that moved."""
    now = time.time() if now is None else now
    rng = rng or random.Random()
    moves = []
    for symbol, (price, updated) in db.stock_prices(guild_id).items():
        stock = STOCKS.get(symbol)
        hours = int((now - updated) // config.STOCK_UPDATE_SECONDS)
        if stock is None or hours <= 0:
            continue
        new = price
        for _ in range(min(hours, MAX_CATCH_UP_HOURS)):
            new = step(stock, new, rng)
        db.set_stock_price(guild_id, symbol, new, updated + hours * config.STOCK_UPDATE_SECONDS)
        moves.append((symbol, price, new))
    return moves


def buy_cost(price: float, shares: int) -> int:
    return math.ceil(price * shares * (100 + config.STOCK_FEE_PERCENT) / 100)


def sell_value(price: float, shares: int) -> int:
    return math.floor(price * shares * (100 - config.STOCK_FEE_PERCENT) / 100)


def buy(db: Database, guild_id: int, user_id: int, symbol: str, shares: int) -> tuple[TradeResult, int]:
    price = ensure(db, guild_id)[symbol]
    cost = buy_cost(price, shares)
    with db.transaction():
        if not db.try_debit(guild_id, user_id, cost):
            return TradeResult.CANT_AFFORD, cost
        held, basis = db.holdings(guild_id, user_id).get(symbol, (0, 0))
        db.set_holding(guild_id, user_id, symbol, held + shares, basis + cost)
    return TradeResult.OK, cost


def sell(db: Database, guild_id: int, user_id: int, symbol: str, shares: int) -> tuple[TradeResult, int, int]:
    """Returns (result, money received, profit compared to what those shares cost)."""
    price = ensure(db, guild_id)[symbol]
    held, basis = db.holdings(guild_id, user_id).get(symbol, (0, 0))
    if shares > held:
        return TradeResult.NOT_ENOUGH_SHARES, 0, 0
    value = sell_value(price, shares)
    sold_basis = basis * shares // held
    with db.transaction():
        db.set_holding(guild_id, user_id, symbol, held - shares, basis - sold_basis)
        db.credit(guild_id, user_id, value)
    return TradeResult.OK, value, value - sold_basis


def portfolio_value(db: Database, guild_id: int, user_id: int) -> int:
    held = db.holdings(guild_id, user_id)
    if not held:
        return 0
    prices = ensure(db, guild_id)
    return sum(int(prices[sym] * shares) for sym, (shares, _) in held.items() if sym in prices)


def change_since(db: Database, guild_id: int, symbol: str, since: float) -> float | None:
    """Percent change from the first recorded price after `since` to now."""
    history = db.stock_history(guild_id, symbol, since)
    if len(history) < 2:
        return None
    first, last = history[0][1], history[-1][1]
    return (last - first) / first * 100
