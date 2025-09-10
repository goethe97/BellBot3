"""
Discord HR Bot
==============
Основной файл для запуска бота.

Функционал:
- обработка заявок кандидатов в Discord (анкеты, вопросы/ответы);
- восстановление незавершённых анкет при перезапуске;
- проверка дедлайнов;
- логика диалога в ЛС с пользователями и реакциями
"""

import discord
from discord.ext import commands
from dotenv import load_dotenv
import sys
import os
import asyncio


# Импорты из модулей (cogs)
from cogs.deadlines import check_deadlines
from cogs.applications import (
    questions,
    load_progress,
    save_progress,
    finish_form,
    ask_question,
    process_application_message,
    user_progress,
)

from cogs.helpers import (
    fetch_app_message,
    extract_lines,
    get_next_index,
    load_blacklist_from_channel,
)
from configuration import (
    GUILD_ID,
    TARGET_CHANNEL_ID,
    REVIEW_ROLES,
    CONFIG_PATH,
)

# Глобальная блокировка для работы с прогрессом
progress_lock = asyncio.Lock()

# Загружаем токен из .env
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Определяем базовую директорию (exe или py)
if getattr(sys, "frozen", False):  # если exe
    BASE_DIR = os.path.dirname(sys.executable)
else:  # если py
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# Настройка intents для работы с контентом сообщений, реакциями и участниками
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

# Создание экземпляра бота
bot = commands.Bot(command_prefix="!", intents=intents)

# Проверяем наличие конфига
if not os.path.exists(CONFIG_PATH):
    raise FileNotFoundError(
        f"❌ Файл {CONFIG_PATH} не найден! Создай config.json рядом с exe"
    )


# -------------------- События --------------------
@bot.event
async def on_ready():
    """
    Событие при запуске бота.
    - Загружает blacklist
    - Восстанавливает прогресс анкет
    - Напоминает пользователям о незавершённых анкетах
    - Проверяет дедлайны
    """
    global user_progress  # ⬅️ вот тут "съехал" отступ (скорее всего таб, а не 4 пробела)

    # Загружаем чёрный список
    await load_blacklist_from_channel(bot)

    # загружаем сохранённый прогресс
    user_progress = await load_progress()

    # восстановление незавершённых анкет
    for uid, entry in list(user_progress.items()):
        index = entry.get("index", 0)
        if index < len(questions):  # анкета не завершена
            try:
                user = await bot.fetch_user(uid)
                print(f"⏩ У {user} есть незавершённая анкета (вопрос {index + 1})")

                dm = user.dm_channel or await user.create_dm()
                await dm.send(
                    f"📌 У вас есть незавершённая анкета. "
                    f"Вы остановились на вопросе {index + 1}. "
                    f"Просто ответьте на сообщение-анкеты реакцией."
                )

            except Exception as e:
                print(f"⚠️ Ошибка восстановления анкеты {uid}: {e}")
                user_progress.pop(uid, None)

    await save_progress()
    print(f"✅ Logged in as {bot.user}")

    # Проверяем канал с анкетами (ищем новые сообщения без реакций)
    guild = bot.get_guild(GUILD_ID)
    if guild is None:
        return
    channel = bot.get_channel(TARGET_CHANNEL_ID)
    if channel is None:
        return

    async for message in channel.history(limit=10):
        if message.reactions:
            continue
        full_text = message.content or ""
        if message.embeds:
            embed = message.embeds[0]
            if embed.description:
                full_text += "\n" + embed.description
            for field in embed.fields:
                full_text += f"\n{field.name}\n{field.value}"

        if "Ваш DISCORD" in full_text:
            await process_application_message(bot, message)

    # Проверяем дедлайны
    try:
        await check_deadlines(bot, GUILD_ID, REVIEW_ROLES)
    except Exception as e:
        print(f"⚠️ Ошибка при проверке дедлайнов: {e}")


@bot.event
async def on_message(message):
    """
    Обработчик всех входящих сообщений.
    Логика:
      1. Сообщения в канале заявок → запуск обработки анкеты.
      2. Сообщения в личке (DM) → продолжение диалога по анкете.
    """
    global user_progress

    # Игнорируем свои же сообщения
    if message.author == bot.user:
        return

    # ==============================
    # === Сообщения в канале заявок
    # ==============================
    if message.channel.id == TARGET_CHANNEL_ID:
        lines = extract_lines(message)

        # Проверяем, содержит ли сообщение признаки анкеты
        if any("ваш discord" in line.lower() for line in lines):
            await process_application_message(bot, message)
        return

    # ==============================
    # === Сообщения в личке (DM)
    # ==============================
    if isinstance(message.channel, discord.DMChannel):
        uid = message.author.id

        # Загружаем прогресс пользователя (если его ещё нет в памяти)
        if uid not in user_progress:
            loaded = await load_progress()
            user_progress.update(loaded)

            # Если анкета всё ещё не найдена — игнорируем сообщение
            if uid not in user_progress:
                return

        # Обновляем прогресс из файла (актуализация)
        user_progress = await load_progress()
        entry = user_progress[uid]

        answers = entry.get("answers", [])
        index = entry.get("index", 0)

        # Проверяем, не вышел ли индекс за пределы списка вопросов
        if index >= len(questions):
            return

        q = questions[index]

        # ==============================
        # === Текстовый вопрос
        # ==============================
        if not q.get("options"):  # если вопрос без вариантов ответа
            answers.append(message.content)

            # Переходим к следующему вопросу
            new_index = await get_next_index(index, answers)

            # Защита от зацикливания: если индекс не изменился — двигаем вручную
            if new_index <= index:
                new_index = index + 1

            entry["index"] = new_index
            entry["answers"] = answers

            # --- Есть ещё вопросы → задаём следующий
            if new_index < len(questions):
                try:
                    new_qmsg = await ask_question(bot, message.author, new_index)
                except Exception:
                    return

                entry["qmsg_id"] = new_qmsg.id if new_qmsg else None
                user_progress[uid] = entry
                await save_progress()

            # --- Вопросы закончились → завершаем анкету
            else:
                msg_obj = await fetch_app_message(bot, entry.get("msg_id"))
                await finish_form(bot, uid, answers, msg_obj)
                await save_progress()

        # ==============================
        # === Вопрос с вариантами
        # ==============================
        else:
            # На такие вопросы ожидаются реакции, поэтому в DM ничего не делаем
            return


@bot.event
async def on_raw_reaction_add(payload):
    """
    Событие при добавлении реакции.
    - Сохраняет выбранный вариант ответа
    - Переходит к следующему вопросу
    """
    user_progress = await load_progress()
    if payload.user_id == bot.user.id:
        return

    uid = payload.user_id
    emoji = str(payload.emoji)

    entry = user_progress.get(uid)
    if not entry:
        print(f"[DEBUG] У {uid} нет активной анкеты")

    index = entry.get("index", 0)
    qmsg_id = entry.get("qmsg_id")
    # Проверяем, что реакция поставлена на актуальное сообщение с вопросом
    if payload.message_id != qmsg_id:
        print(
            f"[DEBUG] Игнорируем реакцию — сообщение не совпадает ({payload.message_id} != {qmsg_id})"
        )
        return

    q = questions[index]
    options = q.get("options")
    if not options or emoji not in options:
        return

    # сохраняем ответ
    entry["answers"].append(options[emoji])
    entry["index"] = await get_next_index(index, entry["answers"])
    user_progress[uid] = entry
    await save_progress()

    user = await bot.fetch_user(uid)

    # Следующий вопрос или завершение анкеты
    if entry["index"] < len(questions):
        new_qmsg = await ask_question(bot, user, entry["index"])
        if new_qmsg:
            entry["qmsg_id"] = new_qmsg.id
            user_progress[uid] = entry
            await save_progress()
    else:
        msg_obj = await fetch_app_message(entry.get("msg_id"))
        await finish_form(bot, uid, entry["answers"], msg_obj)


# -------------------- Запуск --------------------
async def run_bot():
    """
    Запускает бота с автоматическим перезапуском
    при ошибках подключения.
    """

    while True:
        try:
            await bot.start(TOKEN)
        except Exception as e:
            print(f"❌ Ошибка при запуске: {e}")
            print("⏳ Жду 30 секунд и пробую снова...")
            await asyncio.sleep(30)


asyncio.run(run_bot())
