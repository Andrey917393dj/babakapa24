import os
import sys
import json
import asyncio
import logging
import re
import random
from datetime import datetime
from typing import List, Dict, Union

from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

# --- КОНФИГУРАЦИЯ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Токен берем из переменной окружения, как просил в начале
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("❌ BOT_TOKEN не найден в переменных окружения!")
    sys.exit(1)

ACCESS_CODE = "130290"
TARGET_URL = "https://www.olx.ua/uk/elektronika/kompyutery-i-komplektuyuschie/komplektuyuschie-i-aksesuary/q-gtx-1080-ti-11gb/?search%5Border%5D=created_at%3Adesc"
DATA_FILE = "data.json"
COOKIES_FILE = "cookies.txt"

# --- ФУНКЦИЯ ЧТЕНИЯ КУК ИЗ ФАЙЛА ---
def get_cookies_from_file() -> Dict[str, str]:
    cookies = {}
    if os.path.exists(COOKIES_FILE):
        try:
            with open(COOKIES_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                for c in content.split(';'):
                    if '=' in c:
                        name, val = c.strip().split('=', 1)
                        cookies[name] = val
        except Exception as e:
            logger.error(f"Ошибка чтения cookies.txt: {e}")
    return cookies

# --- БД И КЕШ ---
class BotData:
    def __init__(self, filepath):
        self.filepath = filepath
        self.users = {}
        self.seen_ads = {}
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.users = data.get("users", {})
                    self.seen_ads = data.get("seen_ads", {})
            except: pass

    def save(self):
        with open(self.filepath, 'w', encoding='utf-8') as f:
            json.dump({"users": self.users, "seen_ads": self.seen_ads}, f, ensure_ascii=False, indent=2)

    def is_authorized(self, uid): return str(uid) in self.users
    def add_user(self, uid):
        if str(uid) not in self.users:
            self.users[str(uid)] = {"auto": False, "limit": 2}
            self.seen_ads[str(uid)] = []
            self.save()

    def add_seen(self, uid, aid):
        uid = str(uid)
        if aid not in self.seen_ads.get(uid, []):
            if uid not in self.seen_ads: self.seen_ads[uid] = []
            self.seen_ads[uid].append(aid)
            if len(self.seen_ads[uid]) > 200: self.seen_ads[uid].pop(0)
            self.save()

db = BotData(DATA_FILE)
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot, storage=MemoryStorage())

# --- ПАРСЕР ---
async def fetch_olx():
    cookies = get_cookies_from_file()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.olx.ua/",
        "Upgrade-Insecure-Requests": "1"
    }

    try:
        # impersonate="chrome120" крайне важен для обхода TLS защиты
        async with AsyncSession(impersonate="chrome120", headers=headers, cookies=cookies) as s:
            await asyncio.sleep(random.uniform(1, 2)) # Имитируем задержку человека
            r = await s.get(TARGET_URL, timeout=20)
            
            if r.status_code != 200:
                logger.warning(f"OLX вернул код {r.status_code}. Проверьте куки!")
                return None
            
            soup = BeautifulSoup(r.text, 'lxml')
            ads = []
            
            # Поиск по твоей новой верстке (data-cy="ad-card-title")
            title_boxes = soup.find_all('div', attrs={"data-cy": "ad-card-title"})
            
            for box in title_boxes:
                try:
                    # Поднимаемся к родителю, чтобы найти цену, если она рядом
                    parent = box.find_parent('div', attrs={"type": "list"}) or box.parent
                    
                    link_tag = box.find('a', href=True)
                    title_tag = box.find('h4')
                    price_tag = parent.find('p', attrs={"data-testid": "ad-price"}) if parent else None
                    
                    if link_tag and title_tag:
                        href = link_tag['href']
                        if not href.startswith('http'): href = "https://www.olx.ua" + href
                        
                        match = re.search(r'-ID(\w+)\.html', href)
                        ad_id = match.group(1) if match else href
                        
                        ads.append({
                            "id": ad_id,
                            "title": title_tag.get_text(strip=True),
                            "price": price_tag.get_text(strip=True) if price_tag else "Цена не указана",
                            "url": href
                        })
                except: continue
            
            return ads
    except Exception as e:
        logger.error(f"Критическая ошибка парсера: {e}")
        return None

# --- ХЕНДЛЕРЫ ---
@dp.message_handler(commands=['start'])
async def start(m: types.Message):
    if db.is_authorized(m.from_user.id):
        await m.answer("✅ Доступ открыт", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("📥 Получить данные", "⚙️ Настройки"))
    else:
        await m.answer("🔒 Доступ заблокирован. Введите код доступа:")

@dp.message_handler(lambda m: not db.is_authorized(m.from_user.id))
async def auth(m: types.Message):
    if m.text.strip() == ACCESS_CODE:
        db.add_user(m.from_user.id)
        await m.answer("🔓 Добро пожаловать!", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("📥 Получить данные", "⚙️ Настройки"))
    else:
        await m.answer("❌ Неверный код")

@dp.message_handler(lambda m: m.text == "📥 Получить данные")
async def get_manual(m: types.Message):
    await m.answer("🔎 Ищу новые объявления...")
    ads = await fetch_olx()
    if ads is None:
        await m.answer("⚠️ OLX не ответил. Обновите куки в файле cookies.txt!")
        return
    if not ads:
        await m.answer("ℹ️ Сейчас новых объявлений нет.")
        return
    
    limit = db.users[str(m.from_user.id)]['limit']
    for a in ads[:limit]:
        msg = f"📦 <b>{a['title']}</b>\n💰 <b>{a['price']}</b>\n🔗 <a href='{a['url']}'>Открыть на OLX</a>"
        await m.answer(msg, disable_web_page_preview=False)
        db.add_seen(m.from_user.id, a['id'])

@dp.message_handler(lambda m: m.text == "⚙️ Настройки")
async def settings(m: types.Message):
    u = db.users[str(m.from_user.id)]
    await m.answer(f"⚙️ <b>Настройки</b>\nАвто-мониторинг: {'ВКЛ' if u['auto'] else 'ВЫКЛ'}\nЛимит за раз: {u['limit']}\n\n"
                   f"Команды:\n<code>auto on</code> / <code>auto off</code>\n<code>limit 5</code>")

@dp.message_handler(lambda m: m.text.lower().startswith(('auto', 'limit')))
async def set_cfg(m: types.Message):
    uid = str(m.from_user.id)
    if "auto on" in m.text.lower(): db.users[uid]['auto'] = True
    elif "auto off" in m.text.lower(): db.users[uid]['auto'] = False
    elif "limit" in m.text.lower():
        try: db.users[uid]['limit'] = int(m.text.split()[1])
        except: pass
    db.save()
    await m.answer("✅ Сохранено")

# --- ФОНОВЫЙ МОНИТОРИНГ ---
async def monitor_loop():
    while True:
        try:
            active_users = [u for u, s in db.users.items() if s['auto']]
            if active_users:
                ads = await fetch_olx()
                if ads:
                    for uid in active_users:
                        # Берем самые свежие 5
                        for a in ads[:5]:
                            if a['id'] not in db.seen_ads.get(uid, []):
                                await bot.send_message(uid, f"🚨 <b>НОВОЕ ОБЪЯВЛЕНИЕ!</b>\n\n{a['title']}\n💰 {a['price']}\n🔗 {a['url']}")
                                db.add_seen(uid, a['id'])
                                await asyncio.sleep(1)
            # Ждем от 60 до 120 секунд, чтобы не частить
            await asyncio.sleep(random.randint(60, 120))
        except Exception as e:
            logger.error(f"Ошибка в мониторинге: {e}")
            await asyncio.sleep(60)

async def on_startup(_):
    asyncio.create_task(monitor_loop())

if __name__ == '__main__':
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
