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

# Глобальная переменная для хранения куки в памяти бота
current_cookies = ""

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot, storage=MemoryStorage())

# --- ЛОГИКА ПАРСИНГА ---

def parse_cookies(cookie_str):
    res = {}
    for item in cookie_str.split(';'):
        if '=' in item:
            k, v = item.strip().split('=', 1)
            res[k] = v
    return res

async def fetch_olx():
    global current_cookies
    cookies_dict = parse_cookies(current_cookies)
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8",
        "Referer": "https://www.google.com/",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin"
    }

    try:
        # Используем мощный curl_cffi для обхода TLS-защиты
        async with AsyncSession(impersonate="chrome121", headers=headers, cookies=cookies_dict) as s:
            r = await s.get(TARGET_URL, timeout=15)
            if r.status_code != 200:
                return None
            
            soup = BeautifulSoup(r.text, 'lxml')
            ads = []
            # Поиск по твоей структуре (data-cy="ad-card-title")
            items = soup.find_all('div', attrs={"data-cy": "ad-card-title"})
            for item in items:
                try:
                    link = item.find('a', href=True)
                    title = item.find('h4').text
                    price = item.find_parent().find('p', attrs={"data-testid": "ad-price"}).text
                    full_link = "https://www.olx.ua" + link['href'] if not link['href'].startswith('http') else link['href']
                    ads.append({"title": title, "price": price, "url": full_link})
                except: continue
            return ads
    except Exception as e:
        logging.error(f"Ошибка: {e}")
        return None

# --- ХЕНДЛЕРЫ ---

@dp.message_handler(commands=['start'])
async def cmd_start(m: types.Message):
    await m.answer("👋 Привет! Если бот напишет 'Обнови куки', просто скопируй их из браузера и пришли мне сообщением.")

# Хендлер для обновления КУКИ (если сообщение длинное и содержит ключевые слова)
@dp.message_handler(lambda m: "cf_bm" in m.text or "PHPSESSID" in m.text)
async def update_cookies(m: types.Message):
    global current_cookies
    current_cookies = m.text.strip()
    await m.answer("✅ <b>Куки успешно обновлены!</b> Пробую сделать запрос...", parse_mode="HTML")
    
    # Сразу проверяем, заработало ли
    ads = await fetch_olx()
    if ads:
        await m.answer(f"🎉 Успех! Найдено {len(ads)} объявлений. Теперь можешь жать 'Получить данные'.")
    else:
        await m.answer("❌ Даже с этими куками OLX не пускает. Попробуй обновить страницу в браузере и скопировать куки заново.")

@dp.message_handler(lambda m: m.text == "📥 Получить данные")
async def get_data(m: types.Message):
    if not current_cookies:
        await m.answer("⚠️ Сначала пришли мне куки из браузера!")
        return

    await m.answer("🔎 Запрос к OLX...")
    ads = await fetch_olx()
    
    if ads is None:
        await m.answer("⚠️ OLX заблокировал запрос. <b>Обнови куки!</b>\n(Зайди на сайт, нажми F5, скопируй Cookie из F12 и кинь сюда).")
    elif not ads:
        await m.answer("ℹ️ Объявлений не найдено. Попробуй позже.")
    else:
        for a in ads[:3]:
            await m.answer(f"📦 <b>{a['title']}</b>\n💰 {a['price']}\n🔗 {a['url']}")

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
