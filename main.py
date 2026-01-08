import asyncio
import requests
import json
import csv
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
import os

# =================== НАСТРОЙКИ ===================
BOT_TOKEN = os.getenv("BOT_TOKEN")  # токен из переменной окружения
ACCESS_CODE = "130290"
SEARCH_URL = "https://m.olx.ua/uk/elektronika/kompyutery-i-komplektuyuschie/komplektuyuschie-i-aksesuary/q-gtx-1080-ti-11gb/?search%5Border%5D=created_at%3Adesc"

# =================== СОСТОЯНИЕ ===================
authorized_users = set()
known_ads = {}  # url: {price, description, images}
auto_check_enabled = True
check_interval = 300
track_limit = 5
min_price = 0
max_price = 999999
filter_brands = ["ASUS", "ZOTAC", "MSI"]
filter_areas = []
ad_history_file = "olx_history.csv"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# =================== КНОПКИ ===================
def main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📥 Получить данные")
    kb.add("⚙ Настройки", "📊 Статистика")
    kb.add("🛑 Стоп автопроверку")
    return kb

def settings_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("1️⃣ Автопроверка ВКЛ/ВЫКЛ")
    kb.add("2️⃣ Интервал проверки")
    kb.add("3️⃣ Кол-во объявлений")
    kb.add("4️⃣ Мин цена", "5️⃣ Макс цена")
    kb.add("6️⃣ Фильтры брендов")
    kb.add("7️⃣ Фильтры районов")
    kb.add("8️⃣ Очистить память объявлений")
    kb.add("⬅ Назад")
    return kb

# =================== OLX ===================
def fetch_offers():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(SEARCH_URL, headers=headers, timeout=15)
        text = r.text
        start = text.find('"offers":{')
        end = text.find('},"sort":', start)
        if start == -1 or end == -1:
            return []
        raw_json = text[start + 9:end + 1]
        data = json.loads(raw_json)
        return data.get("offers", [])
    except Exception as e:
        print("Ошибка fetch_offers:", e)
        return []

# =================== УВЕДОМЛЕНИЯ ===================
async def send_new_ads(chat_id):
    global known_ads
    offers = fetch_offers()
    sent = 0

    for offer in offers:
        url = offer.get("url")
        price = offer.get("price", 0)
        name = offer.get("name", "")
        area = offer.get("areaServed", {}).get("name", "Не указан")
        images = offer.get("image", [])
        description = offer.get("additionalType", "")

        # Фильтры
        if url in known_ads:
            old_price = known_ads[url]["price"]
            if price < old_price:
                known_ads[url]["price"] = price
                await bot.send_message(chat_id, f"💰 Цена снизилась!\n{name}\nСтарая: {old_price} грн\nНовая: {price} грн\n{url}")
            continue
        if not (min_price <= price <= max_price):
            continue
        if not any(brand.upper() in name.upper() for brand in filter_brands):
            continue
        if filter_areas and area not in filter_areas:
            continue

        known_ads[url] = {"price": price, "description": description, "images": images}

        # Сообщение с частичным описанием
        short_desc = description[:400] + ("..." if len(description) > 400 else "")
        msg = f"🔔 <b>НОВОЕ ОБЪЯВЛЕНИЕ OLX</b>\n\n"
        msg += f"🖥 <b>{name}</b>\n"
        msg += f"💰 Цена: <b>{price} грн</b>\n"
        msg += f"📍 Район: {area}\n"
        msg += f"{short_desc}\n"
        msg += f"🔗 {url}"

        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("Открыть на OLX", url=url))
        kb.add(InlineKeyboardButton("Сохранить в избранное", callback_data=f"save|{url}"))
        if len(description) > 400:
            kb.add(InlineKeyboardButton("Показать больше", callback_data=f"showdesc|{url}"))

        # Отправляем все картинки
        media = []
        for img in images:
            media.append(types.InputMediaPhoto(img))
        if media:
            await bot.send_media_group(chat_id, media)
        await bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=kb)

        # CSV
        try:
            with open(ad_history_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), name, price, area, url])
        except:
            pass

        sent += 1
        if sent >= track_limit:
            break

# =================== АВТОЧЕКЕР ===================
async def auto_checker():
    while True:
        if auto_check_enabled and authorized_users:
            for uid in authorized_users:
                try:
                    await send_new_ads(uid)
                except:
                    pass
        await asyncio.sleep(check_interval + random.randint(10,30))

# =================== CALLBACK ДЛЯ INLINE ===================
@dp.callback_query_handler(lambda c: c.data and c.data.startswith("save|"))
async def save_callback(cq: types.CallbackQuery):
    url = cq.data.split("|")[1]
    await cq.answer("✅ Сохранено в избранное")

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("showdesc|"))
async def showdesc_callback(cq: types.CallbackQuery):
    url = cq.data.split("|")[1]
    desc = known_ads.get(url, {}).get("description", "Описание недоступно")
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Скрыть", callback_data=f"hidedesc|{url}"))
    await cq.message.edit_text(f"📄 <b>Полное описание</b>\n{desc}", parse_mode="HTML", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data and c.data.startswith("hidedesc|"))
async def hidedesc_callback(cq: types.CallbackQuery):
    url = cq.data.split("|")[1]
    name = cq.data.split("|")[1]
    await cq.message.delete()
    await send_new_ads(cq.from_user.id)

# =================== ХЕНДЛЕРЫ ===================
@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    if msg.from_user.id not in authorized_users:
        await msg.answer("🔒 Доступ заблокирован.\nВведите код доступа.")
    else:
        await msg.answer("✅ Бот активен", reply_markup=main_keyboard())

@dp.message_handler(lambda m: m.text == ACCESS_CODE)
async def unlock(msg: types.Message):
    authorized_users.add(msg.from_user.id)
    await msg.answer("✅ Бот разблокирован!", reply_markup=main_keyboard())

@dp.message_handler(lambda m: m.text == "📥 Получить данные")
async def manual_check(msg: types.Message):
    if msg.from_user.id in authorized_users:
        await send_new_ads(msg.from_user.id)

@dp.message_handler(lambda m: m.text == "⚙ Настройки")
async def settings(msg: types.Message):
    await msg.answer("⚙ Меню настроек:", reply_markup=settings_keyboard())

@dp.message_handler(lambda m: m.text == "📊 Статистика")
async def stats(msg: types.Message):
    await msg.answer("📊 Функция статистики будет добавлена позднее (можно расширить CSV)")

@dp.message_handler(lambda m: m.text == "🛑 Стоп автопроверку")
async def stop_auto(msg: types.Message):
    global auto_check_enabled
    auto_check_enabled = False
    await msg.answer("🛑 Автопроверка остановлена")

# =================== ЗАПУСК ===================
async def main():
    asyncio.create_task(auto_checker())
    await dp.start_polling()

if __name__ == "__main__":
    asyncio.run(main())
