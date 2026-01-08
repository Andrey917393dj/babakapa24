import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import os

TOKEN = os.getenv("BOT_TOKEN")  # токен из поля Bothost
bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# ======================
# НАСТРОЙКИ ПО УМОЛЧАНИЮ
# ======================
settings = {
    "auto_checker": True,          # Автоматический чекер вкл/выкл
    "check_interval": 5,           # Интервал чекера в минутах
    "offers_count": 2,             # Сколько предложений показывать
    "min_filter": 100,             # Минимальная сумма фильтра
}

# ======================
# Функции
# ======================
def get_wallet_data():
    # Заглушка: выводим столько предложений, сколько указано в settings
    count = settings["offers_count"]
    return (
        "🟢 ПОКУПКА USDT (min {} грн)\n".format(settings["min_filter"]) +
        "\n".join(f"{i+1}️⃣ 42.{60+i} грн | лимит 100–20 000" for i in range(count)) +
        "\n\n🔴 ПРОДАЖА USDT (min {} грн)\n".format(settings["min_filter"]) +
        "\n".join(f"{i+1}️⃣ 42.{95-i} грн | лимит 100–30 000" for i in range(count))
    )

# ======================
# Главное меню
# ======================
def main_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🔄 Получить данные", callback_data="get_data"),
        InlineKeyboardButton("⚙️ Настройки", callback_data="settings_menu")
    )
    return kb

# ======================
# Кнопки меню настроек
# ======================
def settings_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    # Отображаем галочку/крестик
    kb.add(
        InlineKeyboardButton(f"1️⃣ Авто чекер: {'✅' if settings['auto_checker'] else '❌'}", callback_data="toggle_1"),
        InlineKeyboardButton(f"2️⃣ Интервал чекера: {settings['check_interval']} мин", callback_data="toggle_2"),
        InlineKeyboardButton(f"3️⃣ Кол-во предложений: {settings['offers_count']}", callback_data="toggle_3"),
        InlineKeyboardButton(f"4️⃣ Минимальная сумма фильтра: {settings['min_filter']}", callback_data="toggle_4"),
        InlineKeyboardButton("💾 Сохранить", callback_data="save_settings"),
        InlineKeyboardButton("⬅ Вернуться назад", callback_data="back_main")
    )
    return kb

# ======================
# Хэндлеры
# ======================
@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await message.answer("🤖 Wallet P2P Monitor запущен!\n\nВыберите действие:", reply_markup=main_keyboard())

@dp.callback_query_handler(lambda c: c.data == "get_data")
async def send_data(callback: types.CallbackQuery):
    await callback.message.answer(get_wallet_data())
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "settings_menu")
async def open_settings(callback: types.CallbackQuery):
    await callback.message.answer("⚙️ Меню настроек:", reply_markup=settings_keyboard())
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("toggle_"))
async def toggle_option(callback: types.CallbackQuery):
    option = callback.data.split("_")[1]
    
    # Пункт 1 — вкл/выкл
    if option == "1":
        settings["auto_checker"] = not settings["auto_checker"]
    # Пункт 2 — интервал чекера
    elif option == "2":
        await callback.message.answer("Введите новый интервал в минутах:")
        dp.register_message_handler(change_interval, state=None, content_types=types.ContentTypes.TEXT)
    # Пункт 3 — кол-во предложений
    elif option == "3":
        await callback.message.answer("Введите новое количество предложений:")
        dp.register_message_handler(change_offers, state=None, content_types=types.ContentTypes.TEXT)
    # Пункт 4 — фильтр
    elif option == "4":
        await callback.message.answer("Введите минимальную сумму фильтра (грн):")
        dp.register_message_handler(change_filter, state=None, content_types=types.ContentTypes.TEXT)
    
    # Обновляем меню
    await callback.message.edit_reply_markup(settings_keyboard())
    await callback.answer()

# ======================
# Функции изменения через чат
# ======================
async def change_interval(message: types.Message):
    try:
        val = int(message.text)
        if val <= 0:
            raise ValueError
        settings["check_interval"] = val
        await message.answer(f"Интервал чекера изменён на {val} мин.")
    except ValueError:
        await message.answer("Ошибка: введи положительное число.")
    finally:
        dp.unregister_message_handler(change_interval)

async def change_offers(message: types.Message):
    try:
        val = int(message.text)
        if val <= 0:
            raise ValueError
        settings["offers_count"] = val
        await message.answer(f"Количество предложений изменено на {val}.")
    except ValueError:
        await message.answer("Ошибка: введи положительное число.")
    finally:
        dp.unregister_message_handler(change_offers)

async def change_filter(message: types.Message):
    try:
        val = int(message.text)
        if val <= 0:
            raise ValueError
        settings["min_filter"] = val
        await message.answer(f"Минимальная сумма фильтра изменена на {val} грн.")
    except ValueError:
        await message.answer("Ошибка: введи положительное число.")
    finally:
        dp.unregister_message_handler(change_filter)

@dp.callback_query_handler(lambda c: c.data == "save_settings")
async def save_settings(callback: types.CallbackQuery):
    await callback.message.answer("💾 Настройки сохранены!")
    await callback.answer()

@dp.callback_query_handler(lambda c: c.data == "back_main")
async def back_main(callback: types.CallbackQuery):
    await callback.message.answer("Главное меню:", reply_markup=main_keyboard())
    await callback.answer()

# ======================
# Авто чекер
# ======================
async def auto_checker():
    while True:
        if settings["auto_checker"]:
            # Заглушка: можно отправлять данные себе
            # await bot.send_message(YOUR_CHAT_ID, get_wallet_data())
            pass
        await asyncio.sleep(settings["check_interval"] * 60)

# ======================
# Главная функция
# ======================
async def main():
    asyncio.create_task(auto_checker())
    await dp.start_polling()

if __name__ == "__main__":
    asyncio.run(main())
