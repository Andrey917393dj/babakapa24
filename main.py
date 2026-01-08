import os
import sys
import json
import asyncio
import logging
import re
from datetime import datetime
from typing import List, Dict, Union

from aiogram import Bot, Dispatcher, types, executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from bs4 import BeautifulSoup

# Импортируем эмулятор браузера для запросов
from curl_cffi.requests import AsyncSession

# --- КОНФИГУРАЦИЯ ---

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("❌ Ошибка: Переменная окружения BOT_TOKEN не установлена!")
    sys.exit(1)

ACCESS_CODE = "130290"
# Используем URL мобильной версии, но OLX может редиректить на www.
# Сортировка по новизне включена.
TARGET_URL = "https://m.olx.ua/uk/elektronika/kompyutery-i-komplektuyuschie/komplektuyuschie-i-aksesuary/q-gtx-1080-ti-11gb/?search%5Border%5D=created_at%3Adesc"

DATA_FILE = "data.json"

# --- КЛАССЫ И СОСТОЯНИЯ ---

class AuthState(StatesGroup):
    waiting_for_code = State()

class BotData:
    """Класс для управления сохранением состояния в JSON"""
    def __init__(self, filepath):
        self.filepath = filepath
        self.users: Dict[str, Dict] = {} 
        self.seen_ads: Dict[str, List[str]] = {} 
        self.load()

    def load(self):
        if not os.path.exists(self.filepath):
            self.save()
            return
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.users = data.get("users", {})
                self.seen_ads = data.get("seen_ads", {})
        except Exception as e:
            logger.error(f"Ошибка загрузки данных: {e}")

    def save(self):
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump({
                    "users": self.users,
                    "seen_ads": self.seen_ads
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения данных: {e}")

    def is_authorized(self, user_id: str) -> bool:
        return str(user_id) in self.users

    def add_user(self, user_id: str):
        if str(user_id) not in self.users:
            self.users[str(user_id)] = {
                "auto_check": False,
                "interval": 60,
                "limit": 2
            }
            self.seen_ads[str(user_id)] = []
            self.save()

    def update_setting(self, user_id: str, key: str, value):
        if str(user_id) in self.users:
            self.users[str(user_id)][key] = value
            self.save()

    def get_settings(self, user_id: str):
        return self.users.get(str(user_id), {})

    def add_seen_ad(self, user_id: str, ad_id: str):
        uid = str(user_id)
        if uid not in self.seen_ads:
            self.seen_ads[uid] = []
        if ad_id not in self.seen_ads[uid]:
            self.seen_ads[uid].append(ad_id)
            if len(self.seen_ads[uid]) > 200:
                self.seen_ads[uid] = self.seen_ads[uid][-200:]
            self.save()

    def is_seen(self, user_id: str, ad_id: str) -> bool:
        return ad_id in self.seen_ads.get(str(user_id), [])

db = BotData(DATA_FILE)
bot = Bot(token=BOT_TOKEN, parse_mode=types.ParseMode.HTML)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# --- ПАРСЕР (ОБНОВЛЕННЫЙ) ---

async def fetch_olx_ads(limit: int = 5) -> Union[List[dict], None]:
    """
    Парсит OLX используя curl_cffi для обхода TLS-фингерпринтинга.
    """
    # Заголовки как у реального браузера Chrome
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "max-age=0",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1"
    }

    try:
        # impersonate="chrome120" заставляет сервер думать, что это реальный хром
        async with AsyncSession(impersonate="chrome120", headers=headers) as session:
            response = await session.get(TARGET_URL, timeout=15)
            
            if response.status_code != 200:
                logger.warning(f"OLX Status: {response.status_code}")
                # Если 403 - значит всё еще блочит, но curl_cffi должен помочь
                return None

            html = response.text
            soup = BeautifulSoup(html, 'lxml')
            ads = []

            # Поиск карточек. Логика расширена для мобильной и десктопной верстки
            # 1. Пробуем найти div с data-cy="l-card" (стандарт листинга)
            cards = soup.find_all('div', attrs={"data-cy": "l-card"})

            # 2. Fallback: ищем просто ссылки на объявления, если верстка поменялась
            if not cards:
                # Ищем блоки, содержащие ссылки на /obyavlenie/
                # Обычно карточка обернута в div
                candidates = soup.find_all('a', href=re.compile(r'/obyavlenie/|/d/'))
                unique_cards = []
                seen_urls = set()
                
                for a in candidates:
                    parent = a.find_parent('div')
                    url = a.get('href')
                    if parent and url and url not in seen_urls:
                        unique_cards.append(parent)
                        seen_urls.add(url)
                cards = unique_cards

            for card in cards:
                if len(ads) >= limit:
                    break
                try:
                    # Поиск ссылки
                    link_tag = card.find('a', href=True)
                    if not link_tag:
                        # Иногда ссылка прямо на карточке или карточка сама ссылка
                        if card.name == 'a':
                            link_tag = card
                        else:
                            continue

                    href = link_tag['href']
                    if not href.startswith('http'):
                        href = f"https://www.olx.ua{href}"
                    
                    # ID объявления
                    match = re.search(r'-ID(\w+)\.html', href)
                    ad_id = match.group(1) if match else href

                    # Заголовок
                    title_tag = card.find('h6')
                    if title_tag:
                        title = title_tag.get_text(strip=True)
                    else:
                        # Ищем любой текст внутри ссылки
                        title = link_tag.get_text(strip=True)
                        # Если текст слишком длинный или мусорный, обрезаем
                        if len(title) > 100: title = title[:100] + "..."

                    # Цена
                    price_tag = card.find('p', attrs={"data-testid": "ad-price"})
                    if not price_tag:
                         # Попытка найти цену по тексту грн
                         price_tag = card.find(string=re.compile(r'грн'))
                         price = price_tag.parent.get_text(strip=True) if price_tag else "Цена не указана"
                    else:
                        price = price_tag.get_text(strip=True)

                    ads.append({
                        "id": ad_id,
                        "title": title,
                        "price": price,
                        "url": href,
                        "time": datetime.now().strftime("%H:%M:%S")
                    })

                except Exception as e:
                    continue
            
            return ads

    except Exception as e:
        logger.error(f"Ошибка запроса OLX: {e}")
        return None

# --- ХЕНДЛЕРЫ ---

def get_main_keyboard():
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(types.KeyboardButton("📥 Получить данные"))
    keyboard.add(types.KeyboardButton("⚙️ Настройки"))
    return keyboard

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = str(message.from_user.id)
    if db.is_authorized(user_id):
        await message.answer("✅ Доступ уже открыт.", reply_markup=get_main_keyboard())
    else:
        await message.answer("🔒 <b>Доступ заблокирован</b>\nВведите код доступа:", parse_mode="HTML")
        await AuthState.waiting_for_code.set()

@dp.message_handler(state=AuthState.waiting_for_code)
async def process_access_code(message: types.Message, state: FSMContext):
    if message.text.strip() == ACCESS_CODE:
        db.add_user(str(message.from_user.id))
        await state.finish()
        await message.answer("🔓 <b>Доступ открыт!</b>", parse_mode="HTML", reply_markup=get_main_keyboard())
    else:
        await message.answer("❌ Неверный код.")

@dp.message_handler(lambda message: message.text == "📥 Получить данные")
async def manual_check(message: types.Message):
    user_id = str(message.from_user.id)
    if not db.is_authorized(user_id): return

    settings = db.get_settings(user_id)
    await message.answer("🔎 <i>Запрос к OLX (эмуляция Chrome)...</i>", parse_mode="HTML")
    
    ads = await fetch_olx_ads(limit=settings.get("limit", 2))

    if ads is None:
        await message.answer("⚠️ OLX не ответил. Возможно требуется смена IP (используйте VPN на сервере).")
        return

    if not ads:
        await message.answer("ℹ️ Новых объявлений не найдено (или изменилась верстка сайта).")
        return

    for ad in ads:
        text = f"<b>{ad['title']}</b>\n💰 {ad['price']}\n🔗 {ad['url']}"
        await message.answer(text, disable_web_page_preview=True)
        db.add_seen_ad(user_id, ad['id'])

@dp.message_handler(lambda message: message.text == "⚙️ Настройки")
async def show_settings(message: types.Message):
    user_id = str(message.from_user.id)
    if not db.is_authorized(user_id): return
    s = db.get_settings(user_id)
    status = "✅ ВКЛ" if s['auto_check'] else "❌ ВЫКЛ"
    text = (
        f"⚙️ <b>Настройки:</b>\nАвточекер: {status}\nИнтервал: {s['interval']}с\n"
        "Команды: <code>auto on</code>, <code>auto off</code>, <code>interval 60</code>"
    )
    await message.answer(text, parse_mode="HTML")

@dp.message_handler(lambda message: message.text.lower().startswith(("auto", "interval", "limit")))
async def update_settings_handler(message: types.Message):
    user_id = str(message.from_user.id)
    if not db.is_authorized(user_id): return
    text = message.text.lower().strip()
    try:
        if text == "auto on":
            db.update_setting(user_id, "auto_check", True)
            await message.answer("✅ Авточекер включен.")
        elif text == "auto off":
            db.update_setting(user_id, "auto_check", False)
            await message.answer("❌ Авточекер выключен.")
        elif text.startswith("interval"):
            val = int(text.split()[1])
            if val >= 10:
                db.update_setting(user_id, "interval", val)
                await message.answer(f"⏱ Интервал: {val} сек.")
            else:
                await message.answer("⚠️ Минимум 10 сек.")
    except:
        await message.answer("⚠️ Ошибка команды.")

# --- ФОНОВЫЙ МОНИТОРИНГ ---

async def background_monitor():
    logger.info("🚀 Monitor started")
    while True:
        try:
            active_users = [uid for uid, s in db.users.items() if s.get('auto_check')]
            if active_users:
                # Получаем данные один раз для всех
                ads = await fetch_olx_ads(limit=10)
                if ads:
                    for user_id in active_users:
                        user_limit = db.get_settings(user_id).get('limit', 2)
                        for ad in ads[:user_limit]: # Учитываем лимит пользователя
                            if not db.is_seen(user_id, ad['id']):
                                try:
                                    text = f"🚨 <b>NEW:</b> {ad['title']}\n💰 {ad['price']}\n🔗 {ad['url']}"
                                    await bot.send_message(user_id, text, disable_web_page_preview=True)
                                    db.add_seen_ad(user_id, ad['id'])
                                    await asyncio.sleep(1)
                                except Exception as e:
                                    logger.error(f"Send error: {e}")
            
            # Динамическая пауза. Если OLX блочит, лучше ставить интервал больше.
            await asyncio.sleep(60) 
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            await asyncio.sleep(60)

async def on_startup(_):
    asyncio.create_task(background_monitor())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
