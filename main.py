import os
import sys
import json
import asyncio
import logging
import re
import random
from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

# --- НАСТРОЙКИ ---
logging.basicConfig(level=logging.INFO)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ACCESS_CODE = "130290"
TARGET_URL = "https://www.olx.ua/uk/elektronika/kompyutery-i-komplektuyuschie/komplektuyuschie-i-aksesuary/q-gtx-1080-ti-11gb/?search%5Border%5D=created_at%3Adesc"

# Файл для хранения куки на сервере, чтобы они не пропадали после перезапуска
COOKIE_STORAGE = "current_cookies.txt"

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot, storage=MemoryStorage())

# --- ЛОГИКА ---

def load_cookies():
    if os.path.exists(COOKIE_STORAGE):
        with open(COOKIE_STORAGE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""

def save_cookies(text):
    with open(COOKIE_STORAGE, "w", encoding="utf-8") as f:
        f.write(text)

def parse_cookies_to_dict(cookie_str):
    res = {}
    # Очищаем строку от префикса "Cookie: ", если он есть
    cookie_str = cookie_str.replace("Cookie: ", "").strip()
    for item in cookie_str.split(';'):
        if '=' in item:
            k, v = item.strip().split('=', 1)
            res[k] = v
    return res

async def fetch_olx():
    raw_cookies = load_cookies()
    if not raw_cookies:
        return "NO_COOKIES"
        
    cookies_dict = parse_cookies_to_dict(raw_cookies)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8",
        "Referer": "https://www.google.com/",
    }

    try:
        async with AsyncSession(impersonate="chrome121", headers=headers, cookies=cookies_dict) as s:
            r = await s.get(TARGET_URL, timeout=20)
            if r.status_code != 200:
                logging.error(f"OLX Error: {r.status_code}")
                return None
            
            soup = BeautifulSoup(r.text, 'lxml')
            ads = []
            items = soup.find_all('div', attrs={"data-cy": "ad-card-title"})
            
            for item in items:
                try:
                    link = item.find('a', href=True)
                    title = item.find('h4').text
                    # Ищем цену в родителе
                    parent = item.find_parent('div', attrs={"type": "list"}) or item.parent
                    price_tag = parent.find('p', attrs={"data-testid": "ad-price"})
                    price = price_tag.text if price_tag else "---"
                    
                    full_link = link['href']
                    if not full_link.startswith('http'):
                        full_link = "https://www.olx.ua" + full_link
                        
                    ads.append({"title": title, "price": price, "url": full_link})
                except: continue
            return ads
    except Exception as e:
        logging.error(f"Request error: {e}")
        return None

# --- ХЕНДЛЕРЫ ---

@dp.message_handler(commands=['start'])
async def cmd_start(m: types.Message):
    await m.answer("👋 <b>Бот готов к работе.</b>\n\nЕсли данные не приходят, скопируй Cookie из браузера, сохрани в .txt файл и скинь мне его в чат.", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("📥 Получить данные"))

# Хендлер для приема ФАЙЛА с куками
@dp.message_handler(content_types=['document'])
async def handle_docs(m: types.Message):
    # Скачиваем файл в память
    file_in_io = await bot.download_file_by_id(m.document.file_id)
    content = file_in_io.read().decode('utf-8')
    
    if "cf_bm" in content or "PHPSESSID" in content or "cookie" in content.lower():
        save_cookies(content)
        await m.answer("✅ <b>Файл принят!</b> Куки обновлены. Пробую сделать тестовый запрос...")
        
        ads = await fetch_olx()
        if ads and ads != "NO_COOKIES":
            await m.answer(f"🎉 Успех! Вижу {len(ads)} объявлений.")
        else:
            await m.answer("❌ Запрос всё равно не проходит. Возможно, куки скопированы не полностью или нужно пройти капчу в браузере.")
    else:
        await m.answer("⚠️ Файл не похож на куки. Убедись, что внутри строка вида <code>_cf_bm=...; PHPSESSID=...</code>")

@dp.message_handler(lambda m: m.text == "📥 Получить данные")
async def get_manual(m: types.Message):
    await m.answer("🔎 Обращаюсь к OLX...")
    ads = await fetch_olx()
    
    if ads == "NO_COOKIES":
        await m.answer("⚠️ У меня нет куки. Скинь текстовый файл с ними.")
    elif ads is None:
        await m.answer("⚠️ Ошибка доступа. OLX заблокировал запрос. <b>Скинь свежий файл с куками!</b>")
    elif not ads:
        await m.answer("ℹ️ Объявлений по запросу не найдено.")
    else:
        for a in ads[:3]:
            await m.answer(f"📦 <b>{a['title']}</b>\n💰 <b>{a['price']}</b>\n🔗 {a['url']}", disable_web_page_preview=True)

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
