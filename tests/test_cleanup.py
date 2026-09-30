import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import bot as bot_module
from kelpbot.cogs.cleanup import Cleanup, fmt_delay
from kelpbot.db import Database


def make_bot(default=120):
    fake = SimpleNamespace(db=Database(":memory:", 1000, auto_delete_default=default), _cleanup_tasks=set())
    fake.deleted = []
    message = MagicMock()
    message.delete = AsyncMock(side_effect=lambda: fake.deleted.append(True))
    fake.get_partial_messageable = lambda cid: SimpleNamespace(get_partial_message=lambda mid: message)
    fake._delete_later = lambda *a: bot_module.KelpBot._delete_later(fake, *a)
    fake.schedule_cleanup = lambda *a: bot_module.KelpBot.schedule_cleanup(fake, *a)
    return fake


def test_setting_defaults_and_override():
    db = Database(":memory:", 1000, auto_delete_default=120)
    assert db.auto_delete_seconds(1) == 120
    db.set_auto_delete_seconds(1, 0)
    db.set_auto_delete_seconds(2, 30)
    assert (db.auto_delete_seconds(1), db.auto_delete_seconds(2), db.auto_delete_seconds(3)) == (0, 30, 120)


def test_schedule_deletes_after_delay_and_respects_off():
    async def run():
        b = make_bot()
        b.db.set_auto_delete_seconds(1, 1)
        b.schedule_cleanup(1, 10, 20)
        b.db.set_auto_delete_seconds(2, 0)
        b.schedule_cleanup(2, 10, 21)
        assert len(b._cleanup_tasks) == 1
        await asyncio.sleep(1.1)
        return b

    b = asyncio.run(run())
    assert b.deleted == [True] and not b._cleanup_tasks


def _interaction(ephemeral):
    msg = SimpleNamespace(id=5, channel=SimpleNamespace(id=6), flags=SimpleNamespace(ephemeral=ephemeral))
    return SimpleNamespace(
        guild_id=1,
        response=SimpleNamespace(is_done=lambda: True),
        original_response=AsyncMock(return_value=msg),
    )


def test_listener_skips_ephemeral_and_manual_commands():
    b = make_bot()
    calls = []
    b.schedule_cleanup = lambda *a: calls.append(a)
    cog = Cleanup(b)
    normal = SimpleNamespace(extras={})
    manual = SimpleNamespace(extras={"manual_cleanup": True})
    asyncio.run(cog.on_app_command_completion(_interaction(False), normal))
    asyncio.run(cog.on_app_command_completion(_interaction(True), normal))
    asyncio.run(cog.on_app_command_completion(_interaction(False), manual))
    assert calls == [(1, 6, 5)]


def test_fmt_delay():
    assert [fmt_delay(s) for s in (0, 45, 120, 7200)] == ["off", "45s", "2m", "2h"]
