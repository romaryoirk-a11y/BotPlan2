import os

# Токен бота выдаётся BotFather'ом
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Строка подключения к MongoDB (Atlas)
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "tg_reminder_bot")

# Часовой пояс по умолчанию для пользователей без tz_offset
DEFAULT_TZ_OFFSET = int(os.getenv("DEFAULT_TZ_OFFSET", "3"))  # МСК

# Порт для web-хелсинга на Render
WEB_PORT = int(os.getenv("PORT", "8080"))
