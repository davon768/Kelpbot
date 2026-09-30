"""Shop catalog and buy/sell rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from kelpbot.db import Database

SELL_BACK_PERCENT = 50


class Kind(Enum):
    PASSIVE = "Used up automatically"
    USABLE = "Use with /use"
    UPGRADE = "Permanent upgrade"
    PET = "Pet (permanent perk)"
    COLLECTIBLE = "Collectible"


@dataclass(frozen=True)
class Item:
    key: str
    name: str
    emoji: str
    price: int
    kind: Kind
    description: str
    max_owned: int | None = None

    @property
    def label(self) -> str:
        return f"{self.emoji} {self.name}"

    @property
    def sell_price(self) -> int:
        return self.price * SELL_BACK_PERCENT // 100


PADLOCK = Item("padlock", "Padlock", "🔒", 800, Kind.PASSIVE,
               "Stops the next robbery against you. Breaks when it does.", max_owned=3)
CROWBAR = Item("crowbar", "Crowbar", "🪓", 600, Kind.PASSIVE,
               "+25% success chance on your next /rob. Used up on the attempt.", max_owned=5)
ENERGY_DRINK = Item("energy_drink", "Energy Drink", "🥤", 250, Kind.USABLE,
                    "Resets your /work cooldown so you can work again right away.")
LAPTOP = Item("laptop", "Laptop", "💻", 7_500, Kind.UPGRADE,
              "Permanently earn 50% more from /work.", max_owned=1)
TROPHY = Item("trophy", "Golden Trophy", "🏆", 25_000, Kind.COLLECTIBLE, "Proof you've made it. Does nothing.")
SPORTS_CAR = Item("sports_car", "Sports Car", "🏎️", 100_000, Kind.COLLECTIBLE, "Goes fast. Mostly for showing off.")
YACHT = Item("yacht", "Kelp Yacht", "🛥️", 500_000, Kind.COLLECTIBLE, "The ultimate flex.")

CAT = Item("cat", "Cat", "🐱", 5_000, Kind.PET, "+10% pay from /work.", max_owned=1)
PARROT = Item("parrot", "Parrot", "🦜", 6_000, Kind.PET, "+10% from /daily.", max_owned=1)
DOG = Item("dog", "Guard Dog", "🐶", 8_000, Kind.PET, "Robberies against you are 15% less likely to succeed.",
           max_owned=1)
TURTLE = Item("turtle", "Turtle", "🐢", 12_000, Kind.PET, "+1% daily bank interest.", max_owned=1)
OCTOPUS = Item("octopus", "Octopus", "🐙", 20_000, Kind.PET, "/work cooldown is 15 minutes shorter.", max_owned=1)
DRAGON = Item("dragon", "Dragon", "🐉", 250_000, Kind.PET, "Legendary. No perk, just glory.", max_owned=1)
PETS = (CAT, PARROT, DOG, TURTLE, OCTOPUS, DRAGON)

ITEMS: dict[str, Item] = {
    i.key: i for i in (PADLOCK, CROWBAR, ENERGY_DRINK, LAPTOP, *PETS, TROPHY, SPORTS_CAR, YACHT)
}

CROWBAR_BONUS = 0.25


class TradeResult(Enum):
    OK = "ok"
    UNKNOWN_ITEM = "unknown_item"
    CANT_AFFORD = "cant_afford"
    MAX_OWNED = "max_owned"
    NOT_OWNED = "not_owned"


def buy(db: Database, guild_id: int, user_id: int, key: str, quantity: int = 1) -> TradeResult:
    item = ITEMS.get(key)
    if item is None or quantity < 1:
        return TradeResult.UNKNOWN_ITEM
    if item.max_owned is not None and db.item_count(guild_id, user_id, key) + quantity > item.max_owned:
        return TradeResult.MAX_OWNED
    if not db.try_debit(guild_id, user_id, item.price * quantity):
        return TradeResult.CANT_AFFORD
    db.add_item(guild_id, user_id, key, quantity)
    return TradeResult.OK


def sell(db: Database, guild_id: int, user_id: int, key: str, quantity: int = 1) -> TradeResult:
    item = ITEMS.get(key)
    if item is None or quantity < 1:
        return TradeResult.UNKNOWN_ITEM
    if not db.remove_item(guild_id, user_id, key, quantity):
        return TradeResult.NOT_OWNED
    db.credit(guild_id, user_id, item.sell_price * quantity)
    return TradeResult.OK
