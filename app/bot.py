"""Telegram-бот напоминаний (aiogram 3) с уточнением GPS-локации."""
import logging
from datetime import datetime, timezone, timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, \
    ReplyKeyboardMarkup, KeyboardButton

from app.config import BOT_TOKEN, DEFAULT_TZ_OFFSET
from app.db import reminders_col, users_col
from app.parser import parse_datetime_ru, describe_due

log = logging.getLogger("bot")
router = Router()

GPS_REQUEST_BUTTON = KeyboardButton(text="📍 Отправить мою геолокацию", request_location=True)
MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Добавить"), KeyboardButton(text="📋 Список")],
        [GPS_REQUEST_BUTTON],
    ],
    resize_keyboard=True,
)


async def get_tz(user_id: int) -> int:
    u = await users_col.find_one({"user_id": user_id})
    return u.get("tz_offset", DEFAULT_TZ_OFFSET) if u else DEFAULT_TZ_OFFSET


# ---------- /start и помощь ----------
@router.message(CommandStart())
async def cmd_start(message: Message):
    await users_col.update_one(
        {"user_id": message.from_user.id},
        {"$setOnInsert": {"user_id": message.from_user.id, "tz_offset": DEFAULT_TZ_OFFSET}},
        upsert=True,
    )
    await message.answer(
        "👋 Привет! Я бот-напоминалка.\n\n"
        "Просто напиши мне текст с временем на русском, например:\n"
        '• "в 15:30 выпить таблетки"\n'
        '• "завтра в 9 утра позвонить маме"\n'
        '• "через 2 часа погулять"\n'
        '• "каждый день в 8:00 зарядка"\n\n'
        "Команды:\n"
        "/list — список напоминаний\n"
        "/timezone <часовой пояс> — часовой пояс (по умолчанию +3)\n"
        "/geo — напомнить, когда я приеду к точке (GPS)\n"
        "/cancel — отменить последнее действие\n"
        "/delete <№> — удалить напоминание",
        reply_markup=MAIN_KB,
    )


@router.message(F.text == "➕ Добавить")
async def kb_add(message: Message):
    await message.answer('Напиши напоминание с временем, например: "завтра в 10:00 встреча"')


@router.message(F.text == "📋 Список")
async def kb_list(message: Message):
    await show_list(message)


# ---------- Часовой пояс ----------
@router.message(Command("timezone"))
async def cmd_tz(message: Message):
    try:
        offset = int(message.text.split()[1])
        if not -12 <= offset <= 14:
            raise ValueError
    except (IndexError, ValueError):
        await message.answer("Формат: /timezone 3  (или -5, 5.5...)")
        return
    await users_col.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"tz_offset": offset}},
        upsert=True,
    )
    await message.answer(f"✅ Часовой пояс установлен: UTC{offset:+}")


# ---------- Создание напоминания из текста ----------
@router.message(F.text.func(lambda t: not t.startswith("/")))
async def handle_text(message: Message):
    user_id = message.from_user.id
    tz = await get_tz(user_id)
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    # режим ожидания текстового/гео напоминания после /geo
    u = await users_col.find_one({"user_id": user_id})
    pending_geo = u.get("pending_geo") if u else None

    due_utc, text = parse_datetime_ru(message.text, now_utc, tz)
    if due_utc is None and not pending_geo:
        await message.answer(
            "🤔 Не понял время. Напиши, например:\n"
            '"в 18:30 забрать посылку" или "через 30 минут позвонить"',
        )
        return

    if pending_geo:
        doc = {
            "user_id": user_id,
            "text": message.text,
            "type": "gps",
            "lat": pending_geo["lat"],
            "lon": pending_geo["lon"],
            "radius_m": pending_geo.get("radius_m", 300),
            "created_at": now_utc,
            "done": False,
        }
        await users_col.update_one({"user_id": user_id}, {"$unset": {"pending_geo": ""}})
    else:
        doc = {
            "user_id": user_id,
            "text": text or message.text,
            "type": "time",
            "due_at": due_utc,
            "repeat_daily": "каждый" in message.text.lower() or "ежедневно" in message.text.lower(),
            "created_at": now_utc,
            "done": False,
        }

    res = await reminders_col.insert_one(doc)
    num = res.inserted_id.generation_time  # не используем, id показывать коротко
    if doc["type"] == "gps":
        await message.answer(
            f"📍 Ок! Напомню «{doc['text']}», когда ты будешь в {int(doc['radius_m'])} м "
            f"от точки {doc['lat']:.5f}, {doc['lon']:.5f}."
        )
    else:
        when = describe_due(doc["due_at"], tz)
        repeat = " (каждый день)" if doc.get("repeat_daily") else ""
        await message.answer(f"✅ Напомню «{doc['text']}» — {when}{repeat}. №{_num(res.inserted_id)}")


def _num(oid) -> int:
    """Стабильный короткий номер из ObjectId (последние hex-цифры -> int)."""
    return int(str(oid)[-6:], 16) % 100000


# ---------- GPS ----------
@router.message(Command("geo"))
async def cmd_geo(message: Message):
    parts = message.text.split()
    radius = 300
    if len(parts) > 1:
        try:
            radius = max(50, int(parts[1]))
        except ValueError:
            pass
    await users_col.update_one(
        {"user_id": message.from_user.id},
        {"$set": {"pending_geo": {"lat": None, "lon": None, "radius_m": radius}}},
        upsert=True,
    )
    await message.answer(
        f"Хорошо. Радиус срабатывания: {radius} м.\n"
        "1) Нажми кнопку «📍 Отправить мою геолокацию», чтобы задать точку,\n"
        "2) затем пришли текст напоминания.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[GPS_REQUEST_BUTTON]], resize_keyboard=True
        ),
    )


@router.message(F.location & F.chat.type == "private")
async def handle_location(message: Message):
    user_id = message.from_user.id
    u = await users_col.find_one({"user_id": user_id})
    pending = u.get("pending_geo") if u else None
    loc = message.location

    if pending and pending.get("lat") is None:
        # это точка привязки напоминания
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"pending_geo.lat": loc.latitude, "pending_geo.lon": loc.longitude}},
        )
        await message.answer("📍 Точка сохранена. Теперь пришли текст напоминания.")
        return

    # обычная геолокация — проверяем gps-напоминания пользователя
    triggered = []
    query = {"user_id": user_id, "type": "gps", "done": False}
    async for r in reminders_col.find(query):
        dist = _distance_m(loc.latitude, loc.longitude, r["lat"], r["lon"])
        if dist <= r.get("radius_m", 300):
            triggered.append((r, dist))

    if triggered:
        kb_rows = []
        for r, dist in triggered:
            kb_rows.append([InlineKeyboardButton(
                text=f"✅ {r['text']}", callback_data=f"ack:{r['_id']}"
            )])
            await reminders_col.update_one({"_id": r["_id"]}, {"$set": {"last_seen": datetime.utcnow()}})
        await message.answer(
            "🔔 Ты рядом с местом напоминания!\n" +
            "\n".join(f"• {r['text']} (~{int(d)} м)" for r, d in triggered),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows),
        )
    else:
        await message.answer("Рядом нет мест из твоих GPS-напоминаний 👌")


def _distance_m(lat1, lon1, lat2, lon2) -> float:
    from math import radians, sin, cos, asin, sqrt
    R = 6371000
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * R * asin(sqrt(a))


# ---------- Список / удаление ----------
@router.message(Command("list"))
async def cmd_list(message: Message):
    await show_list(message)


async def show_list(message: Message):
    user_id = message.from_user.id
    tz = await get_tz(user_id)
    items = []
    async for r in reminders_col.find({"user_id": user_id, "done": False}).sort("created_at", 1):
        if r["type"] == "time":
            when = describe_due(r["due_at"], tz) + (" 🔁" if r.get("repeat_daily") else "")
        else:
            when = f"📍 {r['lat']:.5f},{r['lon']:.5f} (±{int(r.get('radius_m', 300))} м)"
        items.append(f"№{_num(r['_id'])} • {r['text']} — {when}")
    if not items:
        await message.answer("Пока пусто. Напиши, например: «завтра в 9 утра позвонить маме»")
    else:
        await message.answer("📋 Напоминания:\n" + "\n".join(items))


@router.message(Command("delete"))
async def cmd_delete(message: Message):
    try:
        num = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Формат: /delete 12345  (номер из /list)")
        return
    user_id = message.from_user.id
    matched = []
    async for r in reminders_col.find({"user_id": user_id, "done": False}):
        if _num(r["_id"]) == num:
            matched.append(r)
    if not matched:
        await message.answer("Не нашёл такое напоминание.")
        return
    await reminders_col.update_many({"_id": {"$in": [r["_id"] for r in matched]}},
                                    {"$set": {"done": True}})
    await message.answer(f"🗑 Удалено: {matched[0]['text']}")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    await users_col.update_one({"user_id": message.from_user.id}, {"$unset": {"pending_geo": ""}})
    await message.answer("Отменено ✅")


@router.callback_query(F.data.startswith("ack:"))
async def cb_ack(callback):
    from bson import ObjectId
    rid = callback.data.split(":", 1)[1]
    await reminders_col.update_one(
        {"_id": ObjectId(rid), "user_id": callback.from_user.id},
        {"$set": {"done": True}},
    )
    await callback.message.answer("Ок, напоминание снято 👍")
    await callback.answer()


# ---------- Scheduler: выдача временных напоминаний ----------
async def fire_due_reminders(bot: Bot):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    query = {"type": "time", "done": False, "due_at": {"$lte": now}}
    async for r in reminders_col.find(query):
        try:
            await bot.send_message(r["user_id"], f"⏰ Напоминание: {r['text']}")
        except Exception as e:
            log.warning("send failed for %s: %s", r["user_id"], e)
        if r.get("repeat_daily"):
            await reminders_col.update_one(
                {"_id": r["_id"]}, {"$set": {"due_at": r["due_at"] + timedelta(days=1)}}
            )
        else:
            await reminders_col.update_one({"_id": r["_id"]}, {"$set": {"done": True}})


async def run_bot():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    log.info("Bot started (long polling)")
    await dp.start_polling(bot)
