"""Парсинг текста напоминания на русском языке: время + текст.

Поддерживаемые форматы (время в часах/минутах пользователя):
  - "в 15:30 выпить таблетки"
  - "завтра в 9 утра позвонить маме"
  - "сегодня вечером в 20:00 ..."
  - "через 2 часа гулять"
  - "каждый день в 8:00 зарядка"   (повторяющееся)
"""
import re
from datetime import datetime, timedelta, timezone

WORD_NUMS = {
    "один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9,
    "десять": 10, "одиннадцать": 11, "двенадцать": 12,
    "полтора": 1.5, "полчас": 0.5, "полчаса": 0.5,
}

PERIOD_WORDS = {
    "утра": 6,          # "9 утра" -> 09:00
    "дня": 13,          # "3 дня" -> 15:00
    "вечера": 19,       # "8 вечера" -> 20:00
    "ночи": 23,         # "1 ночи" -> 01:00
}


def parse_datetime_ru(text: str, now_utc: datetime, tz_offset: int):
    """Возвращает (due_at_utc: datetime, cleaned_text: str) или (None, text)."""
    user_now = now_utc + timedelta(hours=tz_offset)
    low = text.lower()

    # --- через N (часов/минут/дней) ---
    m = re.search(r"(?:через)\s+(\d+|[а-я]+)\s*(час|часа|часов|минут\w*|мин\w*|дн\w*|сут\w*)", low)
    if m:
        num_raw, unit = m.groups()
        num = WORD_NUMS.get(num_raw)
        if num_raw.isdigit():
            num = int(num_raw)
        if num is not None:
            if unit.startswith("час"):
                delta = timedelta(hours=num)
            elif unit.startswith("мин"):
                delta = timedelta(minutes=num)
            else:
                delta = timedelta(days=num)
            due_user = user_now + delta
            cleaned = _cut(text, m.start(), m.end())
            return _to_utc(due_user, tz_offset), cleaned

    repeat = bool(re.search(r"каждый\s+(день|утро|вечер)|ежедневно", low))

    # --- день: сегодня / завтра / послезавтра ---
    day_shift = 0
    day_m = re.search(r"(послезавтра|завтра|сегодня)", low)
    if day_m:
        day_shift = {"сегодня": 0, "завтра": 1, "послезавтра": 2}[day_m.group(1)]

    # --- время: HH:MM или "N часов/минут" + период ---
    time_m = re.search(r"(\d{1,2})[:.](\d{2})", low)
    hour = minute = None
    span = None
    if time_m:
        hour, minute = int(time_m.group(1)), int(time_m.group(2))
        span = (time_m.start(), time_m.end())
        # слово "в" перед временем тоже вырезаем
        prefix = low[:time_m.start()].rstrip()
        if prefix.endswith(" в") or prefix.endswith("во"):
            cut_from = prefix.rfind("в")
            span = (cut_from, time_m.end())
    else:
        time_m2 = re.search(r"\b(\d{1,2})\s*(час[аов]?|утра|дня|вечера|ночи)?(?:\s*(\d{1,2})\s*(минут\w*|мин)?)?", low)
        # ищем число рядом с "в N"
        time_m2 = re.search(r"(?:в\s+)?\b(\d{1,2})\b\s*(утра|дня|вечера|ночи|час[аов]?|минут\w*|мин)?", low)
        if time_m2 and time_m2.group(1):
            n = int(time_m2.group(1))
            word = time_m2.group(2) or ""
            if word.startswith("мин"):
                hour, minute = 0, n
                span = (time_m2.start(), time_m2.end())
            elif word.startswith("час"):
                hour, minute = n % 24, 0
                span = (time_m2.start(), time_m2.end())
            elif word in PERIOD_WORDS:
                base = PERIOD_WORDS[word]
                hour = (base // 12) * 12 + n if base != 23 else (n if n <= 5 else n)
                if word == "ночи":
                    hour = n if n < 6 else (n - 12 if n > 12 else n)
                if word == "дня" and n <= 12:
                    hour = n + 12 if n < 12 else 12
                if word == "вечера" and n <= 12:
                    hour = n + 12 if n < 12 else 12
                if word == "утра":
                    hour = n if n != 12 else 0
                minute = 0
                span = (max(0, time_m2.start() - (2 if "в " in low[time_m2.start():time_m2.start()+2] else 0)), time_m2.end())
            elif n <= 23 and (day_m or repeat):
                hour, minute = n, 0
                span = (time_m2.start(), time_m2.end())

    if hour is None:
        # явный HH:MM без даты — если время уже прошло, переносим на завтра
        if time_m:
            due_user = user_now.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)
            if due_user <= user_now and not repeat:
                due_user += timedelta(days=1)
            cleaned = _cut(text, span[0], span[1])
            cleaned = re.sub(r"^[\s,.]*(?:сегодня|завтра)?[\s,]*", "", cleaned, flags=re.I)
            return _to_utc(due_user, tz_offset), cleaned
        return None, text

    target_date = (user_now + timedelta(days=day_shift)).date()
    try:
        due_user = datetime(target_date.year, target_date.month, target_date.day,
                            hour % 24, minute, tzinfo=user_now.tzinfo)
    except ValueError:
        return None, text

    if not repeat and due_user <= user_now:
        if day_m and day_m.group(1) == "сегодня":
            due_user += timedelta(days=1)
        elif not day_m:
            due_user += timedelta(days=1)

    cleaned = text
    if span:
        s, e = span
        if s >= 2 and text[s-2:s].lower().strip() in ("в", "во"):
            s -= 2
        cleaned = text[:s] + text[e:]
    if day_m:
        cleaned = cleaned[:day_m.start()] + cleaned[day_m.end():]
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ,.")
    return _to_utc(due_user, tz_offset), cleaned


def _to_utc(user_dt: datetime, tz_offset: int) -> datetime:
    return user_dt.replace(tzinfo=None) - timedelta(hours=tz_offset)


_FILLER_RE = re.compile(
    r"^\s*(?:[,.]\s*)?(?:а|и|то|ну|пожалуйста|напомни(?:ть)?(?: мне)?|мне)\b[\s,.]*",
    re.I,
)


def _strip_fillers(text: str) -> str:
    prev = None
    while prev != text:
        prev = text
        text = _FILLER_RE.sub("", text).strip()
    return text


def _cut(text: str, start: int, end: int) -> str:
    if start >= 2 and text[start-2:start].lower().strip() in ("в", "во"):
        start -= 2
    res = (text[:start] + text[end:]).strip(" ,.")
    res = re.sub(r"^(?:сегодня|завтра|послезавтра)[\s,]*", "", res, flags=re.I)
    return _strip_fillers(res)


def describe_due(due_utc: datetime, tz_offset: int) -> str:
    user_dt = due_utc + timedelta(hours=tz_offset)
    days = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    return f"{user_dt.strftime('%d.%m.%Y (%A) %H:%M')}".replace("%A", days[user_dt.weekday()])
