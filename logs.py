import disnake
from disnake.ext import commands
import aiosqlite
import datetime

class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.setup_database())
        self.path = "dbs/file.db"

    async def init_db(self):
        async with aiosqlite.connect(self.path) as db:

            await db.execute("PRAGMA journal_mode=WAL")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    action TEXT,
                    timestamp TEXT,
                    user_actioned_id INTEGER,
                    reason TEXT,
                    duration TEXT,
                    deleted_message TEXT,
                    channel_id INTEGER,
                    moderator_id INTEGER,
                    extra_info TEXT
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    guild_id INTEGER PRIMARY KEY,
                    is_setup TEXT DEFAULT 'False', 
                    category_id INTEGER,
                    channel_id INTEGER
                )
            """)
            await db.commit()

    async def setup_database(self):
        await self.init_db()

    async def log_action(self, guild_id: int, user_id: int, action: str, user_actioned_id: int = None, 
                        reason: str = None, duration: str = None, deleted_message_text: str = None,
                        channel_id: int = None, moderator_id: int = None, extra_info: str = None):
        """Универсальная функция логирования"""
        timestamp = datetime.datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO logs (
                    guild_id,
                    user_id, 
                    action, 
                    timestamp, 
                    user_actioned_id, 
                    reason, 
                    duration, 
                    deleted_message,
                    channel_id,
                    moderator_id,
                    extra_info
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (guild_id, user_id, action, timestamp, user_actioned_id, reason, duration, 
                  deleted_message_text, channel_id, moderator_id, extra_info))
            await db.commit()

    async def send_log_embed(self, guild, embed):
        """Отправить лог в канал"""
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT channel_id FROM settings WHERE guild_id = ?", (guild.id,))
            row = await cursor.fetchone()
            await cursor.close()
            
            if row and row[0]:
                log_channel = guild.get_channel(row[0])
                if log_channel:
                    await log_channel.send(embed=embed)

    async def fetch_logs(self, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT * FROM logs WHERE user_id = ?", (user_id,))
            rows = await cursor.fetchall()
            await cursor.close()
            return rows
        
    async def fetch_all_logs(self):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT * FROM logs")
            rows = await cursor.fetchall()
            await cursor.close()
            return rows

    @commands.slash_command(description="Настроить каналы для логгирования")
    @commands.has_permissions(administrator=True)
    async def lsetup(self, inter: disnake.ApplicationCommandInteraction):

        await inter.response.send_message("**🛠️ Сетап логов**\n\n▱▱▱▱▱▱ [0%]")
        
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT * FROM settings WHERE guild_id = ?", (inter.guild.id,))
            existing = await cursor.fetchone()
            await cursor.close()
            
            if existing and existing[1] == 'True':
                await inter.edit_original_response(content="❌ Логирование уже настроено!")
                return

            overwrites = {
    inter.guild.default_role: disnake.PermissionOverwrite(view_channel=False),
    inter.guild.me: disnake.PermissionOverwrite(view_channel=True),
}

            category = await inter.guild.create_category("📋 Логи", overwrites=overwrites)

            channel = await inter.guild.create_text_channel(
                "логирование",
                category=category,
                overwrites={
                    **overwrites,
                    inter.author: disnake.PermissionOverwrite(view_channel=True)
                }
            )


            await db.execute("""
                INSERT OR REPLACE INTO settings (guild_id, is_setup, category_id, channel_id)
                VALUES (?, 'True', ?, ?)
            """, (inter.guild.id, category.id, channel.id))
            await db.commit()

            await inter.edit_original_response(
                content="**🛠️ Сетап логов**\n\n▰▰▰▰▰▰ [100%]\n\n✅ Сетап успешно завершен!"
            )

    # ============= ЛОГИРОВАНИЕ СООБЩЕНИЙ =============
    @commands.Cog.listener()
    async def on_message_delete(self, message: disnake.Message):
        if message.author.bot or not message.guild:
            return
        
        deleted_message_text = message.content[:100] + "..." if len(message.content) > 100 else message.content

        await self.log_action(
            guild_id=message.guild.id,
            user_id=message.author.id,
            action="message_delete",
            deleted_message_text=deleted_message_text,
            channel_id=message.channel.id
        )

        embed = disnake.Embed(
            title="🗑️ Сообщение удалено",
            description=f"**Автор:** {message.author.mention}\n**Канал:** {message.channel.mention}\n**Содержание:** {deleted_message_text or '*Нет текста*'}",
            color=disnake.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_footer(text=f"ID пользователя: {message.author.id}")
        
        await self.send_log_embed(message.guild, embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: disnake.Message, after: disnake.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        
        before_text = before.content[:100] + "..." if len(before.content) > 100 else before.content
        after_text = after.content[:100] + "..." if len(after.content) > 100 else after.content

        await self.log_action(
            guild_id=before.guild.id,
            user_id=before.author.id,
            action="message_edit",
            channel_id=before.channel.id,
            extra_info=f"До: {before_text} | После: {after_text}"
        )

        embed = disnake.Embed(
            title="✏️ Сообщение отредактировано",
            color=disnake.Color.orange(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Автор", value=before.author.mention, inline=False)
        embed.add_field(name="Канал", value=before.channel.mention, inline=False)
        embed.add_field(name="До", value=before_text or "*Нет текста*", inline=False)
        embed.add_field(name="После", value=after_text or "*Нет текста*", inline=False)
        embed.set_footer(text=f"ID пользователя: {before.author.id}")
        
        await self.send_log_embed(before.guild, embed)

    # ============= ЛОГИРОВАНИЕ УЧАСТНИКОВ =============
    @commands.Cog.listener()
    async def on_member_join(self, member: disnake.Member):
        await self.log_action(
            guild_id=member.guild.id,
            user_id=member.id,
            action="member_join"
        )

        embed = disnake.Embed(
            title="📥 Участник присоединился",
            description=f"{member.mention} присоединился к серверу",
            color=disnake.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id, inline=True)
        embed.add_field(name="Аккаунт создан", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        
        await self.send_log_embed(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: disnake.Member):
        await self.log_action(
            guild_id=member.guild.id,
            user_id=member.id,
            action="member_leave"
        )

        embed = disnake.Embed(
            title="📤 Участник покинул сервер",
            description=f"{member.mention} покинул сервер",
            color=disnake.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="ID", value=member.id, inline=True)
        
        await self.send_log_embed(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: disnake.Member, after: disnake.Member):
        # Изменение ролей
        if before.roles != after.roles:
            added = set(after.roles) - set(before.roles)
            removed = set(before.roles) - set(after.roles)
            
            if added or removed:
                roles_info = f"Добавлено: {', '.join([r.name for r in added])} | Удалено: {', '.join([r.name for r in removed])}"
                
                await self.log_action(
                    guild_id=after.guild.id,
                    user_id=after.id,
                    action="member_roles_update",
                    extra_info=roles_info
                )

                embed = disnake.Embed(
                    title="🎭 Роли изменены",
                    color=disnake.Color.blue(),
                    timestamp=datetime.datetime.utcnow()
                )
                embed.add_field(name="Участник", value=after.mention, inline=False)
                
                if added:
                    embed.add_field(name="Добавлено", value=", ".join([r.mention for r in added]), inline=False)
                if removed:
                    embed.add_field(name="Удалено", value=", ".join([r.mention for r in removed]), inline=False)
                
                embed.set_footer(text=f"ID пользователя: {after.id}")
                
                await self.send_log_embed(after.guild, embed)
        
        # Изменение никнейма
        if before.nick != after.nick:
            await self.log_action(
                guild_id=after.guild.id,
                user_id=after.id,
                action="member_nick_update",
                extra_info=f"До: {before.nick or before.name} | После: {after.nick or after.name}"
            )

            embed = disnake.Embed(
                title="📝 Никнейм изменён",
                color=disnake.Color.blue(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="Участник", value=after.mention, inline=False)
            embed.add_field(name="Старый", value=before.nick or before.name, inline=True)
            embed.add_field(name="Новый", value=after.nick or after.name, inline=True)
            embed.set_footer(text=f"ID пользователя: {after.id}")
            
            await self.send_log_embed(after.guild, embed)

    # ============= ЛОГИРОВАНИЕ БАНОВ =============
    @commands.Cog.listener()
    async def on_member_ban(self, guild: disnake.Guild, user: disnake.User):
        # Пытаемся получить информацию из audit logs
        moderator = None
        reason = "Не указана"
        
        try:
            async for entry in guild.audit_logs(limit=1, action=disnake.AuditLogAction.ban):
                if entry.target.id == user.id:
                    moderator = entry.user
                    reason = entry.reason or "Не указана"
                    break
        except:
            pass

        await self.log_action(
            guild_id=guild.id,
            user_id=user.id,
            action="member_ban",
            moderator_id=moderator.id if moderator else None,
            reason=reason
        )

        embed = disnake.Embed(
            title="🔨 Участник забанен",
            description=f"{user.mention} ({user})",
            color=disnake.Color.dark_red(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="ID", value=user.id, inline=True)
        if moderator:
            embed.add_field(name="Модератор", value=moderator.mention, inline=True)
        embed.add_field(name="Причина", value=reason, inline=False)
        
        await self.send_log_embed(guild, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: disnake.Guild, user: disnake.User):
        moderator = None
        
        try:
            async for entry in guild.audit_logs(limit=1, action=disnake.AuditLogAction.unban):
                if entry.target.id == user.id:
                    moderator = entry.user
                    break
        except:
            pass

        await self.log_action(
            guild_id=guild.id,
            user_id=user.id,
            action="member_unban",
            moderator_id=moderator.id if moderator else None
        )

        embed = disnake.Embed(
            title="✅ Участник разбанен",
            description=f"{user.mention} ({user})",
            color=disnake.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="ID", value=user.id, inline=True)
        if moderator:
            embed.add_field(name="Модератор", value=moderator.mention, inline=True)
        
        await self.send_log_embed(guild, embed)

    # ============= ЛОГИРОВАНИЕ ГОЛОСОВЫХ КАНАЛОВ =============
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: disnake.Member, before: disnake.VoiceState, after: disnake.VoiceState):
        # Подключился
        if before.channel is None and after.channel is not None:
            await self.log_action(
                guild_id=member.guild.id,
                user_id=member.id,
                action="voice_join",
                channel_id=after.channel.id
            )

            embed = disnake.Embed(
                title="🔊 Вход в голосовой канал",
                description=f"{member.mention} подключился к {after.channel.mention}",
                color=disnake.Color.green(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_footer(text=f"ID пользователя: {member.id}")
            
            await self.send_log_embed(member.guild, embed)
        
        # Отключился
        elif before.channel is not None and after.channel is None:
            await self.log_action(
                guild_id=member.guild.id,
                user_id=member.id,
                action="voice_leave",
                channel_id=before.channel.id
            )

            embed = disnake.Embed(
                title="🔇 Выход из голосового канала",
                description=f"{member.mention} отключился от {before.channel.mention}",
                color=disnake.Color.red(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_footer(text=f"ID пользователя: {member.id}")
            
            await self.send_log_embed(member.guild, embed)
        
        # Переключился
        elif before.channel != after.channel and before.channel is not None and after.channel is not None:
            await self.log_action(
                guild_id=member.guild.id,
                user_id=member.id,
                action="voice_move",
                extra_info=f"Из: {before.channel.name} | В: {after.channel.name}"
            )

            embed = disnake.Embed(
                title="🔄 Переключение голосового канала",
                description=f"{member.mention} переключился",
                color=disnake.Color.blue(),
                timestamp=datetime.datetime.utcnow()
            )
            embed.add_field(name="Из", value=before.channel.mention, inline=True)
            embed.add_field(name="В", value=after.channel.mention, inline=True)
            embed.set_footer(text=f"ID пользователя: {member.id}")
            
            await self.send_log_embed(member.guild, embed)

    # ============= ЛОГИРОВАНИЕ ИЗМЕНЕНИЙ КАНАЛОВ =============
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self.log_action(
            guild_id=channel.guild.id,
            user_id=None,
            action="channel_create",
            channel_id=channel.id,
            extra_info=f"Название: {channel.name} | Тип: {channel.type}"
        )

        embed = disnake.Embed(
            title="➕ Канал создан",
            description=f"**Название:** {channel.mention}\n**Тип:** {channel.type}",
            color=disnake.Color.green(),
            timestamp=datetime.datetime.utcnow()
        )
        
        await self.send_log_embed(channel.guild, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.log_action(
            guild_id=channel.guild.id,
            user_id=None,
            action="channel_delete",
            channel_id=channel.id,
            extra_info=f"Название: {channel.name} | Тип: {channel.type}"
        )

        embed = disnake.Embed(
            title="➖ Канал удалён",
            description=f"**Название:** {channel.name}\n**Тип:** {channel.type}",
            color=disnake.Color.red(),
            timestamp=datetime.datetime.utcnow()
        )
        
        await self.send_log_embed(channel.guild, embed)

    # ============= МЕТОДЫ ДЛЯ ВНЕШНЕГО ВЫЗОВА ИЗ ДРУГИХ КОГОВ =============
    async def log_moderation_action(self, guild_id: int, moderator_id: int, user_id: int, 
                                    action: str, reason: str = None, duration: str = None):
        """Логирование модерационных действий (вызывается из mod.py)"""
        await self.log_action(
            guild_id=guild_id,
            user_id=moderator_id,  # Действие совершил модератор
            action=action,
            user_actioned_id=user_id,  # На кого было действие
            moderator_id=moderator_id,
            reason=reason,
            duration=duration
        )
        
        # Создаём embed для отправки в канал логов
        action_emojis = {
            "mute": "🔇",
            "unmute": "🔊",
            "kick": "👢",
            "ban": "🚫",
            "unban": "✅",
            "warn": "⚠️",
            "unwarn": "✅",
            "clear": "🗑️"
        }
        
        action_names = {
            "mute": "Мьют выдан",
            "unmute": "Мьют снят",
            "kick": "Кик",
            "ban": "Бан",
            "unban": "Разбан",
            "warn": "Предупреждение",
            "unwarn": "Снятие предупреждения",
            "clear": "Очистка сообщений"
        }
        
        emoji = action_emojis.get(action, "📝")
        title = action_names.get(action, action.upper())
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        
        moderator = guild.get_member(moderator_id)
        user = guild.get_member(user_id) or await self.bot.fetch_user(user_id)
        
        embed = disnake.Embed(
            title=f"{emoji} {title}",
            color=disnake.Color.orange(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Модератор", value=moderator.mention if moderator else f"ID: {moderator_id}", inline=True)
        embed.add_field(name="Пользователь", value=user.mention if user else f"ID: {user_id}", inline=True)
        
        if reason:
            embed.add_field(name="Причина", value=reason, inline=False)
        if duration:
            embed.add_field(name="Длительность", value=duration, inline=False)
        
        embed.set_footer(text=f"ID модератора: {moderator_id} | ID пользователя: {user_id}")
        
        await self.send_log_embed(guild, embed)

    async def log_ticket_action(self, guild_id: int, user_id: int, action: str, 
                               ticket_id: int = None, extra_info: str = None):
        """Логирование действий с тикетами (вызывается из tickets.py)"""
        await self.log_action(
            guild_id=guild_id,
            user_id=user_id,
            action=action,
            extra_info=f"Ticket #{ticket_id}" + (f" | {extra_info}" if extra_info else "")
        )
        
        action_emojis = {
            "ticket_create": "🎫",
            "ticket_close": "❌",
            "ticket_accept": "✅"
        }
        
        action_names = {
            "ticket_create": "Тикет создан",
            "ticket_close": "Тикет закрыт",
            "ticket_accept": "Тикет принят"
        }
        
        emoji = action_emojis.get(action, "🎫")
        title = action_names.get(action, action)
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        
        user = guild.get_member(user_id)
        
        embed = disnake.Embed(
            title=f"{emoji} {title}",
            description=f"**Пользователь:** {user.mention if user else f'ID: {user_id}'}\n**Тикет:** #{ticket_id}",
            color=disnake.Color.blue(),
            timestamp=datetime.datetime.utcnow()
        )
        
        if extra_info:
            embed.add_field(name="Информация", value=extra_info, inline=False)
        
        embed.set_footer(text=f"ID пользователя: {user_id}")
        
        await self.send_log_embed(guild, embed)

    async def log_tempvoice_action(self, guild_id: int, user_id: int, action: str, 
                                   channel_id: int = None, extra_info: str = None):
        """Логирование действий с временными каналами (вызывается из tempchannels.py)"""
        await self.log_action(
            guild_id=guild_id,
            user_id=user_id,
            action=action,
            channel_id=channel_id,
            extra_info=extra_info
        )
        
        action_emojis = {
            "tempvoice_create": "🔊",
            "tempvoice_delete": "🗑️",
            "tempvoice_lock": "🔐",
            "tempvoice_unlock": "🔓",
            "tempvoice_transfer": "👑"
        }
        
        action_names = {
            "tempvoice_create": "Временный канал создан",
            "tempvoice_delete": "Временный канал удалён",
            "tempvoice_lock": "Канал закрыт",
            "tempvoice_unlock": "Канал открыт",
            "tempvoice_transfer": "Владение передано"
        }
        
        emoji = action_emojis.get(action, "🔊")
        title = action_names.get(action, action)
        
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        
        user = guild.get_member(user_id)
        channel = guild.get_channel(channel_id) if channel_id else None
        
        embed = disnake.Embed(
            title=f"{emoji} {title}",
            color=disnake.Color.purple(),
            timestamp=datetime.datetime.utcnow()
        )
        embed.add_field(name="Пользователь", value=user.mention if user else f"ID: {user_id}", inline=True)
        
        if channel:
            embed.add_field(name="Канал", value=channel.mention, inline=True)
        
        if extra_info:
            embed.add_field(name="Информация", value=extra_info, inline=False)
        
        embed.set_footer(text=f"ID пользователя: {user_id}")
        
        await self.send_log_embed(guild, embed)

            
def setup(bot):
    bot.add_cog(Logs(bot))