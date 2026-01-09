import asyncio
import json
import os
import requests
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, executor, types

BOT_TOKEN = os.getenv("BOT_TOKEN")

bot = Bot(BOT_TOKEN)
dp = Dispatcher(bot)

ACCESS_CODE = "130290"

OLX_URL = "https://www.olx.ua/uk/elektronika/kompyutery-i-komplektuyuschie/komplektuyuschie-i-aksesuary/q-gtx-1080-ti-11gb/?search%5Border%5D=created_at%3Adesc"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

DATA_FILE = "data.json"

DEFAULT_USER = {
    "authorized": False,
    "auto": False,
    "interval": 300,
    "limit": 5,
    "known": []
}

def load():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

users = load()

def main_kb():
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📥 Получить данные", callback_data="get"))
    kb.add(types.InlineKeyboardButton("⚙️ Настройки", callback_data="settings"))
    return kb

def settings_kb(uid):
    u = users[uid]
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(
        f"Авточекер {'✅' if u['auto'] else '❌'}", callback_data="toggle_auto"
    ))
    kb.add(types.InlineKeyboardButton(
        f"Лимит объявлений: {u['limit']}", callback_data="limit"
    ))
    kb.add(types.InlineKeyboardButton("⬅ Назад", callback_data="back"))
    return kb

def fetch_ads(limit):
    r = requests.get(OLX_URL, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")

    ads = []
    cards = soup.find_all("div", {"data-testid": "l-card"})
    for card in cards[:limit]:
        try:
            title = card.find("h4").get_text(strip=True)
            price = card.find("p", {"data-testid": "ad-price"}).get_text(strip=True)
            loc = card.find("p", {"data-testid": "location-date"}).get_text(strip=True)
            link = "https://www.olx.ua" + card.find("a", href=True)["href"]
            img = card.find("img")["src"] if card.find("img") else None

            ads.append({
                "title": title,
                "price": price,
                "loc": loc,
                "link": link,
                "img": img
            })
        except:
            continue
    return ads

@dp.message_handler(commands=["start"])
async def start(m: types.Message):
    uid = str(m.from_user.id)
    if uid not in users:
        users[uid] = DEFAULT_USER.copy()
        save(users)

    if not users[uid]["authorized"]:
        await m.answer("🔒 Доступ заблокирован\n\nВведите код:")
    else:
        await m.answer("Готов к работе ✅", reply_markup=main_kb())

@dp.message_handler()
async def code_check(m: types.Message):
    uid = str(m.from_user.id)
    if uid not in users:
        return

    if not users[uid]["authorized"]:
        if m.text.strip() == ACCESS_CODE:
            users[uid]["authorized"] = True
            save(users)
            await m.answer("✅ Бот разблокирован", reply_markup=main_kb())
        else:
            await m.answer("❌ Неверный код")

@dp.callback_query_handler()
async def callbacks(c: types.CallbackQuery):
    uid = str(c.from_user.id)
    if uid not in users or not users[uid]["authorized"]:
        await c.answer("Нет доступа", show_alert=True)
        return

    if c.data == "get":
        ads = fetch_ads(users[uid]["limit"])
        if not ads:
            await c.message.answer("ℹ️ Объявлений нет")
        for ad in ads:
            text = (
                f"📌 {ad['title']}\n"
                f"💰 {ad['price']}\n"
                f"📍 {ad['loc']}\n"
                f"🔗 {ad['link']}"
            )
            if ad["img"]:
                await c.message.answer_photo(ad["img"], caption=text)
            else:
                await c.message.answer(text)

    elif c.data == "settings":
        await c.message.edit_text("⚙️ Настройки", reply_markup=settings_kb(uid))

    elif c.data == "toggle_auto":
        users[uid]["auto"] = not users[uid]["auto"]
        save(users)
        await c.message.edit_reply_markup(reply_markup=settings_kb(uid))

    elif c.data == "limit":
        users[uid]["limit"] = 10 if users[uid]["limit"] == 5 else 5
        save(users)
        await c.message.edit_reply_markup(reply_markup=settings_kb(uid))

    elif c.data == "back":
        await c.message.edit_text("Главное меню", reply_markup=main_kb())

async def auto_checker():
    while True:
        for uid, u in users.items():
            if not u["authorized"] or not u["auto"]:
                continue

            ads = fetch_ads(5)
            for ad in ads:
                if ad["link"] not in u["known"]:
                    u["known"].append(ad["link"])
                    save(users)
                    await bot.send_message(uid, f"🆕 Новое объявление!\n{ad['title']}\n{ad['price']}\n{ad['link']}")
        await asyncio.sleep(300)

async def on_startup(dp):
    asyncio.create_task(auto_checker())

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)