import asyncio
import aiohttp
import json
import os
from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from bs4 import BeautifulSoup
from datetime import datetime

# ================== НАСТРОЙКИ ==================
UNLOCK_CODE = "130290"

OLX_URL = "https://m.olx.ua/uk/elektronika/kompyutery-i-komplektuyuschie/komplektuyuschie-i-aksesuary/q-gtx-1080-ti-11gb/?search%5Border%5D=created_at%3Adesc"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Mobile) AppleWebKit/537.36 Chrome/120.0",
    "Accept-Language": "uk-UA,uk;q=0.9",
    "Referer": "https://www.olx.ua/"
}

DATA_FILE = "data.json"

# ===============================================

bot = Bot(token=os.getenv("BOT_TOKEN"))
dp = Dispatcher(bot)

users = {}
ads_cache = set()

# ================== КНОПКИ ==================
def main_kb():
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("📥 Получить данные", callback_data="get_ads"),
        InlineKeyboardButton("⚙️ Настройки", callback_data="settings")
    )
    return kb


def settings_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("✅ Авточекер", callback_data="toggle_auto"),
        InlineKeyboardButton("⏱ Интервал чекера", callback_data="interval"),
        InlineKeyboardButton("📊 Кол-во объявлений", callback_data="limit"),
        InlineKeyboardButton("🔍 Фильтр цены", callback_data="filter"),
        InlineKeyboardButton("💾 Сохранить", callback_data="save"),
        InlineKeyboardButton("⬅️ Назад", callback_data="back")
    )
    return kb


# ================== ЗАГРУЗКА ДАННЫХ ==================
def load_data():
    global users, ads_cache
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            users = data.get("users", {})
            ads_cache = set(data.get("ads", []))


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"users": users, "ads": list(ads_cache)}, f, ensure_ascii=False, indent=2)


# ================== OLX ПАРСЕР ==================
async def fetch_ads(limit=5):
    ads = []
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        async with session.get(OLX_URL, timeout=20) as resp:
            html = await resp.text()

    soup = BeautifulSoup(html, "lxml")

    for a in soup.select("a[href*='/obyavlenie/']"):
        title = a.get_text(strip=True)
        link = a.get("href")
        if not link.startswith("http"):
            link = "https://www.olx.ua" + link

        if link in ads_cache:
            continue

        ads.append({
            "title": title[:80],
            "url": link,
            "time": datetime.now().strftime("%H:%M:%S")
        })

        if len(ads) >= limit:
            break

    return ads


# ================== КОМАНДЫ ==================
@dp.message_handler(commands=["start"])
async def start(msg: types.Message):
    uid = str(msg.from_user.id)

    if uid not in users:
        users[uid] = {
            "unlocked": False,
            "auto": False,
            "interval": 60,
            "limit": 2,
            "price_min": 0,
            "price_max": 999999
        }
        save_data()

    if not users[uid]["unlocked"]:
        await msg.answer("🔒 Доступ заблокирован\n\nВведите код доступа:")
    else:
        await msg.answer("✅ Бот активен", reply_markup=main_kb())


@dp.message_handler()
async def unlock(msg: types.Message):
    uid = str(msg.from_user.id)

    if not users.get(uid):
        return

    if not users[uid]["unlocked"]:
        if msg.text.strip() == UNLOCK_CODE:
            users[uid]["unlocked"] = True
            save_data()
            await msg.answer("🔓 Бот разблокирован", reply_markup=main_kb())
        else:
            await msg.answer("❌ Неверный код")


# ================== CALLBACK ==================
@dp.callback_query_handler()
async def callbacks(call: types.CallbackQuery):
    uid = str(call.from_user.id)

    if not users.get(uid, {}).get("unlocked"):
        await call.answer("🔒 Нет доступа", show_alert=True)
        return

    if call.data == "get_ads":
        ads = await fetch_ads(users[uid]["limit"])

        if not ads:
            await call.message.answer("ℹ️ По текущим фильтрам объявлений нет.")
            return

        for ad in ads:
            ads_cache.add(ad["url"])
            await call.message.answer(
                f"🆕 <b>{ad['title']}</b>\n"
                f"🕒 {ad['time']}\n"
                f"🔗 {ad['url']}",
                parse_mode="HTML"
            )

        save_data()

    elif call.data == "settings":
        await call.message.edit_text("⚙️ Настройки:", reply_markup=settings_kb())

    elif call.data == "toggle_auto":
        users[uid]["auto"] = not users[uid]["auto"]
        save_data()
        await call.answer("Авточекер переключен")

    elif call.data == "interval":
        await call.message.answer("✍️ Напиши интервал в секундах")

    elif call.data == "limit":
        await call.message.answer("✍️ Сколько объявлений показывать?")

    elif call.data == "filter":
        await call.message.answer("✍️ Напиши цену: мин макс (пример: 5000 7000)")

    elif call.data == "save":
        save_data()
        await call.answer("💾 Сохранено")

    elif call.data == "back":
        await call.message.edit_text("🏠 Главное меню", reply_markup=main_kb())


# ================== АВТОЧЕКЕР ==================
async def auto_checker():
    await asyncio.sleep(10)
    while True:
        for uid, cfg in users.items():
            if not cfg["auto"]:
                continue

            ads = await fetch_ads(cfg["limit"])
            for ad in ads:
                ads_cache.add(ad["url"])
                try:
                    await bot.send_message(
                        uid,
                        f"🔥 <b>Новое объявление!</b>\n"
                        f"{ad['title']}\n"
                        f"🔗 {ad['url']}",
                        parse_mode="HTML"
                    )
                except:
                    pass

        save_data()
        await asyncio.sleep(60)


# ================== ЗАПУСК ==================
load_data()
loop = asyncio.get_event_loop()
loop.create_task(auto_checker())

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)