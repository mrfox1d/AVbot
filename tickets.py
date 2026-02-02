# tickets.py
import disnake
from disnake.ext import commands
from disnake.ui import Button, View, Modal, TextInput, Select
import aiosqlite
import asyncio
from datetime import datetime
import io

class TicketSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.path = "dbs/file.db"
        self.ticket_cooldowns = {}

    async def init_db(self):
        async with aiosqlite.connect(self.path) as db:

            await db.execute("PRAGMA journal_mode=WAL")


            await db.execute("PRAGMA foreign_keys = ON")
            
            # Таблица тикетов
            await db.execute("""CREATE TABLE IF NOT EXISTS tickets (
                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                             author_id INTEGER,
                             created_at TEXT,
                             status TEXT DEFAULT 'open',
                             channel_id INTEGER,
                             moderator_id INTEGER DEFAULT NULL,
                             guild_id INTEGER,
                             ticket_type TEXT DEFAULT 'general',
                             closed_at TEXT DEFAULT NULL,
                             close_reason TEXT DEFAULT NULL)""")
            
            # Сообщения в тикетах
            await db.execute("""CREATE TABLE IF NOT EXISTS ticket_messages (
                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                             ticket_id INTEGER,
                             author_id INTEGER,
                             message TEXT,
                             created_at TEXT,
                             attachments TEXT DEFAULT NULL,
                             FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE)""")
            
            # Транскрипты
            await db.execute("""CREATE TABLE IF NOT EXISTS transcripts (
                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                             ticket_id INTEGER,
                             content TEXT,
                             created_at TEXT,
                             FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE)""")
            
            # Конфигурация
            await db.execute("""CREATE TABLE IF NOT EXISTS ticket_config (
                             guild_id INTEGER PRIMARY KEY,
                             category_id INTEGER DEFAULT NULL,
                             create_channel_id INTEGER DEFAULT NULL,
                             create_message_id INTEGER DEFAULT NULL,
                             log_channel_id INTEGER DEFAULT NULL,
                             support_role_id INTEGER DEFAULT NULL,
                             max_tickets_per_user INTEGER DEFAULT 3,
                             ticket_cooldown INTEGER DEFAULT 300,
                             require_topic BOOLEAN DEFAULT 0,
                             auto_close_hours INTEGER DEFAULT 24,
                             welcome_message TEXT DEFAULT 'Спасибо за обращение! Ожидайте ответа модератора.',
                             ticket_types TEXT DEFAULT 'general,report,bug,support')""")
            
            # Темы тикетов
            await db.execute("""CREATE TABLE IF NOT EXISTS ticket_topics (
                             id INTEGER PRIMARY KEY AUTOINCREMENT,
                             guild_id INTEGER,
                             name TEXT,
                             description TEXT,
                             emoji TEXT DEFAULT '🎫')""")
            
            await db.commit()

    async def get_ticket_config(self, guild_id):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute("SELECT * FROM ticket_config WHERE guild_id = ?", (guild_id,))
            config = await cursor.fetchone()
            await cursor.close()
            
            if config:
                return {
                    'guild_id': config[0],
                    'category_id': config[1],
                    'create_channel_id': config[2],
                    'create_message_id': config[3],
                    'log_channel_id': config[4],
                    'support_role_id': config[5],
                    'max_tickets_per_user': config[6],
                    'ticket_cooldown': config[7],
                    'require_topic': bool(config[8]),
                    'auto_close_hours': config[9],
                    'welcome_message': config[10],
                    'ticket_types': config[11].split(',') if config[11] else ['general']
                }
            
            # Конфиг по умолчанию
            default_types = 'general,report,bug,support,other'
            await db.execute(
                "INSERT INTO ticket_config (guild_id, ticket_types) VALUES (?, ?)",
                (guild_id, default_types)
            )
            await db.commit()
            
            return {
                'guild_id': guild_id,
                'category_id': None,
                'create_channel_id': None,
                'create_message_id': None,
                'log_channel_id': None,
                'support_role_id': None,
                'max_tickets_per_user': 3,
                'ticket_cooldown': 300,
                'require_topic': False,
                'auto_close_hours': 24,
                'welcome_message': 'Спасибо за обращение! Ожидайте ответа модератора.',
                'ticket_types': default_types.split(',')
            }

    async def get_user_tickets_count(self, guild_id, user_id):
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND author_id = ? AND status = 'open'",
                (guild_id, user_id)
            )
            count = await cursor.fetchone()
            await cursor.close()
            return count[0] if count else 0

    async def create_ticket(self, guild_id, author_id, channel_id, ticket_type='general'):
        async with aiosqlite.connect(self.path) as db:
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor = await db.execute(
                "INSERT INTO tickets (guild_id, author_id, created_at, channel_id, ticket_type) VALUES (?, ?, ?, ?, ?)",
                (guild_id, author_id, created_at, channel_id, ticket_type)
            )
            await db.commit()
            return cursor.lastrowid

    async def close_ticket(self, ticket_id, moderator_id=None, reason="Не указана"):
        async with aiosqlite.connect(self.path) as db:
            closed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await db.execute(
                "UPDATE tickets SET status = 'closed', moderator_id = ?, closed_at = ?, close_reason = ? WHERE id = ?",
                (moderator_id, closed_at, reason, ticket_id)
            )
            await db.commit()

    async def add_ticket_moderator(self, ticket_id, moderator_id):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE tickets SET moderator_id = ? WHERE id = ?", (moderator_id, ticket_id))
            await db.commit()

    async def save_transcript(self, ticket_id, channel):
        """Сохранить транскрипт тикета"""
        messages = []
        
        async for message in channel.history(limit=None, oldest_first=True):
            if message.author.bot and not message.content and not message.embeds:
                continue
                
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            author = f"{message.author.name}#{message.author.discriminator}"
            
            content = message.clean_content
            if not content and message.embeds:
                content = "[EMBED]"
            elif not content and message.attachments:
                content = "[ATTACHMENT]"
            
            attachments = ""
            if message.attachments:
                attachments = " | Вложения: " + ", ".join([att.filename for att in message.attachments])
            
            messages.append(f"[{timestamp}] {author}: {content}{attachments}")
        
        transcript_content = "\n".join(messages)
        
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO transcripts (ticket_id, content, created_at) VALUES (?, ?, ?)",
                (ticket_id, transcript_content, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            await db.commit()
        
        return transcript_content

    async def check_auto_close_tickets(self):
        """Проверка неактивных тикетов для автозакрытия"""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                # Здесь можно добавить логику автозакрытия тикетов
                pass
            except Exception as e:
                print(f"Ошибка в check_auto_close_tickets: {e}")
            
            await asyncio.sleep(3600)  # Проверка каждый час

    @commands.slash_command(name="ticket_setup", description="Настроить систему тикетов")
    @commands.has_permissions(administrator=True)
    async def ticket_setup(self, inter: disnake.ApplicationCommandInteraction):
        await inter.response.defer()
        
        config = await self.get_ticket_config(inter.guild.id)
        
        if config['category_id']:
            await inter.followup.send("❌ Система тикетов уже настроена!", ephemeral=True)
            return
        
        # Создаем категорию
        category = await inter.guild.create_category("🎫 Тикеты")
        
        # Создаем канал для создания тикетов
        create_channel = await inter.guild.create_text_channel(
            "создать-тикет",
            category=category,
            topic="Создайте тикет, нажав на кнопку ниже"
        )
        
        # Обновляем конфиг
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE ticket_config SET category_id = ?, create_channel_id = ? WHERE guild_id = ?",
                (category.id, create_channel.id, inter.guild.id)
            )
            await db.commit()
        
        # Создаем сообщение с кнопками
        config = await self.get_ticket_config(inter.guild.id)
        view = TicketCreateView(self.bot, config)
        
        embed = disnake.Embed(
            title="🎫 Система поддержки",
            description="Нажмите на кнопку ниже, чтобы создать тикет.\nВыберите тип обращения:",
            color=disnake.Color.blue()
        )
        
        message = await create_channel.send(embed=embed, view=view)
        
        # Сохраняем ID сообщения
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE ticket_config SET create_message_id = ? WHERE guild_id = ?",
                (message.id, inter.guild.id)
            )
            await db.commit()
        
        await inter.followup.send(f"✅ Система тикетов настроена!\nКанал: {create_channel.mention}", ephemeral=True)

    @commands.Cog.listener()
    async def on_button_click(self, inter: disnake.MessageInteraction):
        if not inter.component.custom_id.startswith("create_ticket_"):
            if inter.component.custom_id == "accept_ticket":
                await self.handle_ticket_accept(inter)
            elif inter.component.custom_id == "close_ticket":
                await self.handle_ticket_close(inter)
            elif inter.component.custom_id == "transcript_ticket":
                await self.handle_ticket_transcript(inter)
            return
        
        # Создание тикета
        ticket_type = inter.component.custom_id.replace("create_ticket_", "")
        await self.handle_ticket_create(inter, ticket_type)

    async def handle_ticket_create(self, inter: disnake.MessageInteraction, ticket_type: str):
        """Обработка создания тикета"""
        config = await self.get_ticket_config(inter.guild.id)
        
        # Проверка кулдауна
        if inter.author.id in self.ticket_cooldowns:
            last_ticket = self.ticket_cooldowns[inter.author.id]
            cooldown = config['ticket_cooldown']
            elapsed = (datetime.now() - last_ticket).total_seconds()
            
            if elapsed < cooldown:
                remaining = int(cooldown - elapsed)
                await inter.response.send_message(
                    f"⏰ Вы сможете создать новый тикет через {remaining} секунд.",
                    ephemeral=True
                )
                return
        
        # Проверка лимита тикетов
        user_tickets = await self.get_user_tickets_count(inter.guild.id, inter.author.id)
        if user_tickets >= config['max_tickets_per_user']:
            await inter.response.send_message(
                f"❌ У вас уже {user_tickets} открытых тикетов. Максимум: {config['max_tickets_per_user']}.",
                ephemeral=True
            )
            return
        
        # Создаем тикет
        if not config['category_id']:
            await inter.response.send_message("❌ Система тикетов не настроена.", ephemeral=True)
            return
        
        category = inter.guild.get_channel(config['category_id'])
        if not category:
            await inter.response.send_message("❌ Категория тикетов не найдена.", ephemeral=True)
            return
        
        await inter.response.defer(ephemeral=True)
        
        # Создаем канал тикета
        ticket_channel = await inter.guild.create_text_channel(
            name=f"ticket-{inter.author.name}-{datetime.now().strftime('%d%m')}",
            category=category,
            topic=f"Тикет пользователя {inter.author.name} | Тип: {ticket_type}"
        )
        
        # Настраиваем права
        await ticket_channel.set_permissions(inter.author, read_messages=True, send_messages=True)
        await ticket_channel.set_permissions(inter.guild.default_role, read_messages=False)
        
        if config['support_role_id']:
            support_role = inter.guild.get_role(config['support_role_id'])
            if support_role:
                await ticket_channel.set_permissions(support_role, read_messages=True, send_messages=True)
        
        # Создаем запись в БД
        ticket_id = await self.create_ticket(inter.guild.id, inter.author.id, ticket_channel.id, ticket_type)
        
        # Устанавливаем кд
        self.ticket_cooldowns[inter.author.id] = datetime.now()
        
        # Отправляем приветственное сообщение
        view = TicketActionsView()
        
        embed = disnake.Embed(
    title=f"🎫 Тикет #{ticket_id}",
    description=f"**{config['welcome_message']}**",
    color=disnake.Color.from_rgb(88, 101, 242)
)

        embed.add_field(name="👤 Пользователь", value=inter.author.mention, inline=True)
        embed.add_field(name="📁 Тип", value=f"`{ticket_type}`", inline=True)
        embed.add_field(name="🕒 Создан", value=f"<t:{int(datetime.now().timestamp())}:R>", inline=True)
        embed.set_thumbnail(url=inter.author.display_avatar.url)
        embed.set_footer(text="Используйте кнопки ниже для управления тикетом")

        embed.add_field(name="👤 Автор", value=inter.author.mention, inline=True)
        embed.add_field(name="📅 Создан", value=datetime.now().strftime("%d.%m.%Y %H:%M"), inline=True)
        embed.add_field(name="🔖 Тип", value=ticket_type.capitalize(), inline=True)
        embed.set_footer(text="Тикет будет автоматически закрыт через 24 часа неактивности")
        
        await ticket_channel.send(embed=embed, view=view)
        await ticket_channel.send(f"{inter.author.mention} {f'<@&{config['support_role_id']}>' if config['support_role_id'] else ''}")
        
        await inter.followup.send(
            f"✅ Тикет создан: {ticket_channel.mention}",
            ephemeral=True
        )
        
        # Логируем создание тикета
        logs_cog = self.bot.get_cog('Logs')
        if logs_cog:
            await logs_cog.log_ticket_action(
                guild_id=inter.guild.id,
                user_id=inter.author.id,
                action="ticket_create",
                ticket_id=ticket_id,
                extra_info=f"Тип: {ticket_type} | Канал: {ticket_channel.mention}"
            )
        
        # Логируем в лог-канал тикетов
        if config['log_channel_id']:
            log_channel = inter.guild.get_channel(config['log_channel_id'])
            if log_channel:
                embed = disnake.Embed(
                    title="🎫 Новый тикет",
                    description=f"**Тикет:** #{ticket_id}\n"
                              f"**Автор:** {inter.author.mention} ({inter.author.id})\n"
                              f"**Тип:** {ticket_type}\n"
                              f"**Канал:** {ticket_channel.mention}",
                    color=disnake.Color.green(),
                    timestamp=datetime.utcnow()
                )
                await log_channel.send(embed=embed)

    async def handle_ticket_accept(self, inter: disnake.MessageInteraction):
        """Обработка принятия тикета"""
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT * FROM tickets WHERE channel_id = ?", (inter.channel.id,)
            )
            ticket = await cursor.fetchone()
            await cursor.close()
            
            if not ticket:
                await inter.response.send_message("❌ Тикет не найден.", ephemeral=True)
                return
            
            if ticket[5]:  # moderator_id
                await inter.response.send_message(
                    f"❌ Тикет уже принят пользователем <@{ticket[5]}>.",
                    ephemeral=True
                )
                return
            
            await self.add_ticket_moderator(ticket[0], inter.author.id)
            
            embed = disnake.Embed(
                title="✅ Тикет принят",
                description=f"Модератор {inter.author.mention} принял тикет.",
                color=disnake.Color.green()
            )
            await inter.channel.send(embed=embed)
            
            await inter.response.send_message("✅ Вы приняли тикет.", ephemeral=True)
            
            # Логируем принятие тикета
            logs_cog = self.bot.get_cog('Logs')
            if logs_cog:
                await logs_cog.log_ticket_action(
                    guild_id=inter.guild.id,
                    user_id=inter.author.id,
                    action="ticket_accept",
                    ticket_id=ticket[0],
                    extra_info=f"Модератор: {inter.author.mention}"
                )

    async def handle_ticket_close(self, inter: disnake.MessageInteraction):
        """Обработка закрытия тикета"""
        modal = TicketCloseModal()
        await inter.response.send_modal(modal)
        
        try:
            modal_inter: disnake.ModalInteraction = await self.bot.wait_for(
                "modal_submit",
                timeout=300.0,
                check=lambda m: m.custom_id == "ticket_close_modal" and m.author.id == inter.author.id
            )
            
            reason = modal_inter.text_values.get("reason", "Не указана")
            
            # Получаем информацию о тикете
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute(
                    "SELECT * FROM tickets WHERE channel_id = ?", (inter.channel.id,)
                )
                ticket = await cursor.fetchone()
                await cursor.close()
                
                if not ticket:
                    await modal_inter.response.send_message("❌ Тикет не найден.", ephemeral=True)
                    return
                
                ticket_id = ticket[0]
                author_id = ticket[1]
            
            # Сохраняем транскрипт
            transcript = await self.save_transcript(ticket_id, inter.channel)
            
            # Закрываем тикет в БД
            await self.close_ticket(ticket_id, inter.author.id, reason)
            
            # Уведомляем о закрытии
            embed = disnake.Embed(
                title="❌ Тикет закрыт",
                description=f"**Причина:** {reason}\n**Закрыл:** {inter.author.mention}",
                color=disnake.Color.red()
            )
            await inter.channel.send(embed=embed)
            
            await modal_inter.response.send_message("✅ Тикет будет закрыт через 5 секунд...", ephemeral=True)
            
            # Отправляем транскрипт создателю тикета
            try:
                author = inter.guild.get_member(author_id)
                if author:
                    transcript_file = io.BytesIO(transcript.encode('utf-8'))
                    file = disnake.File(transcript_file, filename=f"ticket-{ticket_id}-transcript.txt")
                    
                    embed = disnake.Embed(
                        title=f"📋 Транскрипт тикета #{ticket_id}",
                        description=f"**Сервер:** {inter.guild.name}\n**Причина закрытия:** {reason}",
                        color=disnake.Color.blue()
                    )
                    await author.send(embed=embed, file=file)
            except:
                pass
            
            # Логируем закрытие тикета
            logs_cog = self.bot.get_cog('Logs')
            if logs_cog:
                await logs_cog.log_ticket_action(
                    guild_id=inter.guild.id,
                    user_id=inter.author.id,
                    action="ticket_close",
                    ticket_id=ticket_id,
                    extra_info=f"Причина: {reason}"
                )
            
            # Удаляем канал через 5 секунд
            await asyncio.sleep(5)
            await inter.channel.delete()
            
        except asyncio.TimeoutError:
            await inter.followup.send("❌ Время ожидания истекло.", ephemeral=True)

    async def handle_ticket_transcript(self, inter: disnake.MessageInteraction):
        """Обработка запроса транскрипта"""
        await inter.response.defer(ephemeral=True)
        
        async with aiosqlite.connect(self.path) as db:
            cursor = await db.execute(
                "SELECT * FROM tickets WHERE channel_id = ?", (inter.channel.id,)
            )
            ticket = await cursor.fetchone()
            await cursor.close()
            
            if not ticket:
                await inter.followup.send("❌ Тикет не найден.", ephemeral=True)
                return
            
            ticket_id = ticket[0]
        
        # Генерируем транскрипт
        transcript = await self.save_transcript(ticket_id, inter.channel)
        
        # Отправляем файл
        transcript_file = io.BytesIO(transcript.encode('utf-8'))
        file = disnake.File(transcript_file, filename=f"ticket-{ticket_id}-transcript.txt")
        
        await inter.followup.send(
            f"📋 Транскрипт тикета #{ticket_id}",
            file=file,
            ephemeral=True
        )

class TicketCreateView(View):
    """View для создания тикета с выбором типа"""
    
    def __init__(self, bot, config):
        super().__init__(timeout=None)
        self.bot = bot
        self.config = config
        
        # Добавляем кнопки для каждого типа тикета
        for ticket_type in self.config['ticket_types']:
            emoji = self.get_emoji_for_type(ticket_type)
            button = Button(
                label=ticket_type.capitalize(),
                emoji=emoji,
                style=disnake.ButtonStyle.primary,
                custom_id=f"create_ticket_{ticket_type}"
            )
            self.add_item(button)
    
    def get_emoji_for_type(self, ticket_type):
        emojis = {
            'general': '🎫',
            'report': '⚠️',
            'bug': '🐛',
            'support': '🛠️',
            'question': '❓',
            'suggestion': '💡',
            'other': '📝'
        }
        return emojis.get(ticket_type, '🎫')

class TicketActionsView(View):
    """View для управления тикетом"""
    
    def __init__(self):
        super().__init__(timeout=None)
        
        accept_button = Button(
            label="Принять",
            style=disnake.ButtonStyle.green,
            custom_id="accept_ticket",
            emoji="✅"
        )
        self.add_item(accept_button)
        
        close_button = Button(
            label="Закрыть",
            style=disnake.ButtonStyle.red,
            custom_id="close_ticket",
            emoji="❌"
        )
        self.add_item(close_button)
        
        transcript_button = Button(
            label="Транскрипт",
            style=disnake.ButtonStyle.blurple,
            custom_id="transcript_ticket",
            emoji="📋"
        )
        self.add_item(transcript_button)

class TicketCloseModal(Modal):
    """Модальное окно для закрытия тикета"""
    
    def __init__(self):
        components = [
            TextInput(
                label="Причина закрытия",
                placeholder="Укажите причину закрытия тикета...",
                custom_id="reason",
                style=disnake.TextInputStyle.paragraph,
                max_length=500,
                required=False
            )
        ]
        super().__init__(title="Закрытие тикета", custom_id="ticket_close_modal", components=components)

def setup(bot):
    bot.add_cog(TicketSystem(bot))