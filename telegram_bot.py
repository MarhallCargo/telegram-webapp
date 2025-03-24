from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
import aiohttp
import random
import string
from aiogram import executor

# 🔹 Подключение к Telegram
bot = Bot(token="7124484653:AAE1TwK7RhdYfFXjMRCOg5olc35iMWGY20I")
dp = Dispatcher(bot)

# 🔹 Генератор случайных логина и пароля
def generate_credentials():
    chinese_parts = [
        "Li", "Zhao", "Wang", "Wei", "Ming", "Chen", "Liu", "Zhang", "Huang", "Ma",
        "Xiao", "Hong", "Mei", "Zhi", "Wu", "Fi", "Chan", "Man", "Gan", "Zhong", "Huong", "Ku",
        "Ni", "Ling", "Mai", "Yuan", "Qing", "Hai", "Yue", "Feng", "Ping", "Zhi",
        "Hang", "Shen", "Xi", "Maimai", "Nan", "Chi", "Zhou"
    ]

    name = random.choice(chinese_parts) + random.choice(chinese_parts) + random.choice(chinese_parts)
    password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    return name, password

# 🔹 Хендлер на /start
@dp.message_handler(commands=["start"])
async def handle_start(message: Message):
    telegram_id = str(message.from_user.id)

    login, password = generate_credentials()

    # Попытка зарегистрировать пользователя через FastAPI
    async with aiohttp.ClientSession() as session:
        async with session.post("http://localhost:8000/auth/telegram_register", data={
            "telegram_id": telegram_id,
            "username": login,
            "password": password
        }) as response:
            result = await response.json()

    if result.get("message") == "Пользователь успешно зарегистрирован":
        await message.answer(
            f"✅ Вы зарегистрированы!\n\n"
            f"Логин: `{login}`\n"
            f"Пароль: `{password}`\n\n"
            f"Теперь вы можете войти в приложение."
        )
    else:
        # уже зарегистрирован
        await message.answer(
            f"👋 Вы уже зарегистрированы!\n"
            f"Ваш логин: `{result.get('username')}`"
        )

if __name__ == "__main__":
    from asyncio import run
    executor.start_polling(dp, skip_updates=True)
