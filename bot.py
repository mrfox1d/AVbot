import os
import disnake
from disnake.ext import commands
import os

TOKEN = os.getenv("TOKEN")

intents = disnake.Intents.all()

bot = commands.Bot(
    command_prefix=".",
    intents=intents,
    help_command=None
)


# ------------------ ИНИЦИАЛИЗАЦИЯ БД ВО ВСЕХ КОГАХ ------------------

async def init_all_databases():
    await bot.wait_until_ready()

    print("🔧 Инициализация баз данных...")

    for cog in bot.cogs.values():
        if hasattr(cog, "init_db"):
            try:
                await cog.init_db()
                print(f"✅ {cog.__class__.__name__} — БД готова")
            except Exception as e:
                print(f"❌ Ошибка БД в {cog.__class__.__name__}: {e}")

    print("🎉 Все базы инициализированы!\n")


# ------------------ СОБЫТИЯ БОТА ------------------

@bot.event
async def on_ready():
    print(f"🤖 Бот запущен как {bot.user} (ID: {bot.user.id})")

    await bot.change_presence(
        activity=disnake.Activity(
            type=disnake.ActivityType.playing,
            name="Minecraft | Сервер: AquaLand"
        ),
        status=disnake.Status.dnd
    )

    # Инициализация БД
    await init_all_databases()


# ------------------ ЗАГРУЗКА КОГОВ ------------------

def load_cogs():
    print("📦 Загрузка когов...")
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            try:
                bot.load_extension(f"cogs.{filename[:-3]}")
                print(f"✅ Загружен cog: {filename}")
            except Exception as e:
                print(f"❌ Ошибка загрузки {filename}: {e}")


load_cogs()


# ------------------ ЗАПУСК ------------------

bot.run(TOKEN)