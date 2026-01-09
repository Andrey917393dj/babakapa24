import os
import sys
import json
import asyncio
import logging
import re
import random
from datetime import datetime
from typing import List, Dict, Union, Optional

from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

# --- КОНФИГУРАЦИЯ ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("❌ BOT_TOKEN не найден!")
    sys.exit(1)

ACCESS_CODE = "130290"
# Оригинальный URL
ORIGIN_URL = "https://www.olx.ua/uk/elektronika/kompyutery-i-komplektuyuschie/komplektuyuschie-i-aksesuary/q-gtx-1080-ti-11gb/?search%5Border%5D=created_at%3Adesc"
DATA_FILE = "data.json"

# --- БД ---
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

db = BotData(DATA_FILE)
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot, storage=MemoryStorage())

# --- ПАРСЕР С ОБХОДОМ БЕЗ КУКИ ---

async def fetch_olx_via_mirror() -> Optional[List[dict]]:
    """
    Пытается получить данные через разные публичные шлюзы и 
    прямую эмуляцию с подменой TLS.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8",
        "Referer": "https://www.google.com/",
    }

    # Попытка 1: Прямой запрос с имитацией самого нового Chrome
    # curl_cffi с impersonate="chrome120" часто пробивает защиту даже без кук, 
    # если IP еще не совсем "сгорел".
    try:
        async with AsyncSession(impersonate="chrome120", headers=headers) as s:
            r = await s.get(ORIGIN_URL, timeout=15)
            if r.status_code == 200 and "data-cy=\"ad-card-title\"" in r.text:
                return parse_html(r.text)
    except Exception as e:
        logger.error(f"Прямой запрос не удался: {e}")

    # Попытка 2: Использование CORS-прокси (может помочь на некоторых хостингах)
    proxies = [
        f"https://api.allorigins.win/get?url={ORIGIN_URL}",
        f"https://corsproxy.io/?{ORIGIN_URL}"
    ]
    
    for p_url in proxies:
        try:
            async with AsyncSession(headers=headers) as s:
                r = await s.get(p_url, timeout=15)
                if r.status_code == 200:
                    content = r.text
                    # Если это allorigins, там JSON с полем contents
                    if "allorigins" in p_url:
                        content = json.loads(content).get("contents", "")
                    
                    if "ad-card-title" in content:
                        return parse_html(content)
        except:
            continue

    return None

def parse_html(html: str) -> List[dict]:
    soup = BeautifulSoup(html, 'lxml')
    ads = []
    # Поиск по твоей структуре
    title_boxes = soup.find_all('div', attrs={"data-cy": "ad-card-title"})
    
    for box in title_boxes:
        try:
            parent = box.find_parent('div', attrs={"type": "list"}) or box.parent
            link_tag = box.find('a', href=True)
            title_tag = box.find('h4')
            price_tag = parent.find('p', attrs={"data-testid": "ad-price"})
            
            if link_tag and title_tag:
                href = link_tag['href']
                if not href.startswith('http'): href = "https://www.olx.ua" + href
                match = re.search(r'-ID(\w+)\.html', href)
                ad_id = match.group(1) if match else href
                
                ads.append({
                    "id": ad_id,
                    "title": title_tag.get_text(strip=True),
                    "price": price_tag.get_text(strip=True) if price_tag else "---",
                    "url": href
                })
        except: continue
    return ads

# --- ХЕНДЛЕРЫ (Классика) ---

@dp.message_handler(commands=['start'])
async def start(m: types.Message):
    if db.is_authorized(m.from_user.id):
        await m.answer("✅ Работаем. Используем ротацию шлюзов.", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("📥 Получить данные", "⚙️ Настройки"))
    else:
        await m.answer("Введите код доступа:")

@dp.message_handler(lambda m: not db.is_authorized(m.from_user.id))
async def auth(m: types.Message):
    if m.text == ACCESS_CODE:
        db.add_user(m.from_user.id)
        await m.answer("🔓 Доступ открыт!", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("📥 Получить данные", "⚙️ Настройки"))

@dp.message_handler(lambda m: m.text == "📥 Получить данные")
async def manual(m: types.Message):
    await m.answer("🔄 Пробую пробиться на OLX без куки...")
    ads = await fetch_olx_via_mirror()
    if not ads:
        await m.answer("⚠️ Все шлюзы заблокированы. OLX усилил защиту. Без VPN или прокси сейчас не зайти.")
        return

    uid = str(m.from_user.id)
    limit = db.users[uid]['limit']
    for a in ads[:limit]:
        await m.answer(f"📦 <b>{a['title']}</b>\n💰 {a['price']}\n🔗 {a['url']}")
        if a['id'] not in db.seen_ads.get(uid, []):
            db.seen_ads[uid].append(a['id'])
    db.save()

@dp.message_handler(lambda m: m.text == "⚙️ Настройки")
async def sets(m: types.Message):
    u = db.users[str(m.from_user.id)]
    await m.answer(f"⚙️ Авто: {'ВКЛ' if u['auto'] else 'ВЫКЛ'}\nЛимит: {u['limit']}\n\nКоманды: auto on/off, limit N")

@dp.message_handler(lambda m: m.text.lower().startswith(('auto', 'limit')))
async def cfg(m: types.Message):
    uid = str(m.from_user.id)
    if "auto on" in m.text.lower(): db.users[uid]['auto'] = True
    elif "auto off" in m.text.lower(): db.users[uid]['auto'] = False
    elif "limit" in m.text.lower():
        try: db.users[uid]['limit'] = int(m.text.split()[1])
        except: pass
    db.save()
    await m.answer("✅ Принято")

async def monitor():
    while True:
        try:
            active = [u for u, s in db.users.items() if s['auto']]
            if active:
                ads = await fetch_olx_via_mirror()
                if ads:
                    for uid in active:
                        for a in ads[:5]:
                            if a['id'] not in db.seen_ads.get(uid, []):
                                await bot.send_message(uid, f"🚨 <b>НОВОЕ:</b>\n{a['title']}\n💰 {a['price']}\n🔗 {a['url']}")
                                if uid not in db.seen_ads: db.seen_ads[uid] = []
                                db.seen_ads[uid].append(a['id'])
                db.save()
            await asyncio.sleep(random.randint(120, 300)) # Реже чекаем, чтобы не банили
        except:
            await asyncio.sleep(60)

async def on_startup(_):
    asyncio.create_task(monitor())

if __name__ == '__main__':
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
