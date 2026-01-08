import asyncio
import requests
import json
import csv
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto
)
import os

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ACCESS_CODE = "130290"

SEARCH_URL = "https://m.olx.ua/uk/elektronika/kompyutery-i-komplektuyuschie/komplektuyuschie-i-aksesuary/q-gtx-1080-ti-11gb/?search%5Border%5D=created_at%3Adesc"

# ================= СОСТОЯНИЕ =================
authorized_users = set()
known_ads = {}  # url -> price

auto_check_enabled = True
check_interval = 300
track_limit = 5

min_price = 0
max_price = 999999
filter_brands = ["ASUS", "ZOTAC", "MSI"]
filter_areas = []

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot)

# ================= КНОПКИ =================
def main_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("📥 Получить данные")
    kb.add("⚙ Настройки", "📊 Статус")
    kb.add("🧹 Очистить память", "🛑 Стоп авто")
    return kb

def settings_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("1️⃣ Авто ВКЛ/ВЫКЛ")
    kb.add("2️⃣ Интервал", "3️⃣ Лимит")
    kb.add("4️⃣ Мин цена", "5️⃣ Макс цена")
    kb.add("⬅ Назад")
    return kb

# ================= OLX =================
def fetch_offers():
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(SEARCH_URL, headers=headers, timeout=15)
        text = r.text
        start = text.find('"offers":{')
        end = text.find('},"sort":', start)
        if start == -1 or end == -1:
            return []
        raw = text[start + 9:end + 1]
        data = json.loads(raw)
        return data.get("offers", [])
    except Exception as e:
        print("OLX error:", e)
        return []

# ================= ОСНОВНАЯ ЛОГИКА =================
async def send_ads(chat_id, force_show=False):
    offers = fetch_offers()
    sent = 0

    for o in offers:
        url = o.get("url")
        price = o.get("price", 0)
        name = o.get("name", "")
        area = o.get("areaServed", {}).get("name", "—")
        images = o.get("image", [])
        description = o.get("description", "")

        if not (min_price <= price <= max_price):
            continue
        if not any(b.upper() in name.upper() for b in filter_brands):
            continue
        if filter_areas and area not in filter_areas:
            continue

        # автопроверка — только новое
        if not force_show and url in known_ads:
            continue

        # обновление цены
        if url in known_ads and price < known_ads[url]:
            await bot.send_message(
                chat_id,
                f"💰 Цена снижена!\n{name}\nБыло: {known_ads[url]} грн\nСтало: {price} грн\n{url}"
            )

        known_ads[url] = price

        short_desc = description[:400]
        if len(description) > 400:
            short_desc += "..."

        text = (
            f"🔔 <b>{name}</b>\n"
            f"💰 <b>{price} грн</b>\n"
            f"📍 {area}\n\n"
            f"{short_desc}\n\n"
            f"🔗 {url}"
        )

        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("Открыть OLX", url=url))
        if description:
            kb.add(InlineKeyboardButton("Показать полностью", callback_data=f"desc|{url}"))

        # картинки
        if images:
            media = [InputMediaPhoto(img) for img in images]
            await bot.send_media_group(chat_id, media)

        await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)

        sent += 1
        if sent >= track_limit:
            break

    if sent == 0:
        await bot.send_message(chat_id, "ℹ️ По текущим фильтрам объявлений нет.")

# ================= АВТОЧЕКЕР =================
async def auto_checker():
    while True:
        if auto_check_enabled:
            for uid in authorized_users:
                await send_ads(uid, force_show=False)
        await asyncio.sleep(check_interval + random.randint(10, 30))

# ================= CALLBACK =================
@dp.callback_query_handler(lambda c: c.data.startswith("desc|"))
async def full_desc(c: types.CallbackQuery):
    url = c.data.split("|", 1)[1]
    await c.message.answer("📄 Полное описание доступно на OLX:\n" + url)
    await c.answer()

# ================= ХЕНДЛЕРЫ =================
@dp.message_handler(commands=["start"])
async def start(m: types.Message):
    if m.from_user.id not in authorized_users:
        await m.answer("🔒 Доступ заблокирован.\nВведите код.")
    else:
        await m.answer("✅ Бот активен", reply_markup=main_kb())

@dp.message_handler(lambda m: m.text == ACCESS_CODE)
async def unlock(m: types.Message):
    authorized_users.add(m.from_user.id)
    await m.answer("✅ Доступ открыт", reply_markup=main_kb())

@dp.message_handler(lambda m: m.text == "📥 Получить данные")
async def manual(m: types.Message):
    await send_ads(m.from_user.id, force_show=True)

@dp.message_handler(lambda m: m.text == "⚙ Настройки")
async def settings(m: types.Message):
    await m.answer("⚙ Настройки:", reply_markup=settings_kb())

@dp.message_handler(lambda m: m.text == "📊 Статус")
async def status(m: types.Message):
    await m.answer(
        f"Авто: {auto_check_enabled}\n"
        f"Интервал: {check_interval} сек\n"
        f"Лимит: {track_limit}\n"
        f"Цена: {min_price} – {max_price}"
    )

@dp.message_handler(lambda m: m.text == "🧹 Очистить память")
async def clear(m: types.Message):
    known_ads.clear()
    await m.answer("🧹 Память объявлений очищена")

@dp.message_handler(lambda m: m.text == "🛑 Стоп авто")
async def stop_auto(m: types.Message):
    global auto_check_enabled
    auto_check_enabled = False
    await m.answer("🛑 Автопроверка остановлена")

@dp.message_handler(lambda m: m.text.isdigit())
async def numbers(m: types.Message):
    global check_interval, track_limit, min_price, max_price
    n = int(m.text)

    if 30 <= n <= 3600:
        check_interval = n
        await m.answer(f"⏱ Интервал: {n} сек")
    elif 1 <= n <= 20:
        track_limit = n
        await m.answer(f"📦 Лимит: {n}")
    elif 100 <= n <= 100000:
        min_price = n
        await m.answer(f"⬇ Мин цена: {n}")
    elif n > min_price:
        max_price = n
        await m.answer(f"⬆ Макс цена: {n}")

# ================= ЗАПУСК =================
async def main():
    asyncio.create_task(auto_checker())
    await dp.start_polling()

if __name__ == "__main__":
    asyncio.run(main())
