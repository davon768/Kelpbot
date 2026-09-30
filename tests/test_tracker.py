import itertools
from types import SimpleNamespace

import discord
import pytest

from conftest import GUILD, FakeInteraction, FakeMember, call
from kelpbot import achievements, config, settings, tracker
from kelpbot.cogs import tracker as tracker_cog
from kelpbot.db import Database
from kelpbot.gambling import is_highlight, settle

NOW = 1_790_000_000.0  # a fixed moment so "today" is stable
_ids = itertools.count(5000)


def make():
    return Database(":memory:", starting_balance=1000)


def text(embeds):
    out = []
    for e in embeds:
        out += [e.title or "", e.description or ""] + [f"{f.name}\n{f.value}" for f in e.fields]
    return "\n".join(out)


# ---- rendering ---------------------------------------------------------------------

def test_empty_server_renders_friendly_placeholders():
    db = make()
    body = text(tracker.render(db, GUILD, settings.load(db, GUILD), "Kelp", NOW))
    assert "Kelp Tracker" in body
    assert "No games yet today" in body and "Nothing yet" in body and "Nobody yet" in body


def test_today_highlights():
    db = make()
    start = tracker.day_start(NOW)
    db.log_game(GUILD, 1, "crash", 100, 3000, ts=start + 10)   # +2900, 30x
    db.log_game(GUILD, 2, "slots", 5000, 0, ts=start + 20)     # biggest loss
    db.log_game(GUILD, 2, "dice", 100, 196, ts=start + 30)
    db.log_game(GUILD, 3, "mines", 100, 0, ts=start - 100)     # yesterday
    db.log_game(GUILD, 3, "mines", 100, 900, ts=start - 50)    # yesterday's top earner
    db.add_event(GUILD, "rob", 4, 250, other_id=1, ts=start + 40)
    body = tracker.today_embed(db, GUILD, settings.load(db, GUILD), NOW).description
    assert "**3 games**" in body and "5,200 wagered" in body and "house is up" in body
    assert "Biggest win: <@1> **+🪙 2,900** on crash" in body
    assert "Luckiest hit: <@1> **30.0x**" in body
    assert "Biggest loss: <@2> lost 🪙 5,000 on slots" in body
    assert "Most active: <@2> (2 games)" in body
    assert "1 robbery**, 🪙 250 stolen" in body
    assert "Yesterday's top earner: <@3> +🪙 700" in body


def test_history_lines_for_every_event_kind():
    db = make()
    cfg = settings.load(db, GUILD)
    db.add_event(GUILD, "big_win", 1, 4000, amount2=1000, detail="crash", ts=NOW - 9)
    db.add_event(GUILD, "rob", 2, 300, other_id=1, ts=NOW - 8)
    db.add_event(GUILD, "lottery", 3, 9000, amount2=90, ts=NOW - 7)
    db.add_event(GUILD, "duel", 1, 500, other_id=2, ts=NOW - 6)
    db.add_event(GUILD, "achievement", 2, 5000, detail="jackpot", ts=NOW - 5)
    db.add_event(GUILD, "weekly", 3, 12000, amount2=5000, ts=NOW - 4)
    db.add_event(GUILD, "season", 1, 80000, amount2=2, ts=NOW - 3)
    db.add_event(GUILD, "role", 2, 1000, other_id=77, ts=NOW - 2)
    db.add_event(GUILD, "mystery", 2, ts=NOW - 1)  # unknown kinds are skipped
    body = tracker.history_embed(db, GUILD, cfg, NOW).description
    for snippet in ["won **🪙 4,000** on crash (5.0x)", "<@2> robbed <@1>", "won the lottery", "in a 🪙 500 duel",
                    "unlocked **Jackpot!**", "won the week", "Season 2 ended", "bought <@&77>"]:
        assert snippet in body
    assert body.index("bought") < body.index("robbed")  # newest first
    assert "mystery" not in body


def test_seven_day_sparkline():
    db = make()
    start = tracker.day_start(NOW)
    for days_ago, games in [(6, 1), (1, 4), (0, 8)]:
        for _ in range(games):
            db.log_game(GUILD, 1, "dice", 10, 0, ts=start - days_ago * tracker.DAY + 5)
    field = tracker.history_embed(db, GUILD, settings.load(db, GUILD), NOW).fields[0].value
    assert "13 games" in field and field.startswith("`▁") and "█`" in field
    assert tracker.sparkline([0, 0]) == "▁▁" and tracker.sparkline([1, 2])[-1] == "█"


def test_fingerprint_ignores_timestamp_but_not_content():
    db = make()
    cfg = settings.load(db, GUILD)
    a = tracker.render(db, GUILD, cfg, "X", NOW)
    b = tracker.render(db, GUILD, cfg, "X", NOW)
    b[-1].timestamp = discord.utils.utcnow()
    assert tracker.fingerprint(a) == tracker.fingerprint(b)
    db.log_game(GUILD, 1, "dice", 10, 0, ts=NOW)
    assert tracker.fingerprint(tracker.render(db, GUILD, cfg, "X", NOW)) != tracker.fingerprint(a)


def test_fits_discord_limits_with_busy_server():
    db = make()
    for uid in range(1, 40):
        db.credit(GUILD, uid, uid * 1_000_000)
        db.log_game(GUILD, uid, "higher or lower", 50_000, 50_000_000, ts=NOW - 5)
        db.add_event(GUILD, "big_win", uid, 49_950_000, amount2=50_000, detail="higher or lower", ts=NOW - 5)
    embeds = tracker.render(db, GUILD, settings.load(db, GUILD), "A" * 90, NOW)
    assert sum(len(e) for e in embeds) < 6000 and len(embeds) <= 10
    assert all(len(f.value) <= 1024 for e in embeds for f in e.fields)
    assert all(len(e.description or "") <= 4096 for e in embeds)


# ---- recording -----------------------------------------------------------------------

def test_highlight_rules():
    assert is_highlight(100, 100 + config.HISTORY_BIG_WIN_PROFIT)
    assert is_highlight(100, 1000)            # 10x with 900 profit
    assert not is_highlight(10, 100)          # 10x but tiny
    assert not is_highlight(1000, 2000)       # 2x, 1,000 profit


def test_settle_logs_games_and_big_wins():
    db = make()
    fake_bot = SimpleNamespace(db=db, cfg=lambda gid: settings.load(db, gid), log_event=lambda *a: None)
    settle(fake_bot, GUILD, 1, 100, 0, "slots")
    settle(fake_bot, GUILD, 1, 100, 5000, "crash")
    assert db.game_totals(GUILD, 0, 2e10) == (2, 200, 5000)
    kinds = [e.kind for e in db.recent_events(GUILD)]
    assert "big_win" in kinds and "achievement" in kinds  # first win achievement too


def test_achievement_unlock_is_recorded():
    db = make()
    achievements.unlock(db, GUILD, 1, "duelist")
    achievements.unlock(db, GUILD, 1, "duelist")
    assert [(e.kind, e.detail) for e in db.recent_events(GUILD)] == [("achievement", "duelist")]


def test_history_is_pruned():
    db = make()
    db.log_game(GUILD, 1, "dice", 10, 0, ts=100.0)
    db.add_event(GUILD, "rob", 1, ts=100.0)
    db.log_game(GUILD, 1, "dice", 10, 0, ts=NOW)
    db.prune_history(1000.0)
    assert db.game_totals(GUILD, 0, 2e10)[0] == 1 and db.recent_events(GUILD) == []


# ---- the live message -----------------------------------------------------------------

class FakeChannel:
    def __init__(self):
        self.messages = {}  # id -> list of embed snapshots
        self.deleted = []
        self.edits = 0

    def send(self, embeds, **kw):
        async def _send():
            mid = next(_ids)
            self.messages[mid] = embeds
            return SimpleNamespace(id=mid)
        return _send()

    def get_partial_message(self, mid):
        channel = self

        class Partial:
            async def edit(self, embeds, **kw):
                if mid not in channel.messages:
                    raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Message")
                channel.messages[mid] = embeds
                channel.edits += 1

            async def delete(self):
                channel.messages.pop(mid, None)
                channel.deleted.append(mid)

        return Partial()


@pytest.fixture
def live(kb):
    channel = FakeChannel()
    kb.get_partial_messageable = lambda cid: channel
    cog = kb.get_cog("Tracker")
    return kb, cog, channel


def tracker_id(kb):
    return int(kb.db.config(GUILD).get(tracker.MESSAGE_KEY, 0))


def test_set_channel_posts_once_then_edits_only_on_change(live):
    kb, cog, channel = live
    kb.run(cog.move(GUILD, 0, 42))
    first = tracker_id(kb)
    assert list(channel.messages) == [first] and kb.cfg(GUILD).tracker_channel_id == 42
    kb.run(cog.refresh(GUILD))
    assert channel.edits == 0  # nothing changed
    kb.db.log_game(GUILD, 1, "dice", 10, 0)
    kb.run(cog.refresh(GUILD))
    assert channel.edits == 1 and tracker_id(kb) == first


def test_deleted_tracker_comes_back_on_next_tick(live):
    kb, cog, channel = live
    kb.run(cog.move(GUILD, 0, 42))
    old = tracker_id(kb)
    channel.messages.pop(old)
    kb.run(cog.on_raw_message_delete(SimpleNamespace(guild_id=GUILD, channel_id=42, message_id=old)))
    kb.run(cog.refresh(GUILD))
    assert tracker_id(kb) not in (0, old) and tracker_id(kb) in channel.messages


def test_missing_tracker_detected_when_editing(live):
    kb, cog, channel = live
    kb.run(cog.move(GUILD, 0, 42))
    channel.messages.clear()  # deleted while the bot was offline, say
    kb.db.log_game(GUILD, 1, "dice", 10, 0)
    kb.run(cog.refresh(GUILD))
    assert tracker_id(kb) in channel.messages


def buried_by(kb, cog, count, seconds_ago):
    for _ in range(count):
        msg = SimpleNamespace(id=next(_ids), guild=SimpleNamespace(id=GUILD), channel=SimpleNamespace(id=42))
        kb.run(cog.on_message(msg))
    cog.last_activity[GUILD] -= seconds_ago


def test_reposts_at_bottom_when_buried_and_quiet(live):
    kb, cog, channel = live
    kb.run(cog.move(GUILD, 0, 42))
    old = tracker_id(kb)
    buried_by(kb, cog, tracker_cog.BURIED_AFTER, seconds_ago=0)
    kb.run(cog.refresh(GUILD))
    assert tracker_id(kb) == old  # chat is still active: leave it alone
    cog.last_activity[GUILD] -= tracker_cog.QUIET_SECONDS
    kb.run(cog.refresh(GUILD))
    assert tracker_id(kb) != old and old in channel.deleted and cog.buried[GUILD] == 0


def test_deleted_chat_messages_dont_count_as_burying(live):
    kb, cog, _ = live
    kb.run(cog.move(GUILD, 0, 42))
    buried_by(kb, cog, tracker_cog.BURIED_AFTER, seconds_ago=tracker_cog.QUIET_SECONDS)
    kb.run(cog.on_raw_bulk_message_delete(SimpleNamespace(guild_id=GUILD, channel_id=42, message_ids=[1, 2, 3])))
    old = tracker_id(kb)
    kb.run(cog.refresh(GUILD))
    assert tracker_id(kb) == old


def test_messages_in_other_channels_are_ignored(live):
    kb, cog, _ = live
    kb.run(cog.move(GUILD, 0, 42))
    msg = SimpleNamespace(id=1, guild=SimpleNamespace(id=GUILD), channel=SimpleNamespace(id=99))
    kb.run(cog.on_message(msg))
    assert cog.buried.get(GUILD, 0) == 0


def test_clearing_the_channel_removes_the_tracker(live):
    kb, cog, channel = live
    kb.run(cog.move(GUILD, 0, 42))
    kb.run(cog.move(GUILD, 42, None))
    assert channel.messages == {} and tracker_id(kb) == 0 and kb.cfg(GUILD).tracker_channel_id == 0


def test_settings_channel_command(live):
    kb, _, channel = live
    admin = FakeMember(9)
    target = SimpleNamespace(
        id=42, mention="<#42>",
        permissions_for=lambda me: SimpleNamespace(view_channel=True, send_messages=True, embed_links=True),
    )
    it = call(kb, "settings channel", admin, kind="tracker", channel=target)
    assert "tracker is live" in it.followups[-1].content and len(channel.messages) == 1
    it = call(kb, "settings channel", admin, kind="tracker", channel=None)
    assert "removed" in it.followups[-1].content and channel.messages == {}


def test_cleanup_never_deletes_the_tracker(live):
    kb, cog, _ = live
    kb.run(cog.move(GUILD, 0, 42))
    kb._connection.user = SimpleNamespace(id=999)
    bot_msgs = [SimpleNamespace(id=tracker_id(kb), author=SimpleNamespace(id=999)),
                SimpleNamespace(id=1, author=SimpleNamespace(id=999)),
                SimpleNamespace(id=2, author=SimpleNamespace(id=5))]

    async def purge(limit, check, bulk):
        return [m for m in bot_msgs if check(m)]

    it = FakeInteraction(FakeMember(9))
    it.channel = SimpleNamespace(purge=purge, permissions_for=lambda me: SimpleNamespace(manage_messages=True))
    it.guild.me = SimpleNamespace()
    cmd = kb.tree.get_command("cleanup")
    kb.run(cmd.callback(cmd.binding, it, scan=100))
    assert "Deleted **1**" in it.followups[-1].content
