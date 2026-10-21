"""Фоновый планировщик: раз в интервал проверяет просроченные напоминания."""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot

log = logging.getLogger("scheduler")

CHECK_INTERVAL_SEC = 30


async def scheduler_loop(fire_fn):
    """fire_fn(bot) — корутина, которая выбирает и отправляет due-напоминания."""
    from app.config import BOT_TOKEN
    bot = Bot(BOT_TOKEN)
    log.info("Scheduler started (interval=%ss)", CHECK_INTERVAL_SEC)
    try:
        while True:
            try:
                await fire_fn(bot)
            except Exception as e:
                log.exception("scheduler tick failed: %s", e)
            await asyncio.sleep(CHECK_INTERVAL_SEC)
    finally:
        await bot.session.close()
