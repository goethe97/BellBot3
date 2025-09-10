"""
Модуль для работы с дедлайнами смены фамилий в Discord-сервере.

Функционал:
- Логирование дедлайна для конкретного участника.
- Проверка всех записей логов и отправка оповещений в канал-аларм.
- Пометка обработанных сообщений галочкой (✅), чтобы не проверять повторно.
"""

import discord
from datetime import datetime, timedelta

# 🔧 Настройки каналов и ролей
LOG_CHANNEL_ID = 1414026815873486868
ALARM_CHANNEL_ID = 1414027547016040559
ROLE_TO_CHECK = 1389184190989467677  # роль, которую проверяем


async def log_deadline(bot: discord.Client, member: discord.Member, days: int = 7):
    """
    Логирует срок смены фамилии в канал логов.

    :param bot: Discord клиент
    :param member: участник гильдии
    :param days: количество дней до дедлайна (по умолчанию 7)
    """
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        return

    deadline = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    await channel.send(f"{member.id} {deadline}")


async def check_deadlines(bot: discord.Client, guild_id: int, review_roles=None):
    """
    Проверяет все записи в канале LOG_CHANNEL_ID и кидает аларм, если срок вышел.
    После отправки аларма ставит ✅ на сообщение, чтобы не проверять повторно.
    review_roles — список ID ролей, которые нужно упомянуть.
    """
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    alarm_channel = bot.get_channel(ALARM_CHANNEL_ID)
    guild = bot.get_guild(guild_id)

    if not log_channel or not alarm_channel or not guild:
        print("❌ Не найден один из каналов (лог/аларм) или гильдия")
        return

    now = datetime.utcnow()

    async for msg in log_channel.history(limit=None):
        # 🔹 Пропускаем сообщения, где уже стоит ✅
        if any(r.emoji == "✅" for r in msg.reactions):
            continue

        try:
            uid_str, deadline_str = msg.content.split(" ", 1)
            uid = int(uid_str)
            deadline = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M:%S")

            if now >= deadline:
                member = guild.get_member(uid)
                if member and any(r.id == ROLE_TO_CHECK for r in member.roles):
                    mentions = ""
                    if review_roles:
                        roles = [
                            guild.get_role(rid)
                            for rid in review_roles
                            if guild.get_role(rid)
                        ]
                        mentions = " ".join(r.mention for r in roles)
                        if mentions:
                            mentions = f"\n🔔 {mentions}"

                    await alarm_channel.send(
                        f"⚠️ Срок смены фамилии истёк!\n"
                        f"Пользователь: {member.mention} (`{uid}`)\n"
                        f"Проверьте, что он состоит в орге и изменил фамилию."
                        f"{mentions}"
                    )
                    # ✅ ставим галочку на сообщении, чтобы больше не проверять
                    await msg.add_reaction("✅")

        except Exception as e:
            print(f"⚠️ Ошибка при разборе записи в логах: {msg.content} → {e}")
