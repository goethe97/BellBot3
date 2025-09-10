"""
applications.py — управление заявками (анкеты HR-бота)

Задачи:
- Ведение прогресса анкет (загрузка/сохранение)
- Задавание вопросов в ЛС и сбор ответов
- Проверка ЧС / отклонённых
- Присвоение ролей и изменение ника
- Создание веток для рассмотрения заявок
"""

import os
import discord
import json
import asyncio
from cogs.deadlines import (
    log_deadline,
)
from cogs.helpers import (
    extract_lines,
    load_config,
    is_blacklisted,
    is_declined,
    calculate_score,
    save_id,
)

from configuration import (
    GUILD_ID,
    ROLE_IDS,
    REVIEW_ROLES,
    DECLINED_FILE,
    PROGRESS_FILE,
)

# -------------------------Глобальные переменные -------------------------
progress_lock = asyncio.Lock()  # блокировка для синхронного доступа к файлу прогресса
user_progress = {}  # {uid: {answers, index, msg_id, qmsg_id}}


# Список вопросов анкеты
questions = [
    {
        "text": "Привет! 👋 Я HR-BOT фамки **Bell**.\n\nПеред началом: ты понимаешь, что нужно подождать, пока бот добавит все реакции перед тем как выбрать? А также, чтобы нельзя менять ответы на предыдущем вопросе?[Если бот завис, нажми опять на туже реакцию, подожди пока все эмодзи загрузятся и нажми заново]",
        "options": {"✅": "Да", "❌": "Нет"},
    },
    {
        "text": "Сколько вам лет?",
        "options": {"1️⃣": "Меньше 14", "2️⃣": "14-16", "3️⃣": "17-20", "4️⃣": "21+"},
    },
    {
        "text": "Сколько вы играете на серверах?",
        "options": {
            "1️⃣": "Меньше месяца",
            "2️⃣": ">1 месяца",
            "3️⃣": ">3 месяцев",
            "4️⃣": ">6 месяцев",
            "5️⃣": ">1 года",
            "6️⃣": ">2 лет",
            "7️⃣": ">5 лет",
        },
    },
    {
        "text": "Состояли ли вы когда-либо в государственной фракции?",
        "options": {"✅": "Да", "❌": "Нет"},
    },
    {"text": "Были ли вы в старшем составе?", "options": {"✅": "Да", "❌": "Нет"}},
    {
        "text": "Сколько времени вы были в старшем составе?",
        "options": {"1️⃣": "1 неделя", "2️⃣": "2 недели", "3️⃣": ">2 недель"},
    },
    {
        "text": "Какое имя вы будете использовать в игре? (пример: Christopher)",
        "options": None,
    },
    {"text": "Как вас зовут в реальной жизни?", "options": None},
]


# -------------------------Работа с прогрессом-------------------------
async def load_progress():
    """
    Загружает прогресс анкет из PROGRESS_FILE.
    Формат файла: { "uid": {answers, index, msg_id, qmsg_id} }
    """
    global user_progress
    async with progress_lock:
        if os.path.exists(PROGRESS_FILE):
            try:
                with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    user_progress.clear()
                    user_progress.update({int(uid): v for uid, v in data.items()})
                    return {int(uid): v for uid, v in data.items()}
            except Exception as e:
                print(f"⚠️ Ошибка при загрузке прогресса: {e}")
        return {}


async def save_progress():
    """
    Сохраняет user_progress в PROGRESS_FILE.
    """
    async with progress_lock:
        try:
            data = {str(uid): v for uid, v in user_progress.items()}
            with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Ошибка при сохранении прогресса: {e}")


# -------------------------Основная логика анкеты-------------------------
async def finish_form(bot, uid, answers, msg):
    """
    Завершает обработку анкеты:
    - Проверяет ЧС / отклонённых
    - Считает баллы
    - Присваивает роли и ник
    - Создаёт ветку для заявки
    - Чистит прогресс
    """
    guild = bot.get_guild(GUILD_ID)
    member = None
    if guild:
        try:
            member = guild.get_member(uid) or await guild.fetch_member(uid)
        except Exception:
            member = None

    async def safe_send(target_member, text):
        """Отправка ЛС пользователю (если закрыто — ставим реакцию в анкете)."""
        try:
            if isinstance(target_member, (discord.Member, discord.User)):
                await target_member.send(text)
            else:
                user = await bot.fetch_user(uid)
                await user.send(text)
        except discord.Forbidden:
            if msg:
                try:
                    await msg.add_reaction("🚷")
                    await msg.reply(
                        "🚷 Этот пользователь закрыл ЛС или вышел. DM не отправлен."
                    )
                except Exception:
                    pass
        except Exception as e:
            print(f"⚠️ Не удалось отправить DM {uid}: {e}")

    # --- загружаем конфиг ---
    config = {}
    try:
        config = load_config()
    except Exception as e:
        print(f"⚠️ Не удалось загрузить config.json: {e}")
    THRESHOLDS = config.get("THRESHOLDS", {})

    # --- проверка ЧС / отклонённых ---
    if is_blacklisted(uid) or is_declined(uid):
        if msg:
            try:
                await msg.add_reaction("❌")
                thread = await msg.create_thread(
                    name=f"❌ {member.display_name if member else uid}"
                )
                await thread.send(
                    f"📋 Заявка {member.mention if member else f'`{uid}`'}\n"
                    f"Статус: **Отклонено** (ранее)\n"
                    f"Причина: Пользователь в ЧС или уже отклонён\n\n"
                    f"UID анкеты: `{msg.id}`"
                )
            except Exception as e:
                print(f"⚠️ Ошибка при создании ветки для {uid}: {e}")

        await safe_send(
            member,
            "🚫 Ваша заявка отклонена. Вы либо в ЧС, либо уже отклонялись ранее. 🙏",
        )
        user_progress.pop(uid, None)
        await save_progress()
        return

    # --- подсчёт баллов ---
    try:
        score = calculate_score(answers)
    except Exception as e:
        print(f"⚠️ Ошибка при подсчёте баллов {uid}: {e}")
        score = 0

    status, reason = "", ""

    # --- принят ---
    if score >= THRESHOLDS.get("accept", 99999):
        status, reason = "Принят", "Достаточный возраст и опыт"
        if msg:
            await msg.add_reaction("✅")

        if member and guild:
            # выдаём роли
            roles = [guild.get_role(rid) for rid in ROLE_IDS if guild.get_role(rid)]
            if roles:
                try:
                    await member.add_roles(*roles)
                except discord.Forbidden:
                    print(f"❌ Нет прав выдать роли {member}")
                except Exception as e:
                    print(f"⚠️ Ошибка при выдаче ролей {member}: {e}")

            # меняем ник
            new_nick = f"{answers[6]} | {answers[7]}"
            try:
                await member.edit(nick=new_nick)
            except Exception as e:
                print(f"⚠️ Ошибка при смене ника {member}: {e}")
            await safe_send(
                member,
                f"🎉 Поздравляем, вы прошли отбор!\n\n"
                f"Ваш ник должен быть 👉 **{new_nick}**\n"
                f"⚠️ В течение 7 суток смените фамилию на **Bell** и пришлите скриншот в любой в чат на канале Bell.\n"
                f"❌ Нарушение = исключение.\n\n"
                f"💡 Совет: не нарушайте правила, будьте онлайн при контрактах.\n",
            )
            await log_deadline(bot, member, days=7)

    # --- отклонён ---
    elif score <= THRESHOLDS.get("decline", 0):
        status, reason = "Отклонено", "Возраст или опыт ниже допустимого"
        if msg:
            await msg.add_reaction("❌")
        if not is_declined(uid):
            await safe_send(
                member,
                "🚫 К сожалению, ваша заявка отклонена по внутренним причинам.\n"
                "🙏 Просьба отнестись с пониманием и не донимать Даню по пустякам.\n"
                "Хорошей игры на GTA5RP!",
            )
            save_id(DECLINED_FILE, uid)

    # --- спорные ---
    else:
        status, reason = (
            "На рассмотрении",
            "Ответы спорные, требуется проверка. Если считаете отклонен, попросите Даню, пусть id добавит в файлик отклоненных",
        )
        if msg:
            await msg.add_reaction("❓")
        await safe_send(
            member,
            "❓ Ваша заявка требует дополнительного рассмотрения.\n"
            "Пожалуйста, дождитесь решения руководства.",
        )

    # --- собираем анкету ---
    answers_text = [
        f"**{q['text']}**\n➡️ {answers[i]}"
        for i, q in enumerate(questions)
        if i < len(answers)
    ]
    full_form = "\n\n".join(answers_text)

    # --- создаём ветку ---
    if msg:
        try:
            display_name = member.display_name if member else f"UID:{uid}"
            mention = member.mention if member else f"`{uid}`"
            thread = await msg.create_thread(name=f"{status} {display_name}")

            mentions = ""
            if status == "На рассмотрении" and guild:
                roles = [
                    guild.get_role(rid) for rid in REVIEW_ROLES if guild.get_role(rid)
                ]
                mentions = " ".join([r.mention for r in roles])

            await thread.send(
                f"📋 Заявка {mention}\n"
                f"Статус: **{status}**\n"
                f"Причина: {reason}\n"
                f"Баллы: {score}\n\n"
                f"{'🔔 ' + mentions if mentions else ''}\n\n"
                f"**Анкета:**\n{full_form}"
            )
        except Exception as e:
            print(f"⚠️ Ошибка при создании ветки для {uid}: {e}")

    # --- чистим прогресс ---
    user_progress.pop(uid, None)
    await save_progress()


async def ask_question(bot, user, index):
    """
    Отправляет пользователю вопрос анкеты в ЛС.
    Сохраняет прогресс (номер вопроса и id сообщения).
    """
    if index >= len(questions):
        return None

    dm = user.dm_channel or await user.create_dm()
    q = questions[index]

    # Формируем текст с вариантами
    text = f"**Вопрос {index + 1}/{len(questions)}:**\n{q['text']}"
    options = q.get("options") or {}
    if options:
        opts_text = "\n".join(
            [f"{emoji} {answer}" for emoji, answer in options.items()]
        )
        text += f"\n\n{opts_text}"

    qmsg = await dm.send(text)

    # Добавляем реакции-ответы
    for emoji in options.keys():
        try:
            await qmsg.add_reaction(emoji)
        except discord.HTTPException:
            print(f"⚠️ Не удалось добавить реакцию {emoji} к вопросу {index + 1}")

    # ⚡ обновляем прогресс
    entry = user_progress.get(
        user.id,
        {
            "answers": [],
            "index": 0,
            "msg_id": None,
            "qmsg_id": None,
        },
    )

    entry["index"] = index
    entry["qmsg_id"] = qmsg.id
    user_progress[user.id] = entry

    await save_progress()
    return qmsg


# -------------------------Обработка новых сообщений-заявок-------------------------
async def process_application_message(bot, message):
    """
    Обрабатывает сообщение анкеты из канала заявок:
    - Ищет поле 'Ваш DISCORD'
    - Проверяет пользователя
    - Запускает или продолжает анкету
    """
    lines = extract_lines(message)

    # ищем Discord-тег
    discord_tag = None
    for i, line in enumerate(lines):
        if "ваш discord" in line.lower():
            if i + 1 < len(lines):
                discord_tag = lines[i + 1].strip()
            break

    if not discord_tag:
        print(f"⚠️ Не найден 'Ваш DISCORD' в сообщении {message.id}")
        return

    guild = bot.get_guild(GUILD_ID)
    member = guild.get_member_named(discord_tag)
    if not member:
        await message.add_reaction("❌")
        thread = await message.create_thread(name=f"❌ {discord_tag}")
        roles = [guild.get_role(rid) for rid in REVIEW_ROLES]
        mentions = " ".join([r.mention for r in roles if r])
        await thread.send(
            f"⚠️ Пользователь **{discord_tag}** не найден на сервере.\n"
            f"UID анкеты: `{message.id}`\n"
            f"Анкета остаётся без проверки\n\n"
            f"{mentions}"
        )
        return

    # Проверка ЧС
    if is_blacklisted(member.id):
        await message.add_reaction("❌")
        thread = await message.create_thread(name=f"❌ {member.display_name}")
        await thread.send(
            f"⛔ Пользователь {member.mention} находится в ЧС.\n"
            f"UID анкеты: `{message.id}`\n"
            f"Заявка автоматически отклонена."
        )
        try:
            await member.send(
                "🚫 Ваша заявка отклонена, так как вы находитесь в **ЧС Bell**.\n"
                "Просьба не пытаться подавать заявку повторно 🙏"
            )
        except discord.Forbidden:
            pass
        return

    # отклонён ранее
    if is_declined(member.id):
        await message.add_reaction("❌")
        thread = await message.create_thread(name=f"❌ {member.display_name}")
        await thread.send(
            f"⚠️ Пользователь {member.mention} уже был отклонён ранее.\n"
            f"UID анкеты: `{message.id}`\n"
            f"Заявка автоматически отклонена."
        )
        try:
            await member.send(
                "🚫 Вы уже получали отказ по заявке ранее.\n"
                "Повторные попытки приёма невозможны 🙏"
            )
        except discord.Forbidden:
            print(f"❌ Не удалось отправить ЛС {member}")
        return

    # продолжаем или запускаем анкету
    try:
        if member.id in user_progress:
            entry = user_progress[member.id]
            idx = entry.get("index", 0)

            try:
                user = await bot.fetch_user(member.id)
                dm = user.dm_channel or await user.create_dm()
                await dm.send(
                    f"📌 Вы остановились на вопросе {idx + 1}. Просто ответьте на него реакцией."
                )
            except Exception as e:
                print(f"⚠️ Не удалось напомнить {member}: {e}")

            return

        # Если анкеты нет → запускаем с первого вопроса
        qmsg = await ask_question(bot, member, 0)
        entry = {
            "index": 0,
            "answers": [],
            "msg_id": message.id if message else None,  # сообщение заявки в канале
            "qmsg_id": qmsg.id if qmsg else None,  # текущее сообщение-вопрос в ЛС
        }
        user_progress[member.id] = entry
        await save_progress()
        print(f"✅ Анкета для {member} успешно запущена (UID анкеты {message.id})")

    except discord.Forbidden:
        # закрыты ЛС
        await message.add_reaction("❌")
        role = guild.get_role(1389184170739240970)
        thread = await message.create_thread(name=f"❌ {member.display_name}")
        await thread.send(
            f"⚠️ Пользователь {member.mention} закрыл личные сообщения. Анкета не начата.\n\n"
            f"{role.mention if role else ''}"
        )
        print(f"❌ Не удалось отправить ЛС {discord_tag} (закрыты сообщения)")
