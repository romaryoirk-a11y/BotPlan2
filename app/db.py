from motor.motor_asyncio import AsyncIOMotorClient

from app.config import MONGO_URI, MONGO_DB

_client = AsyncIOMotorClient(MONGO_URI)
db = _client[MONGO_DB]

reminders_col = db.reminders   # напоминания пользователей
users_col = db.users           # настройки пользователей (tz, gps-разрешение и т.п.)


async def init_indexes():
    await reminders_col.create_index([("user_id", 1), ("due_at", 1)])
    await reminders_col.create_index([("done", 1), ("due_at", 1)])
    await users_col.create_index("user_id", unique=True)
