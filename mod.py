import disnake
from disnake.ext import commands
import aiosqlite
import datetime
from datetime import timedelta
import asyncio

class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.path = "dbs/file.db"

    async def init_db(self):
        async with aiosqlite.connect(self.path) as db:

            await db.execute("PRAGMA journal_mode=WAL")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT,
                    time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    active TEXT DEFAULT "true"
                )""")
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS punishments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    action_type TEXT NOT NULL,
                    duration TEXT,
                    reason TEXT,
                    time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    guild_id INTEGER NOT NULL
                )""")
            await db.commit()

    async def warn_user(self, user_id: int, moderator_id: int, reason: str = None):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "INSERT INTO warnings (user_id, moderator_id, reason) VALUES (?, ?, ?)", 
                (user_id, moderator_id, reason)
            )
            await db.commit()
            return cursor.lastrowid

    async def log_punishment(self, guild_id: int, user_id: int, moderator_id: int, action_type: str, duration: str = None, reason: str = None):
        """Логировать наказание в базу данных"""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO punishments (guild_id, user_id, moderator_id, action_type, duration, reason) 
                VALUES (?, ?, ?, ?, ?, ?)""",
                (guild_id, user_id, moderator_id, action_type, duration, reason)
            )
            await db.commit()

    async def unwarn_user(self, user_id: int, by_moderator: bool = False, warn_id: int = None):
        async with aiosqlite.connect(self.path) as db:
            if by_moderator:
                if warn_id:
                    await db.execute("UPDATE warnings SET active = 'false' WHERE id = ? AND user_id = ?", 
                                    (warn_id, user_id))
                else:
                    await db.execute("UPDATE warnings SET active = 'false' WHERE user_id = ? AND active = 'true' ORDER BY id DESC LIMIT 1", 
                                    (user_id,))
                await db.commit()
                return True
            return False

    async def get_warnings_count(self, user_id: int):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM warnings WHERE user_id = ? AND active = 'true'", 
                (user_id,)
            )
            count = await cursor.fetchone()
            await cursor.close()
            return count[0] if count else 0

    @commands.slash_command(name="mute", description="Выдать мьют пользователю на сервере.")
    @commands.has_permissions(mute_members=True)
    async def mute(self, inter: disnake.ApplicationCommandInteraction,
                   user: disnake.Member = commands.Param(description="Выберите пользователя."),
                   duration: str = commands.Param(description="Время (пример: 1ч, 30м, 1д). Макс: 28д", default="1ч"),
                   reason: str = commands.Param(description="Причина", default="Не указана")):
        
        # Проверка прав
        if user.top_role >= inter.author.top_role:
            await inter.response.send_message("❌ Вы не можете замутить этого пользователя.", ephemeral=True)
            return
        
        # Парсинг времени
        time_multipliers = {
            'с': 1,
            'м': 60,
            'ч': 3600,
            'д': 86400,
            'н': 604800
        }
        
        try:
            time_value = int(duration[:-1])
            time_unit = duration[-1].lower()
            
            if time_unit not in time_multipliers:
                raise ValueError
            
            seconds = time_value * time_multipliers[time_unit]
            
            if seconds > 2419200:  # 28 дней
                await inter.response.send_message("❌ Максимальное время мьюта - 28 суток.", ephemeral=True)
                return
            
            # Выдача мьюта
            await user.timeout(duration=timedelta(seconds=seconds), reason=f"{reason} | Модератор: {inter.author}")
            
            # Логируем в базу данных
            await self.log_punishment(
                inter.guild.id, user.id, inter.author.id, "mute", duration, reason
            )
            
            # Логируем через систему логов
            logs_cog = self.bot.get_cog('Logs')
            if logs_cog:
                await logs_cog.log_moderation_action(
                    guild_id=inter.guild.id,
                    moderator_id=inter.author.id,
                    user_id=user.id,
                    action="mute",
                    reason=reason,
                    duration=duration
                )
            
            embed = disnake.Embed(
                title="🔇 Мьют выдан",
                description=f"**Пользователь:** {user.mention}\n**Время:** {duration}\n**Причина:** {reason}",
                color=disnake.Color.orange()
            )
            embed.set_footer(text=f"Модератор: {inter.author}")
            
            await inter.response.send_message(embed=embed)
            
            # Отправляем сообщение пользователю
            try:
                await user.send(f"🔇 Вы получили мьют на сервере **{inter.guild.name}** на **{duration}**.\n**Причина:** {reason}\n**Модератор:** {inter.author}")
            except:
                pass
                
        except ValueError:
            await inter.response.send_message("❌ Неверный формат времени. Используйте: 1ч, 30м, 2д и т.д.", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)

    @commands.slash_command(name="unmute", description="Снять мьют с пользователя.")
    @commands.has_permissions(mute_members=True)
    async def unmute(self, inter: disnake.ApplicationCommandInteraction,
                     user: disnake.Member = commands.Param(description="Выберите пользователя."),
                     reason: str = commands.Param(description="Причина", default="Не указана")):
        
        try:
            await user.timeout(duration=None, reason=f"{reason} | Модератор: {inter.author}")
            
            # Логируем в базу данных
            await self.log_punishment(
                inter.guild.id, user.id, inter.author.id, "unmute", None, reason
            )
            
            # Логируем через систему логов
            logs_cog = self.bot.get_cog('Logs')
            if logs_cog:
                await logs_cog.log_moderation_action(
                    guild_id=inter.guild.id,
                    moderator_id=inter.author.id,
                    user_id=user.id,
                    action="unmute",
                    reason=reason
                )
            
            embed = disnake.Embed(
                title="🔊 Мьют снят",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=disnake.Color.green()
            )
            embed.set_footer(text=f"Модератор: {inter.author}")
            
            await inter.response.send_message(embed=embed)
            
            try:
                await user.send(f"🔊 Ваш мьют был снят на сервере **{inter.guild.name}**.\n**Причина:** {reason}\n**Модератор:** {inter.author}")
            except:
                pass
                
        except Exception as e:
            await inter.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)

    @commands.slash_command(name="kick", description="Выдать кик пользователю.")
    @commands.has_permissions(kick_members=True)
    async def kick(self, inter: disnake.ApplicationCommandInteraction,
                   user: disnake.Member = commands.Param(description="Выберите пользователя."),
                   reason: str = commands.Param(description="Причина", default="Не указана")):
        
        if user.top_role >= inter.author.top_role:
            await inter.response.send_message("❌ Вы не можете кикнуть этого пользователя.", ephemeral=True)
            return
        
        try:
            # Отправляем сообщение пользователю перед киком
            try:
                await user.send(f"👢 Вы были кикнуты с сервера **{inter.guild.name}**.\n**Причина:** {reason}\n**Модератор:** {inter.author}")
            except:
                pass
            
            await user.kick(reason=f"{reason} | Модератор: {inter.author}")
            
            # Логируем в базу данных
            await self.log_punishment(
                inter.guild.id, user.id, inter.author.id, "kick", None, reason
            )
            
            # Логируем через систему логов
            logs_cog = self.bot.get_cog('Logs')
            if logs_cog:
                await logs_cog.log_moderation_action(
                    guild_id=inter.guild.id,
                    moderator_id=inter.author.id,
                    user_id=user.id,
                    action="kick",
                    reason=reason
                )
            
            embed = disnake.Embed(
                title="👢 Кик выдан",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=disnake.Color.orange()
            )
            embed.set_footer(text=f"Модератор: {inter.author}")
            
            await inter.response.send_message(embed=embed)
                
        except Exception as e:
            await inter.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)

    @commands.slash_command(name="ban", description="Забанить пользователя на сервере.")
    @commands.has_permissions(ban_members=True)
    async def ban(self, inter: disnake.ApplicationCommandInteraction,
                  user: disnake.User = commands.Param(description="Выберите пользователя (можно по ID)."),
                  reason: str = commands.Param(description="Причина", default="Не указана"),
                  delete_messages: int = commands.Param(
                      description="Удалить сообщения за последние дни (0-7)",
                      default=0,
                      min_value=0,
                      max_value=7
                  )):
        
        # Если user - это Member, проверяем роли
        if isinstance(user, disnake.Member):
            if user.top_role >= inter.author.top_role:
                await inter.response.send_message("❌ Вы не можете забанить этого пользователя.", ephemeral=True)
                return
        
        try:
            # Отправляем сообщение пользователю перед баном
            try:
                await user.send(f"🚫 Вы были забанены на сервере **{inter.guild.name}**.\n**Причина:** {reason}\n**Модератор:** {inter.author}")
            except:
                pass
            
            await inter.guild.ban(
                user, 
                reason=f"{reason} | Модератор: {inter.author}",
                delete_message_days=delete_messages
            )
            
            # Логируем в базу данных
            await self.log_punishment(
                inter.guild.id, user.id, inter.author.id, "ban", None, reason
            )
            
            # Логируем через систему логов
            logs_cog = self.bot.get_cog('Logs')
            if logs_cog:
                await logs_cog.log_moderation_action(
                    guild_id=inter.guild.id,
                    moderator_id=inter.author.id,
                    user_id=user.id,
                    action="ban",
                    reason=reason
                )
            
            embed = disnake.Embed(
                title="🚫 Бан выдан",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=disnake.Color.red()
            )
            if delete_messages > 0:
                embed.add_field(name="Удалено сообщений", value=f"За последние {delete_messages} дней")
            embed.set_footer(text=f"Модератор: {inter.author}")
            
            await inter.response.send_message(embed=embed)
                
        except Exception as e:
            await inter.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)

    @commands.slash_command(name="unban", description="Разбанить пользователя.")
    @commands.has_permissions(ban_members=True)
    async def unban(self, inter: disnake.ApplicationCommandInteraction,
                    user_id: str = commands.Param(description="ID пользователя")):
        
        try:
            user_id = int(user_id)
            user = await self.bot.fetch_user(user_id)
            
            await inter.guild.unban(user, reason=f"Разбанен модератором {inter.author}")
            
            # Логируем в базу данных
            await self.log_punishment(
                inter.guild.id, user.id, inter.author.id, "unban", None, "Разбанен"
            )
            
            # Логируем через систему логов
            logs_cog = self.bot.get_cog('Logs')
            if logs_cog:
                await logs_cog.log_moderation_action(
                    guild_id=inter.guild.id,
                    moderator_id=inter.author.id,
                    user_id=user.id,
                    action="unban"
                )
            
            embed = disnake.Embed(
                title="✅ Разбан",
                description=f"**Пользователь:** {user.mention} разбанен",
                color=disnake.Color.green()
            )
            embed.set_footer(text=f"Модератор: {inter.author}")
            
            await inter.response.send_message(embed=embed)
                
        except ValueError:
            await inter.response.send_message("❌ Неверный ID пользователя.", ephemeral=True)
        except disnake.NotFound:
            await inter.response.send_message("❌ Пользователь не найден в списке банов.", ephemeral=True)
        except Exception as e:
            await inter.response.send_message(f"❌ Ошибка: {str(e)}", ephemeral=True)

    @commands.slash_command(name="clear", description="Удалить сообщения в канале.")
    @commands.has_permissions(manage_messages=True)
    async def clear(self, inter: disnake.ApplicationCommandInteraction,
                    amount: int = commands.Param(description="Количество сообщений (1-100)", min_value=1, max_value=100)):
        
        await inter.response.defer(ephemeral=True)
        
        try:
            deleted = await inter.channel.purge(limit=amount)
            
            # Логируем в базу данных
            await self.log_punishment(
                inter.guild.id, inter.author.id, inter.author.id, "clear", None, f"Удалено {len(deleted)} сообщений"
            )
            
            # Логируем через систему логов
            logs_cog = self.bot.get_cog('Logs')
            if logs_cog:
                await logs_cog.log_moderation_action(
                    guild_id=inter.guild.id,
                    moderator_id=inter.author.id,
                    user_id=inter.author.id,
                    action="clear",
                    reason=f"Удалено {len(deleted)} сообщений в {inter.channel.mention}"
                )
            
            embed = disnake.Embed(
                title="🗑️ Очистка сообщений",
                description=f"Удалено **{len(deleted)}** сообщений в {inter.channel.mention}",
                color=disnake.Color.blue()
            )
            embed.set_footer(text=f"Модератор: {inter.author}")
            
            await inter.followup.send(embed=embed, ephemeral=True)
            
            # Автоудаление через 5 секунд
            await asyncio.sleep(5)
            await inter.delete_original_response()
            
        except Exception as e:
            await inter.followup.send(f"❌ Ошибка: {str(e)}", ephemeral=True)

    @commands.slash_command(name="warn", description="Выдать предупреждение пользователю.")
    @commands.has_permissions(manage_messages=True)
    async def warn(self, inter: disnake.ApplicationCommandInteraction,
                   user: disnake.Member = commands.Param(description="Выберите пользователя."),
                   reason: str = commands.Param(description="Укажите причину.", default="Не указана")):
        
        if user.top_role >= inter.author.top_role:
            await inter.response.send_message("❌ Вы не можете выдать предупреждение этому пользователю.", ephemeral=True)
            return
        
        warn_id = await self.warn_user(user.id, inter.author.id, reason)
        warnings_count = await self.get_warnings_count(user.id)
        
        # Логируем в базу данных
        await self.log_punishment(
            inter.guild.id, user.id, inter.author.id, "warn", None, reason
        )
        
        # Логируем через систему логов
        logs_cog = self.bot.get_cog('Logs')
        if logs_cog:
            await logs_cog.log_moderation_action(
                guild_id=inter.guild.id,
                moderator_id=inter.author.id,
                user_id=user.id,
                action="warn",
                reason=reason
            )
        
        embed = disnake.Embed(
            title="⚠️ Предупреждение выдано",
            description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}\n**Всего предупреждений:** {warnings_count}",
            color=disnake.Color.yellow()
        )
        embed.set_footer(text=f"ID предупреждения: {warn_id} | Модератор: {inter.author}")
        
        await inter.response.send_message(embed=embed)
        
        try:
            await user.send(f"⚠️ Вы получили предупреждение на сервере **{inter.guild.name}**.\n**Причина:** {reason}\n**Всего предупреждений:** {warnings_count}\n**Модератор:** {inter.author}")
        except:
            pass

    @commands.slash_command(name="unwarn", description="Снять предупреждение с пользователя.")
    @commands.has_permissions(manage_messages=True)
    async def unwarn(self, inter: disnake.ApplicationCommandInteraction,
                     user: disnake.Member = commands.Param(description="Выберите пользователя."),
                     warn_id: int = commands.Param(description="ID предупреждения (оставьте пустым для последнего)", default=None),
                     reason: str = commands.Param(description="Причина", default="Не указана")):
        
        success = await self.unwarn_user(user.id, True, warn_id)
        
        if success:
            # Логируем в базу данных
            await self.log_punishment(
                inter.guild.id, user.id, inter.author.id, "unwarn", None, f"{reason} | Warn ID: {warn_id or 'last'}"
            )
            
            # Логируем через систему логов
            logs_cog = self.bot.get_cog('Logs')
            if logs_cog:
                await logs_cog.log_moderation_action(
                    guild_id=inter.guild.id,
                    moderator_id=inter.author.id,
                    user_id=user.id,
                    action="unwarn",
                    reason=reason
                )
            
            embed = disnake.Embed(
                title="✅ Предупреждение снято",
                description=f"**Пользователь:** {user.mention}\n**Причина:** {reason}",
                color=disnake.Color.green()
            )
            if warn_id:
                embed.add_field(name="ID предупреждения", value=str(warn_id))
            embed.set_footer(text=f"Модератор: {inter.author}")
            
            await inter.response.send_message(embed=embed)
        else:
            await inter.response.send_message("❌ Не удалось снять предупреждение.", ephemeral=True)

    @commands.slash_command(name="warnings", description="Посмотреть предупреждения пользователя.")
    @commands.has_permissions(manage_messages=True)
    async def warnings(self, inter: disnake.ApplicationCommandInteraction,
                       user: disnake.Member = commands.Param(description="Выберите пользователя.")):
        
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT id, moderator_id, reason, time FROM warnings 
                WHERE user_id = ? AND active = 'true' ORDER BY time DESC""", 
                (user.id,)
            )
            warnings = await cursor.fetchall()
            await cursor.close()
        
        if not warnings:
            embed = disnake.Embed(
                title=f"Предупреждения {user.display_name}",
                description="✅ Нет активных предупреждений",
                color=disnake.Color.green()
            )
            await inter.response.send_message(embed=embed)
            return
        
        embed = disnake.Embed(
            title=f"Предупреждения {user.display_name}",
            description=f"Всего активных предупреждений: **{len(warnings)}**",
            color=disnake.Color.orange()
        )
        
        for warn_id, moderator_id, reason, time in warnings[:10]:
            moderator = inter.guild.get_member(moderator_id) or f"ID: {moderator_id}"
            embed.add_field(
                name=f"ID: {warn_id} | {time}",
                value=f"**Модератор:** {moderator}\n**Причина:** {reason}",
                inline=False
            )
        
        await inter.response.send_message(embed=embed)

    @commands.slash_command(name="punishments", description="История наказаний пользователя.")
    @commands.has_permissions(manage_messages=True)
    async def punishments(self, inter: disnake.ApplicationCommandInteraction,
                          user: disnake.Member = commands.Param(description="Выберите пользователя.")):
        
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                """SELECT action_type, moderator_id, duration, reason, time FROM punishments 
                WHERE user_id = ? AND guild_id = ? ORDER BY time DESC LIMIT 20""", 
                (user.id, inter.guild.id)
            )
            punishments = await cursor.fetchall()
            await cursor.close()
        
        if not punishments:
            embed = disnake.Embed(
                title=f"Наказания {user.display_name}",
                description="📝 Нет записей о наказаниях",
                color=disnake.Color.blue()
            )
            await inter.response.send_message(embed=embed)
            return
        
        embed = disnake.Embed(
            title=f"Наказания {user.display_name}",
            description=f"Всего записей: **{len(punishments)}**",
            color=disnake.Color.blue()
        )
        
        for action_type, moderator_id, duration, reason, time in punishments:
            moderator = inter.guild.get_member(moderator_id) or f"ID: {moderator_id}"
            action_emoji = {
                "mute": "🔇", "unmute": "🔊", "kick": "👢", 
                "ban": "🚫", "unban": "✅", "warn": "⚠️", 
                "unwarn": "✅", "clear": "🗑️"
            }.get(action_type, "📝")
            
            value = f"**Модератор:** {moderator}\n**Причина:** {reason}"
            if duration:
                value += f"\n**Длительность:** {duration}"
            
            embed.add_field(
                name=f"{action_emoji} {action_type.upper()} | {time}",
                value=value,
                inline=False
            )
        
        await inter.response.send_message(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        
        # Удаление сообщения по реакции "-смс"
        if message.content.lower() == "-смс" and message.reference:
            if message.channel.permissions_for(message.author).manage_messages:
                try:
                    replied_message = await message.channel.fetch_message(message.reference.message_id)
                    await replied_message.delete()
                    await message.delete()
                except:
                    pass

def setup(bot):
    bot.add_cog(Moderation(bot))