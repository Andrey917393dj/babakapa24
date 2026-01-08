import asyncio
from aiogram import Bot, Dispatcher, types
import os

TOKEN = os.getenv("BOT_TOKEN")  # вставь сюда токен
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

ACCESS_CODE = "130290"
access_granted = False  # глобальная переменная состояния

WATCHED_URLS = set()
SEARCH_URL = "https://m.olx.ua/uk/elektronika/kompyutery-i-komplektuyuschie/komplektuyuschie-i-aksesuary/q-gtx-1080-ti-11gb/?search%5Border%5D=created_at%3Adesc"

# старт
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    global access_granted
    if not access_granted:
        await message.reply("Доступ заблокирован. Чтобы разблокировать, введите код.")
    else:
        await message.reply("Бот уже разблокирован! 🚀")

# обработка текста (кода)
@dp.message_handler()
async def check_code(message: types.Message):
    global access_granted
    if not access_granted:
        if message.text.strip() == ACCESS_CODE:
            access_granted = True
            await message.reply("✅ Бот разблокирован! Теперь у вас есть все функции.")
            # здесь можно запустить автопроверку
            asyncio.create_task(auto_checker())
        else:
            await message.reply("❌ Неверный код! Попробуйте снова.")
    else:
        await message.reply("Бот уже разблокирован. Для проверки новых объявлений используйте кнопку 'Получить данные'.")

# пример автопроверки (placeholder)
async def auto_checker():
    while True:
        # здесь логика проверки OLX
        print("Проверка новых объявлений...")
        await asyncio.sleep(300)  # каждые 5 минут

# кнопка "Получить данные"
@dp.message_handler(lambda message: message.text.lower() == "получить данные")
async def manual_check(message: types.Message):
    if access_granted:
        await message.reply("🔎 Проверка объявлений OLX...")
        # здесь логика парсера и отправки новых объявлений
    else:
        await message.reply("Доступ заблокирован. Введите код для разблокировки.")

# запуск
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
