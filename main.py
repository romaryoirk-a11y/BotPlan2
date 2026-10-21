"""Точка входа: бот + планировщик напоминаний + health-сервер для Render."""
import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.config import BOT_TOKEN, WEB_PORT
from app.db import init_indexes
from app.bot import router as bot_router, run_bot, fire_due_reminders
from app.scheduler import scheduler_loop

log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан! Укажите переменную окружения BOT_TOKEN.")
    await init_indexes()
    tasks = [
        asyncio.create_task(run_bot()),
        asyncio.create_task(scheduler_loop(fire_due_reminders)),
    ]
    log.info("Started bot + scheduler on port %s", WEB_PORT)
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok", "service": "tg-reminder-bot"}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=WEB_PORT)
