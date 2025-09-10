"""
helpers.py
===========
Вспомогательные функции для работы бота:
- загрузка/сохранение ID пользователей;
- работа с blacklist и declined;
- парсинг сообщений и эмбедов;
- вычисление баллов анкеты;
- вспомогательные утилиты.
"""

import discord
import os
import json
import re

from configuration import (
    TARGET_CHANNEL_ID,
    CONFIG_PATH,
    DECLINED_FILE,
    BLACKLIST_CHANNEL_ID,
)

# -------------------- Глобальные переменные --------------------
blacklist_ids: set[str] = set()


# -------------------- Работа с конфигами --------------------
def load_config():
    """
    Загружает JSON-конфиг из CONFIG_PATH.
    Если файла нет → исключение.
    """
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(
            f"❌ Файл {CONFIG_PATH} не найден! Создай config.json рядом с exe"
        )

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# -------------------- Работа с ID --------------------
def load_ids(filename: str) -> set[str]:
    """
    Загружает список ID из файла в множество.
    Если файла нет → возвращает пустое множество.
    """
    if not os.path.exists(filename):
        return set()
    with open(filename, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def save_id(filename: str, uid: int):
    """
    Добавляет ID в конец файла.
    """
    with open(filename, "a", encoding="utf-8") as f:
        f.write(f"{uid}\n")


def is_blacklisted(uid: int) -> bool:
    """
    Проверяет, находится ли пользователь в blacklist.
    """
    blocked = str(uid) in blacklist_ids
    print(f"[DEBUG] Проверка ЧС для {uid}: {blocked}")
    return blocked


def is_declined(uid: int) -> bool:
    """
    Проверяет, отклонялся ли пользователь ранее.
    """
    declined = load_ids(DECLINED_FILE)
    was = str(uid) in declined
    print(f"[DEBUG] Проверка отклонённых для {uid}: {was}")
    return was


# -------------------- Blacklist из канала --------------------
async def load_blacklist_from_channel(bot):
    """
    Загружает ID из канала ЧС (поиск чисел в сообщениях).
    """
    print("✅ Загружаем ID из канала ЧС")
    global blacklist_ids
    channel = bot.get_channel(BLACKLIST_CHANNEL_ID)
    if channel is None:
        print(f"❌ Канал ЧС {BLACKLIST_CHANNEL_ID} не найден")
        return set()

    ids = set()
    async for msg in channel.history(limit=1000):  # лимит можно увеличить
        if msg.content:
            found = re.findall(r"\b\d{17,20}\b", msg.content)
            ids.update(found)

    blacklist_ids = ids
    print(f"✅ Загружено {len(ids)} ID из канала ЧС")
    return ids


# -------------------- Работа с сообщениями --------------------
async def fetch_app_message(bot, msg_id):
    """
    Возвращает объект сообщения анкеты по ID.
    Если сообщение не найдено → None.
    """
    if not msg_id:
        return None
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel is None:
        return None
    try:
        return await channel.fetch_message(msg_id)
    except Exception:
        return None


def calculate_score(answers):
    """
    Подсчёт баллов по ответам анкеты.
    Правила берутся из config.json → "SCORES".
    """
    config = load_config()
    SCORES = config.get("SCORES", {})

    def score_for(cat, idx):
        if idx < len(answers):
            return SCORES.get(cat, {}).get(answers[idx], 0)
        return 0

    score = 0
    score += score_for("age", 1)
    score += score_for("exp", 2)
    score += score_for("gov", 3)
    score += score_for("senior", 4)
    score += score_for("senior_time", 5)
    return score


def parse_discord_tag(tag: str):
    """
    Парсит Discord-тег и возвращает ID пользователя.
    Поддерживает:
    - упоминание <@123>;
    - упоминание <@!123>;
    - просто число (ID).
    """
    if not tag:
        return None
    m = re.search(r"<@!?(?P<id>\d+)>", tag)
    if m:
        return int(m.group("id"))
    if tag.isdigit():
        return int(tag)
    return None


def extract_lines(message: discord.Message):
    """
    Разбивает сообщение (и его эмбеды) на строки.
    Возвращает список строк без пустых.
    """
    lines = []
    if message.content:
        lines.extend(message.content.splitlines())
    if message.embeds:
        for embed in message.embeds:
            if embed.description:
                lines.extend(embed.description.splitlines())
            for field in embed.fields:
                # Добавляем и вопрос (name), и ответ (value)
                if field.name:
                    lines.extend(field.name.splitlines())
                if field.value:
                    lines.extend(field.value.splitlines())
    return [line.strip() for line in lines if line.strip()]


async def get_next_index(index, answers):
    """
    Логика перехода к следующему вопросу.
    Если ответ "Нет" — некоторые вопросы пропускаются.
    """
    index += 1
    if index == 4 and answers[3] == "Нет":
        index += 2
    elif index == 5 and answers[4] == "Нет":
        index += 1
    return index
