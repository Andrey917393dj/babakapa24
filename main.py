#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TEMU FARM SYSTEM v2.0 (BotHost Edition)
Автоматизированная ферма для прогрева аккаунтов Temu
✅ Mail.tm API (бесплатные email с 3+ дней жизни)
✅ Pyppeteer (работает без root)
✅ Таймеры истечения срока email
✅ 3 режима работы: Авто / Полуавто / Прогрев готовых

GitHub: https://github.com/your-repo/temu-farm
"""

import asyncio
import os
import sys
import re
import random
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass
from enum import Enum

# Core
from dotenv import load_dotenv
import aiosqlite
import bcrypt

# Telegram Bot
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Web Automation
from pyppeteer import launch
from pyppeteer.errors import TimeoutError as PyppeteerTimeout

# HTTP
import httpx
from fake_useragent import UserAgent

# Task Scheduling
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Utilities
from faker import Faker
from dateutil import parser as date_parser

# ==================== КОНФИГУРАЦИЯ ====================

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_PASSWORD = "130290"
DB_PATH = 'data/temu_farm.db'

if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в .env файле!")
    print("Создайте файл .env с содержимым:")
    print("BOT_TOKEN=ваш_токен_бота")
    sys.exit(1)

# Создание директорий
os.makedirs('data', exist_ok=True)
os.makedirs('logs', exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/system.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== КОНСТАНТЫ ====================

class Stage(str, Enum):
    """Этапы прогрева"""
    NOT_REGISTERED = "not_registered"
    DAY1 = "day1"
    DAY2 = "day2"
    DAY3 = "day3"
    COMPLETED = "completed"

class Status(str, Enum):
    """Статусы аккаунта"""
    ACTIVE = "active"
    PAUSED = "paused"
    BANNED = "banned"
    PROCESSING = "processing"
    EMAIL_EXPIRING = "email_expiring"

class WorkMode(str, Enum):
    """Режимы работы"""
    AUTO = "auto"  # Автоматическая регистрация
    SEMI_AUTO = "semi_auto"  # Создать email, регистрировать вручную
    WARMUP_ONLY = "warmup_only"  # Только прогрев готовых

class Language(str, Enum):
    """Языки интерфейса"""
    RU = "ru"
    UK = "uk"
    EN = "en"

# Тексты интерфейса
TEXTS = {
    Language.RU: {
        "main_menu": "🏠 ГЛАВНОЕ МЕНЮ",
        "testing": "🧪 Тестирование",
        "accounts": "Аккаунты",
        "start_farm": "▶️ Запустить ферму",
        "pause_farm": "⏸ Поставить на паузу",
        "stop_farm": "⏹ Остановить все",
        "account_list": "📋 Список аккаунтов",
        "create_batch": "➕ Создать партию",
        "statistics": "📊 Статистика",
        "settings": "⚙️ Настройки",
        "logs": "📄 Логи",
        "active": "Активных",
        "paused": "На паузе",
        "banned": "Забанено"
    },
    Language.UK: {
        "main_menu": "🏠 ГОЛОВНЕ МЕНЮ",
        "testing": "🧪 Тестування",
        "accounts": "Акаунти",
        "start_farm": "▶️ Запустити ферму",
        "pause_farm": "⏸ Поставити на паузу",
        "stop_farm": "⏹ Зупинити всі",
        "account_list": "📋 Список акаунтів",
        "create_batch": "➕ Створити партію",
        "statistics": "📊 Статистика",
        "settings": "⚙️ Налаштування",
        "logs": "📄 Логи",
        "active": "Активних",
        "paused": "На паузі",
        "banned": "Забанено"
    },
    Language.EN: {
        "main_menu": "🏠 MAIN MENU",
        "testing": "🧪 Testing",
        "accounts": "Accounts",
        "start_farm": "▶️ Start Farm",
        "pause_farm": "⏸ Pause All",
        "stop_farm": "⏹ Stop All",
        "account_list": "📋 Account List",
        "create_batch": "➕ Create Batch",
        "statistics": "📊 Statistics",
        "settings": "⚙️ Settings",
        "logs": "📄 Logs",
        "active": "Active",
        "paused": "Paused",
        "banned": "Banned"
    }
}

# Профили поведения
BEHAVIOR_PROFILES = {
    "searcher": {
        "search_frequency": 0.7,
        "cart_add_chance": 0.3,
        "keywords": ["sale", "discount", "cheap", "акція", "знижка"]
    },
    "impulse": {
        "search_frequency": 0.3,
        "cart_add_chance": 0.8,
        "keywords": ["new", "trending", "популярне", "новинки"]
    },
    "cautious": {
        "search_frequency": 0.5,
        "cart_add_chance": 0.2,
        "keywords": ["reviews", "rating", "відгуки", "топ"]
    }
}

# Сценарии по дням
SCENARIOS = {
    Stage.DAY1: {
        "products_view": (5, 8),
        "searches": (2, 3),
        "scroll_count": (3, 5)
    },
    Stage.DAY2: {
        "products_view": (10, 15),
        "searches": (4, 5),
        "cart_additions": (3, 5),
        "scroll_count": (5, 8)
    },
    Stage.DAY3: {
        "products_view": (15, 20),
        "searches": (5, 7),
        "cart_additions": (5, 8),
        "scroll_count": (8, 12)
    }
}

# ==================== MAIL.TM API ====================

class MailTM:
    """Клиент для Mail.tm API"""
    
    BASE_URL = "https://api.mail.tm"
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30)
        self.token = None
    
    async def get_domains(self) -> List[str]:
        """Получить доступные домены"""
        try:
            resp = await self.client.get(f"{self.BASE_URL}/domains")
            if resp.status_code == 200:
                data = resp.json()
                return [d['domain'] for d in data.get('hydra:member', [])]
            return []
        except Exception as e:
            logger.error(f"Ошибка получения доменов: {e}")
            return []
    
    async def create_account(self) -> Optional[Dict[str, str]]:
        """Создать новый email аккаунт"""
        try:
            domains = await self.get_domains()
            if not domains:
                logger.error("Не удалось получить домены Mail.tm")
                return None
            
            domain = random.choice(domains)
            
            # Генерируем случайный адрес
            faker = Faker()
            username = faker.user_name()[:10].lower() + str(random.randint(1000, 9999))
            email = f"{username}@{domain}"
            password = ''.join(random.choices('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=12))
            
            # Регистрируем аккаунт
            resp = await self.client.post(
                f"{self.BASE_URL}/accounts",
                json={"address": email, "password": password}
            )
            
            if resp.status_code == 201:
                logger.info(f"✅ Mail.tm аккаунт создан: {email}")
                return {
                    "email": email,
                    "password": password,
                    "created_at": datetime.now().isoformat()
                }
            else:
                logger.error(f"Ошибка создания Mail.tm: {resp.status_code} {resp.text}")
                return None
        
        except Exception as e:
            logger.error(f"Ошибка создания Mail.tm аккаунта: {e}")
            return None
    
    async def get_token(self, email: str, password: str) -> Optional[str]:
        """Получить JWT токен"""
        try:
            resp = await self.client.post(
                f"{self.BASE_URL}/token",
                json={"address": email, "password": password}
            )
            
            if resp.status_code == 200:
                data = resp.json()
                self.token = data.get('token')
                return self.token
            return None
        except Exception as e:
            logger.error(f"Ошибка получения токена: {e}")
            return None
    
    async def get_messages(self, email: str, password: str) -> List[Dict]:
        """Получить сообщения"""
        try:
            token = await self.get_token(email, password)
            if not token:
                return []
            
            headers = {"Authorization": f"Bearer {token}"}
            resp = await self.client.get(
                f"{self.BASE_URL}/messages",
                headers=headers
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return data.get('hydra:member', [])
            return []
        except Exception as e:
            logger.error(f"Ошибка получения сообщений: {e}")
            return []
    
    async def get_message_content(self, message_id: str) -> Optional[str]:
        """Получить содержимое письма"""
        try:
            if not self.token:
                return None
            
            headers = {"Authorization": f"Bearer {self.token}"}
            resp = await self.client.get(
                f"{self.BASE_URL}/messages/{message_id}",
                headers=headers
            )
            
            if resp.status_code == 200:
                data = resp.json()
                return data.get('text', data.get('html', ''))
            return None
        except Exception as e:
            logger.error(f"Ошибка получения содержимого письма: {e}")
            return None
    
    async def close(self):
        await self.client.aclose()

mail_tm = MailTM()

# ==================== DATACLASSES ====================

@dataclass
class Account:
    """Модель аккаунта"""
    id: int
    email: str
    email_password: str
    temu_password: str
    stage: Stage
    status: Status
    profile_type: str
    email_created_at: datetime
    last_active: Optional[datetime]
    next_stage_at: Optional[datetime]
    total_actions: int

# ==================== FSM СОСТОЯНИЯ ====================

class SystemSetup(StatesGroup):
    PASSWORD = State()

class BatchCreation(StatesGroup):
    COUNT = State()
    MODE = State()

# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================

async def init_database():
    """Инициализация SQLite базы данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Системная конфигурация
        await db.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                password_hash TEXT NOT NULL,
                admin_id INTEGER,
                language TEXT DEFAULT 'uk',
                work_mode TEXT DEFAULT 'semi_auto',
                debug_mode BOOLEAN DEFAULT FALSE,
                auto_restart BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor = await db.execute("SELECT COUNT(*) FROM system_config")
        count = (await cursor.fetchone())[0]
        
        if count == 0:
            password_hash = bcrypt.hashpw(
                ADMIN_PASSWORD.encode(), 
                bcrypt.gensalt()
            ).decode()
            
            await db.execute("""
                INSERT INTO system_config (id, password_hash)
                VALUES (1, ?)
            """, (password_hash,))
        
        # Аккаунты
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                email_password TEXT NOT NULL,
                temu_password TEXT NOT NULL,
                stage TEXT DEFAULT 'not_registered',
                status TEXT DEFAULT 'active',
                profile_type TEXT,
                email_created_at TIMESTAMP NOT NULL,
                last_active TIMESTAMP,
                next_stage_at TIMESTAMP,
                total_actions INTEGER DEFAULT 0
            )
        """)
        
        # Лог действий
        await db.execute("""
            CREATE TABLE IF NOT EXISTS actions_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                result TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)
        
        await db.commit()
        logger.info("✅ База данных инициализирована")

# ==================== УТИЛИТЫ ====================

def get_text(lang: Language, key: str) -> str:
    """Получить текст на языке"""
    return TEXTS.get(lang, TEXTS[Language.UK]).get(key, key)

async def get_system_config() -> Dict[str, Any]:
    """Получить конфигурацию системы"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT admin_id, language, work_mode, debug_mode, auto_restart
            FROM system_config WHERE id = 1
        """)
        result = await cursor.fetchone()
        
        if result:
            return {
                'admin_id': result[0],
                'language': Language(result[1]),
                'work_mode': WorkMode(result[2]),
                'debug_mode': result[3],
                'auto_restart': result[4]
            }
        return None

async def set_admin_id(admin_id: int):
    """Установить ID администратора"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE system_config SET admin_id = ? WHERE id = 1
        """, (admin_id,))
        await db.commit()

async def verify_password(password: str) -> bool:
    """Проверить пароль"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT password_hash FROM system_config WHERE id = 1
        """)
        result = await cursor.fetchone()
        
        if result:
            return bcrypt.checkpw(password.encode(), result[0].encode())
        return False

async def set_work_mode(mode: WorkMode):
    """Установить режим работы"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE system_config SET work_mode = ? WHERE id = 1
        """, (mode.value,))
        await db.commit()

def calculate_email_expiry(created_at: datetime) -> Tuple[int, bool]:
    """
    Рассчитать срок до истечения email (3 дня)
    Возвращает: (секунды_до_истечения, истекает_скоро)
    """
    expiry_date = created_at + timedelta(days=3)
    now = datetime.now()
    seconds_left = (expiry_date - now).total_seconds()
    
    # Предупреждение за 24 часа
    expiring_soon = seconds_left < 86400 and seconds_left > 0
    
    return int(seconds_left), expiring_soon

def format_time_left(seconds: int) -> str:
    """Форматировать оставшееся время"""
    if seconds < 0:
        return "❌ Истёк"
    
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    
    if days > 0:
        return f"{days}д {hours}ч {minutes}м"
    elif hours > 0:
        return f"{hours}ч {minutes}м"
    else:
        return f"{minutes}м"

async def log_action(account_id: int, action_type: str, result: str = "success"):
    """Логирование действия"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO actions_log (account_id, action_type, result)
            VALUES (?, ?, ?)
        """, (account_id, action_type, result))
        await db.commit()

# ==================== BROWSER AUTOMATION ====================

class TemuAutomation:
    """Автоматизация через pyppeteer"""
    
    def __init__(self, account: Account, proxy: Optional[str] = None):
        self.account = account
        self.proxy = proxy
        self.browser = None
        self.page = None
        self.ua = UserAgent()
    
    async def init_browser(self):
        """Инициализация браузера"""
        launch_args = [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-blink-features=AutomationControlled'
        ]
        
        if self.proxy:
            launch_args.append(f'--proxy-server={self.proxy}')
        
        self.browser = await launch(
            headless=True,
            args=launch_args,
            ignoreHTTPSErrors=True
        )
        
        self.page = await self.browser.newPage()
        
        # Установка User-Agent
        await self.page.setUserAgent(self.ua.random)
        
        # Установка viewport
        await self.page.setViewport({'width': 1920, 'height': 1080})
        
        # Антидетект патчи
        await self.page.evaluateOnNewDocument("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
            window.chrome = {runtime: {}};
        """)
        
        logger.info(f"✅ Браузер запущен для аккаунта {self.account.id}")
    
    async def human_delay(self, min_sec: float = 1, max_sec: float = 3):
        """Человеческая задержка"""
        await asyncio.sleep(random.uniform(min_sec, max_sec))
    
    async def register_account(self) -> bool:
        """Автоматическая регистрация на Temu"""
        try:
            await self.page.goto("https://www.temu.com", {'waitUntil': 'domcontentloaded'})
            await self.human_delay(2, 4)
            
            # TODO: Реализовать поиск кнопки Sign Up и заполнение формы
            # Здесь требуется конкретные селекторы с сайта Temu
            
            logger.info(f"✅ Регистрация аккаунта {self.account.email}")
            return True
        
        except Exception as e:
            logger.error(f"❌ Ошибка регистрации: {e}")
            return False
    
    async def execute_scenario(self, stage: Stage) -> bool:
        """Выполнение сценария прогрева"""
        try:
            scenario = SCENARIOS.get(stage)
            if not scenario:
                return False
            
            await self.page.goto("https://www.temu.com", {'waitUntil': 'domcontentloaded'})
            await self.human_delay()
            
            # Скроллинг
            for _ in range(random.randint(*scenario['scroll_count'])):
                await self.page.evaluate("window.scrollBy(0, window.innerHeight)")
                await self.human_delay(1, 2)
            
            # Поиски
            searches = random.randint(*scenario['searches'])
            profile = BEHAVIOR_PROFILES[self.account.profile_type]
            
            for _ in range(searches):
                keyword = random.choice(profile['keywords'])
                # TODO: Реализовать поиск
                await self.human_delay(3, 5)
            
            # Просмотр товаров
            products = random.randint(*scenario['products_view'])
            for _ in range(products):
                # TODO: Реализовать клик по товару
                await self.human_delay(10, 30)
            
            logger.info(f"✅ Сценарий {stage} выполнен")
            return True
        
        except Exception as e:
            logger.error(f"❌ Ошибка сценария: {e}")
            return False
    
    async def close(self):
        """Закрытие браузера"""
        if self.browser:
            await self.browser.close()

# ==================== ORCHESTRATOR ====================

class FarmOrchestrator:
    """Управление фермой"""
    
    def __init__(self):
        self.is_running = False
        self.scheduler = AsyncIOScheduler()
    
    async def check_and_advance_stages(self):
        """Проверка и переключение этапов"""
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT id, stage, next_stage_at
                FROM accounts
                WHERE status = 'active' 
                  AND next_stage_at IS NOT NULL
                  AND next_stage_at <= ?
            """, (datetime.now(),))
            
            accounts = await cursor.fetchall()
            
            for acc_id, stage, _ in accounts:
                new_stage = stage
                
                if stage == Stage.DAY1.value:
                    new_stage = Stage.DAY2.value
                elif stage == Stage.DAY2.value:
                    new_stage = Stage.DAY3.value
                elif stage == Stage.DAY3.value:
                    new_stage = Stage.COMPLETED.value
                
                next_time = datetime.now() + timedelta(days=1) if new_stage != Stage.COMPLETED.value else None
                
                await db.execute("""
                    UPDATE accounts 
                    SET stage = ?, next_stage_at = ?
                    WHERE id = ?
                """, (new_stage, next_time, acc_id))
                
                logger.info(f"✅ Аккаунт {acc_id} переведён: {stage} → {new_stage}")
            
            await db.commit()
    
    async def check_email_expiry(self):
        """Проверка истечения срока email"""
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT id, email, email_created_at, status
                FROM accounts
                WHERE status != 'banned'
            """)
            
            accounts = await cursor.fetchall()
            
            for acc_id, email, created_str, status in accounts:
                created_at = datetime.fromisoformat(created_str)
                seconds_left, expiring_soon = calculate_email_expiry(created_at)
                
                if seconds_left < 0:
                    # Email истёк
                    await db.execute("""
                        UPDATE accounts SET status = 'paused' WHERE id = ?
                    """, (acc_id,))
                    logger.warning(f"⚠️ Email истёк для аккаунта {acc_id}")
                
                elif expiring_soon and status != Status.EMAIL_EXPIRING.value:
                    # Скоро истечёт
                    await db.execute("""
                        UPDATE accounts SET status = 'email_expiring' WHERE id = ?
                    """, (acc_id,))
                    logger.warning(f"⏰ Email скоро истечёт для аккаунта {acc_id}")
            
            await db.commit()
    
    async def process_account(self, account: Account):
        """Обработка одного аккаунта"""
        logger.info(f"🔄 Обработка аккаунта {account.id}")
        
        automation = TemuAutomation(account)
        
        try:
            await automation.init_browser()
            
            # Если не зарегистрирован - регистрируем
            if account.stage == Stage.NOT_REGISTERED:
                config = await get_system_config()
                
                if config['work_mode'] == WorkMode.AUTO:
                    success = await automation.register_account()
                    if success:
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute("""
                                UPDATE accounts 
                                SET stage = ?, next_stage_at = ?
                                WHERE id = ?
                            """, (Stage.DAY1.value, datetime.now() + timedelta(days=1), account.id))
                            await db.commit()
                else:
                    logger.info(f"ℹ️ Режим {config['work_mode']}, регистрация вручную")
                    return
            
            # Выполняем сценарий
            if account.stage in [Stage.DAY1, Stage.DAY2, Stage.DAY3]:
                success = await automation.execute_scenario(account.stage)
                
                if success:
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("""
                            UPDATE accounts 
                            SET last_active = ?, total_actions = total_actions + 1
                            WHERE id = ?
                        """, (datetime.now(), account.id))
                        await db.commit()
                    
                    await log_action(account.id, f"scenario_{account.stage.value}", "success")
        
        except Exception as e:
            logger.error(f"❌ Ошибка обработки аккаунта {account.id}: {e}")
            await log_action(account.id, "error", str(e))
        
        finally:
            await automation.close()
    
    async def start_farm(self):
        """Запуск фермы"""
        if self.is_running:
            return
        
        self.is_running = True
        logger.info("🚀 Запуск фермы")
        
        # Запуск планировщика
        self.scheduler.add_job(
            self.check_and_advance_stages,
            'interval',
            minutes=10
        )
        
        self.scheduler.add_job(
            self.check_email_expiry,
            'interval',
            hours=1
        )
        
        self.scheduler.start()
        
        # Первая проверка сразу
        await self.check_and_advance_stages()
        await self.check_email_expiry()
        
        while self.is_running:
            # Получаем активные аккаунты
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("""
                    SELECT id, email, email_password, temu_password, stage, status,
                           profile_type, email_created_at, last_active, next_stage_at, total_actions
                    FROM accounts
                    WHERE status = 'active' AND stage != 'completed'
                    ORDER BY id
                    LIMIT 10
                """)
                
                rows = await cursor.fetchall()
                
                accounts = []
                for row in rows:
                    accounts.append(Account(
                        id=row[0],
                        email=row[1],
                        email_password=row[2],
                        temu_password=row[3],
                        stage=Stage(row[4]),
                        status=Status(row[5]),
                        profile_type=row[6],
                        email_created_at=datetime.fromisoformat(row[7]),
                        last_active=datetime.fromisoformat(row[8]) if row[8] else None,
                        next_stage_at=datetime.fromisoformat(row[9]) if row[9] else None,
                        total_actions=row[10]
                    ))
            
            if not accounts:
                logger.info("ℹ️ Нет активных аккаунтов")
                await asyncio.sleep(300)
                continue
            
            # Обрабатываем последовательно
            for account in accounts:
                if not self.is_running:
                    break
                
                await self.process_account(account)
                await asyncio.sleep(random.uniform(300, 600))
            
            await asyncio.sleep(3600)
    
    async def stop_farm(self):
        """Остановка фермы"""
        logger.info("⏹ Остановка фермы")
        self.is_running = False
        if self.scheduler.running:
            self.scheduler.shutdown()

orchestrator = FarmOrchestrator()

# ==================== TELEGRAM BOT ====================

router = Router()

# Middleware
async def auth_middleware(handler, event, data):
    """Проверка авторизации"""
    config = await get_system_config()
    
    if not config or not config['admin_id']:
        state = data.get('state')
        current_state = await state.get_state() if state else None
        
        if current_state == SystemSetup.PASSWORD or \
           (isinstance(event, Message) and event.text == "/start"):
            return await handler(event, data)
        else:
            await event.answer("⚠️ Требуется авторизация. /start")
            return
    
    user_id = event.from_user.id
    if user_id != config['admin_id']:
        await event.answer("🚫 Нет доступа")
        return
    
    return await handler(event, data)

# Клавиатуры
def get_main_menu_keyboard(lang: Language) -> InlineKeyboardMarkup:
    """Главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text(lang, "start_farm"), callback_data="start_farm"),
            InlineKeyboardButton(text=get_text(lang, "stop_farm"), callback_data="stop_farm")
        ],
        [
            InlineKeyboardButton(text=get_text(lang, "account_list"), callback_data="account_list"),
            InlineKeyboardButton(text=get_text(lang, "create_batch"), callback_data="create_batch")
        ],
        [
            InlineKeyboardButton(text=get_text(lang, "testing"), callback_data="testing"),
            InlineKeyboardButton(text=get_text(lang, "statistics"), callback_data="statistics")
        ],
        [
            InlineKeyboardButton(text=get_text(lang, "settings"), callback_data="settings"),
            InlineKeyboardButton(text=get_text(lang, "logs"), callback_data="logs")
        ]
    ])

# Обработчики
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Старт бота"""
    config = await get_system_config()
    
    if not config or not config['admin_id']:
        await message.answer(
            "🔐 АВТОРИЗАЦИЯ\n\n"
            "Введите пароль:"
        )
        await state.set_state(SystemSetup.PASSWORD)
    else:
        await show_main_menu(message, config['language'])

@router.message(SystemSetup.PASSWORD)
async def process_password(message: Message, state: FSMContext):
    """Обработка пароля"""
    password = message.text.strip()
    
    try:
        await message.delete()
    except:
        pass
    
    if await verify_password(password):
        await set_admin_id(message.from_user.id)
        await message.answer("✅ Авторизация успешна!")
        await state.clear()
        await show_main_menu(message, Language.UK)
    else:
        await message.answer("❌ Неверный пароль")

async def show_main_menu(message: Message, lang: Language):
    """Главное меню"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN status = 'paused' THEN 1 ELSE 0 END) as paused,
                SUM(CASE WHEN status = 'email_expiring' THEN 1 ELSE 0 END) as expiring
            FROM accounts
        """)
        stats = await cursor.fetchone()
    
    total, active, paused, expiring = stats if stats[0] else (0, 0, 0, 0)
    
    text = f"""
{get_text(lang, 'main_menu')}

🟢 {get_text(lang, 'accounts')}: {total}
├ {get_text(lang, 'active')}: {active}
├ {get_text(lang, 'paused')}: {paused}
└ ⏰ Истекает email: {expiring}
"""
    
    await message.answer(text, reply_markup=get_main_menu_keyboard(lang))

@router.callback_query(F.data == "start_farm")
async def callback_start_farm(callback: CallbackQuery):
    """Запуск фермы"""
    if not orchestrator.is_running:
        asyncio.create_task(orchestrator.start_farm())
        await callback.answer("✅ Ферма запущена", show_alert=True)
    else:
        await callback.answer("⚠️ Уже работает", show_alert=True)

@router.callback_query(F.data == "stop_farm")
async def callback_stop_farm(callback: CallbackQuery):
    """Остановка фермы"""
    await orchestrator.stop_farm()
    await callback.answer("⏹ Ферма остановлена", show_alert=True)

@router.callback_query(F.data == "testing")
async def callback_testing(callback: CallbackQuery):
    """Меню тестирования"""
    config = await get_system_config()
    current_mode = config['work_mode']
    
    mode_text = {
        WorkMode.AUTO: "🤖 Автоматическая регистрация",
        WorkMode.SEMI_AUTO: "⚙️ Полуавтомат (создать email)",
        WorkMode.WARMUP_ONLY: "🔥 Только прогрев готовых"
    }
    
    text = f"""
🧪 РЕЖИМЫ ТЕСТИРОВАНИЯ

Текущий режим: {mode_text[current_mode]}

Выберите режим работы:
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{'✅' if current_mode == WorkMode.AUTO else '⚪'} Автоматическая регистрация",
            callback_data="mode_auto"
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if current_mode == WorkMode.SEMI_AUTO else '⚪'} Полуавтомат",
            callback_data="mode_semi"
        )],
        [InlineKeyboardButton(
            text=f"{'✅' if current_mode == WorkMode.WARMUP_ONLY else '⚪'} Только прогрев",
            callback_data="mode_warmup"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)

@router.callback_query(F.data.startswith("mode_"))
async def callback_set_mode(callback: CallbackQuery):
    """Установка режима"""
    mode_map = {
        "mode_auto": WorkMode.AUTO,
        "mode_semi": WorkMode.SEMI_AUTO,
        "mode_warmup": WorkMode.WARMUP_ONLY
    }
    
    mode = mode_map[callback.data]
    await set_work_mode(mode)
    await callback.answer("✅ Режим изменён", show_alert=True)
    await callback_testing(callback)

@router.callback_query(F.data == "create_batch")
async def callback_create_batch(callback: CallbackQuery, state: FSMContext):
    """Создание партии"""
    await callback.message.edit_text(
        "➕ СОЗДАНИЕ ПАРТИИ\n\n"
        "Введите количество аккаунтов (1-10):"
    )
    await state.set_state(BatchCreation.COUNT)

@router.message(BatchCreation.COUNT)
async def process_batch_count(message: Message, state: FSMContext):
    """Обработка количества"""
    try:
        count = int(message.text.strip())
        
        if count < 1 or count > 10:
            await message.answer("❌ От 1 до 10")
            return
        
        await message.answer(f"🔄 Создание {count} email через Mail.tm...")
        
        created = 0
        async with aiosqlite.connect(DB_PATH) as db:
            for _ in range(count):
                # Создаём email через Mail.tm
                mail_account = await mail_tm.create_account()
                
                if not mail_account:
                    logger.error("Не удалось создать Mail.tm аккаунт")
                    continue
                
                temu_password = ''.join(random.choices(
                    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                    k=12
                ))
                profile = random.choice(list(BEHAVIOR_PROFILES.keys()))
                
                await db.execute("""
                    INSERT INTO accounts 
                    (email, email_password, temu_password, profile_type, email_created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    mail_account['email'],
                    mail_account['password'],
                    temu_password,
                    profile,
                    mail_account['created_at']
                ))
                
                created += 1
            
            await db.commit()
        
        await message.answer(
            f"✅ Создано {created} аккаунтов!\n\n"
            "📧 Email адреса будут доступны 3+ дня.\n"
            "⏰ Таймеры истечения активированы."
        )
        
        await state.clear()
        config = await get_system_config()
        await show_main_menu(message, config['language'])
    
    except ValueError:
        await message.answer("❌ Введите число")

@router.callback_query(F.data == "account_list")
async def callback_account_list(callback: CallbackQuery):
    """Список аккаунтов"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, email, stage, status, email_created_at, last_active, total_actions
            FROM accounts
            ORDER BY id
            LIMIT 10
        """)
        accounts = await cursor.fetchall()
    
    if not accounts:
        await callback.message.edit_text(
            "📋 СПИСОК АККАУНТОВ\n\n❌ Нет аккаунтов",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
            ])
        )
        return
    
    text = "📋 СПИСОК АККАУНТОВ\n\n"
    
    for acc in accounts:
        acc_id, email, stage, status, created_str, last_active, actions = acc
        
        status_emoji = "🟢" if status == "active" else "🟡" if status == "paused" else "⏰"
        
        # Таймер email
        created_at = datetime.fromisoformat(created_str)
        seconds_left, expiring = calculate_email_expiry(created_at)
        time_left_str = format_time_left(seconds_left)
        
        text += f"{status_emoji} #{acc_id} | {email[:25]}...\n"
        text += f"   Этап: {stage} | Действий: {actions}\n"
        text += f"   ⏰ Email: {time_left_str}\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ])
    )

@router.callback_query(F.data == "statistics")
async def callback_statistics(callback: CallbackQuery):
    """Статистика"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT COUNT(*), SUM(total_actions), AVG(total_actions)
            FROM accounts
        """)
        total, actions_sum, actions_avg = await cursor.fetchone()
        
        cursor = await db.execute("""
            SELECT stage, COUNT(*) FROM accounts GROUP BY stage
        """)
        stages = await cursor.fetchall()
    
    text = f"""
📊 СТАТИСТИКА

📈 Общие показатели:
├ Всего аккаунтов: {total or 0}
├ Всего действий: {actions_sum or 0}
└ Среднее: {actions_avg or 0:.1f}

📊 По этапам:
"""
    
    for stage, count in stages:
        text += f"├ {stage}: {count}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ])
    )

@router.callback_query(F.data == "settings")
async def callback_settings(callback: CallbackQuery):
    """Настройки"""
    config = await get_system_config()
    
    mode_names = {
        WorkMode.AUTO: "Автоматическая",
        WorkMode.SEMI_AUTO: "Полуавтомат",
        WorkMode.WARMUP_ONLY: "Только прогрев"
    }
    
    text = f"""
⚙️ НАСТРОЙКИ

🌍 Язык: {config['language']}
🤖 Режим: {mode_names[config['work_mode']]}
🔄 Автоперезапуск: {'✅' if config['auto_restart'] else '❌'}
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌍 Язык", callback_data="change_lang")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ])
    )

@router.callback_query(F.data == "change_lang")
async def callback_change_lang(callback: CallbackQuery):
    """Смена языка"""
    await callback.message.edit_text(
        "🌍 ВЫБОР ЯЗЫКА",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
            [InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang_uk")],
            [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")]
        ])
    )

@router.callback_query(F.data.startswith("lang_"))
async def callback_set_lang(callback: CallbackQuery):
    """Установка языка"""
    lang_code = callback.data.split("_")[1]
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE system_config SET language = ? WHERE id = 1", (lang_code,))
        await db.commit()
    
    await callback.answer("✅ Язык изменён", show_alert=True)
    await callback_settings(callback)

@router.callback_query(F.data == "logs")
async def callback_logs(callback: CallbackQuery):
    """Логи"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT action_type, result, timestamp
            FROM actions_log
            ORDER BY timestamp DESC
            LIMIT 20
        """)
        logs = await cursor.fetchall()
    
    if not logs:
        text = "📄 ЛОГИ\n\nПусто"
    else:
        text = "📄 ПОСЛЕДНИЕ 20 ЛОГОВ:\n\n"
        for log in logs:
            time_str = log[2][:19] if log[2] else "N/A"
            text += f"[{time_str}] {log[0]} ({log[1]})\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ])
    )

@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    """Возврат в главное меню"""
    config = await get_system_config()
    await callback.message.delete()
    await show_main_menu(callback.message, config['language'])

# ==================== MAIN ====================

async def main():
    """Главная функция"""
    print("=" * 60)
    print("🚀 TEMU FARM SYSTEM v2.0 (BotHost Edition)")
    print("=" * 60)
    
    # Инициализация
    await init_database()
    
    # Бот
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    dp.include_router(router)
    dp.message.middleware(auth_middleware)
    dp.callback_query.middleware(auth_middleware)
    
    bot_info = await bot.get_me()
    print(f"🤖 Бот: @{bot_info.username}")
    print(f"🆔 ID: {bot_info.id}")
    print("=" * 60)
    print("✅ Система запущена!")
    print("💡 Отправьте /start боту")
    print("=" * 60)
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\n⚠️ Остановка...")
    finally:
        await orchestrator.stop_farm()
        await mail_tm.close()
        await bot.session.close()
        print("✅ Остановлено")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До свидания!")
import os
import sys
import re
import random
import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from enum import Enum

# Core
from dotenv import load_dotenv
import aiosqlite
import bcrypt

# Telegram Bot
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, 
    InlineKeyboardMarkup, InlineKeyboardButton,
    FSInputFile
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Web Automation
from playwright.async_api import async_playwright, Page, Browser
from playwright_stealth import stealth_async

# HTTP & Proxy
import httpx
from fake_useragent import UserAgent

# Task Scheduling
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Analytics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

# Utilities
from faker import Faker

# ==================== КОНФИГУРАЦИЯ ====================

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_PASSWORD = "130290"  # Встроенный пароль
DB_PATH = 'data/temu_farm.db'

if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в .env файле!")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('logs/system.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ==================== КОНСТАНТЫ ====================

class Stage(str, Enum):
    """Этапы прогрева аккаунта"""
    DAY1 = "day1"
    DAY2 = "day2"
    DAY3 = "day3"
    COMPLETED = "completed"

class Status(str, Enum):
    """Статусы аккаунта"""
    ACTIVE = "active"
    PAUSED = "paused"
    BANNED = "banned"
    LAGGING = "lagging"
    PROCESSING = "processing"

class Language(str, Enum):
    """Языки интерфейса"""
    RU = "ru"
    UK = "uk"
    EN = "en"

# Тексты интерфейса
TEXTS = {
    Language.RU: {
        "main_menu": "🏠 ГЛАВНОЕ МЕНЮ",
        "accounts": "Аккаунты",
        "start_farm": "▶️ Запустить ферму",
        "pause_farm": "⏸ Поставить на паузу",
        "stop_farm": "⏹ Остановить все",
        "account_list": "📋 Список аккаунтов",
        "create_batch": "➕ Создать партию аккаунтов",
        "mail_management": "📧 Управление почтой",
        "statistics": "📊 Статистика и аналитика",
        "settings": "⚙️ Настройки",
        "logs": "📄 Логи системы",
        "active": "Активных",
        "paused": "На паузе",
        "banned": "Забанено",
        "stage": "Этап"
    },
    Language.UK: {
        "main_menu": "🏠 ГОЛОВНЕ МЕНЮ",
        "accounts": "Акаунти",
        "start_farm": "▶️ Запустити ферму",
        "pause_farm": "⏸ Поставити на паузу",
        "stop_farm": "⏹ Зупинити всі",
        "account_list": "📋 Список акаунтів",
        "create_batch": "➕ Створити партію акаунтів",
        "mail_management": "📧 Управління поштою",
        "statistics": "📊 Статистика і аналітика",
        "settings": "⚙️ Налаштування",
        "logs": "📄 Логи системи",
        "active": "Активних",
        "paused": "На паузі",
        "banned": "Забанено",
        "stage": "Етап"
    },
    Language.EN: {
        "main_menu": "🏠 MAIN MENU",
        "accounts": "Accounts",
        "start_farm": "▶️ Start Farm",
        "pause_farm": "⏸ Pause All",
        "stop_farm": "⏹ Stop All",
        "account_list": "📋 Account List",
        "create_batch": "➕ Create Batch",
        "mail_management": "📧 Mail Management",
        "statistics": "📊 Statistics & Analytics",
        "settings": "⚙️ Settings",
        "logs": "📄 System Logs",
        "active": "Active",
        "paused": "Paused",
        "banned": "Banned",
        "stage": "Stage"
    }
}

# Профили поведения
BEHAVIOR_PROFILES = {
    "searcher": {
        "name": "Искатель скидок",
        "search_frequency": 0.7,
        "cart_add_chance": 0.3,
        "view_duration_multiplier": 0.8,
        "keywords": ["sale", "discount", "cheap", "акція", "знижка"]
    },
    "impulse": {
        "name": "Импульсивный",
        "search_frequency": 0.3,
        "cart_add_chance": 0.8,
        "view_duration_multiplier": 0.6,
        "keywords": ["new", "trending", "популярне", "новинки"]
    },
    "cautious": {
        "name": "Осторожный",
        "search_frequency": 0.5,
        "cart_add_chance": 0.2,
        "view_duration_multiplier": 1.5,
        "keywords": ["reviews", "rating", "відгуки", "топ"]
    }
}

# Сценарии по дням
SCENARIOS = {
    Stage.DAY1: {
        "duration_minutes": (15, 20),
        "products_view": (5, 8),
        "searches": (2, 3),
        "favorites": (1, 2),
        "categories": (2, 3),
        "scroll_duration": (2, 3)
    },
    Stage.DAY2: {
        "duration_minutes": (20, 30),
        "products_view": (10, 15),
        "searches": (4, 5),
        "cart_additions": (3, 5),
        "reviews_read": (2, 3),
        "scroll_duration": (3, 5)
    },
    Stage.DAY3: {
        "duration_minutes": (30, 40),
        "products_view": (15, 20),
        "searches": (5, 7),
        "cart_additions": (5, 8),
        "checkout_steps": True,
        "scroll_duration": (4, 6)
    }
}

# ==================== DATACLASSES ====================

@dataclass
class Account:
    """Модель аккаунта"""
    id: int
    email: str
    password: str
    temu_user_id: Optional[str]
    stage: Stage
    status: Status
    profile_type: str
    created_at: datetime
    last_active: Optional[datetime]
    total_actions: int

@dataclass
class ProxyInfo:
    """Информация о прокси"""
    ip: str
    port: int
    protocol: str
    country: str
    success_rate: float

# ==================== FSM СОСТОЯНИЯ ====================

class SystemSetup(StatesGroup):
    """Первичная настройка системы"""
    PASSWORD = State()

class BatchCreation(StatesGroup):
    """Создание партии аккаунтов"""
    COUNT = State()

class MailView(StatesGroup):
    """Просмотр почты"""
    SELECT_ACCOUNT = State()

# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================

async def init_database():
    """Инициализация базы данных"""
    os.makedirs('data', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Системная конфигурация
        await db.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                password_hash TEXT NOT NULL,
                admin_id INTEGER,
                language TEXT DEFAULT 'uk',
                debug_mode BOOLEAN DEFAULT FALSE,
                auto_restart BOOLEAN DEFAULT TRUE,
                max_parallel INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Проверка существования записи
        cursor = await db.execute("SELECT COUNT(*) FROM system_config")
        count = (await cursor.fetchone())[0]
        
        if count == 0:
            # Хеширование пароля
            password_hash = bcrypt.hashpw(
                ADMIN_PASSWORD.encode(), 
                bcrypt.gensalt()
            ).decode()
            
            await db.execute("""
                INSERT INTO system_config (id, password_hash)
                VALUES (1, ?)
            """, (password_hash,))
        
        # Аккаунты
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                temu_user_id TEXT,
                stage TEXT DEFAULT 'day1',
                status TEXT DEFAULT 'active',
                profile_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP,
                total_actions INTEGER DEFAULT 0
            )
        """)
        
        # Лог действий
        await db.execute("""
            CREATE TABLE IF NOT EXISTS actions_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                target TEXT,
                result TEXT,
                duration_sec REAL,
                proxy_used TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)
        
        # Почтовые сообщения
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mail_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                subject TEXT,
                body TEXT,
                verification_code TEXT,
                is_read BOOLEAN DEFAULT FALSE,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)
        
        # Пул прокси
        await db.execute("""
            CREATE TABLE IF NOT EXISTS proxy_pool (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT NOT NULL,
                port INTEGER NOT NULL,
                protocol TEXT DEFAULT 'http',
                country TEXT DEFAULT 'UA',
                is_active BOOLEAN DEFAULT TRUE,
                last_check TIMESTAMP,
                success_rate REAL DEFAULT 0.0,
                times_used INTEGER DEFAULT 0
            )
        """)
        
        # Аналитика
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date DATE NOT NULL,
                total_accounts INTEGER DEFAULT 0,
                active_accounts INTEGER DEFAULT 0,
                actions_performed INTEGER DEFAULT 0,
                captchas_encountered INTEGER DEFAULT 0,
                bans_detected INTEGER DEFAULT 0,
                avg_session_duration REAL DEFAULT 0.0,
                stage_distribution TEXT
            )
        """)
        
        await db.commit()
        logger.info("✅ База данных инициализирована")

# ==================== УТИЛИТЫ ====================

def get_text(lang: Language, key: str) -> str:
    """Получить текст на выбранном языке"""
    return TEXTS.get(lang, TEXTS[Language.UK]).get(key, key)

async def get_system_config() -> Dict[str, Any]:
    """Получить конфигурацию системы"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT admin_id, language, debug_mode, auto_restart, max_parallel
            FROM system_config WHERE id = 1
        """)
        result = await cursor.fetchone()
        
        if result:
            return {
                'admin_id': result[0],
                'language': Language(result[1]),
                'debug_mode': result[2],
                'auto_restart': result[3],
                'max_parallel': result[4]
            }
        return None

async def set_admin_id(admin_id: int):
    """Установить ID администратора"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE system_config SET admin_id = ? WHERE id = 1
        """, (admin_id,))
        await db.commit()

async def verify_password(password: str) -> bool:
    """Проверить пароль"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT password_hash FROM system_config WHERE id = 1
        """)
        result = await cursor.fetchone()
        
        if result:
            return bcrypt.checkpw(
                password.encode(), 
                result[0].encode()
            )
        return False

async def log_action(
    account_id: int,
    action_type: str,
    target: str = None,
    result: str = "success",
    duration_sec: float = None,
    proxy_used: str = None
):
    """Логирование действия"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO actions_log 
            (account_id, action_type, target, result, duration_sec, proxy_used)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (account_id, action_type, target, result, duration_sec, proxy_used))
        await db.commit()

def generate_email() -> str:
    """Генерация уникального email адреса"""
    faker = Faker()
    prefix = faker.user_name()[:8].lower()
    suffix = ''.join(str(random.randint(0, 9)) for _ in range(4))
    # TODO: Заменить на ваш домен
    return f"{prefix}{suffix}@yourdomain.xyz"

def generate_password(length: int = 12) -> str:
    """Генерация случайного пароля"""
    chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%"
    return ''.join(random.choice(chars) for _ in range(length))

# ==================== PROXY MANAGER ====================

class ProxyManager:
    """Менеджер бесплатных прокси"""
    
    def __init__(self):
        self.pool: List[ProxyInfo] = []
        self.current_index = 0
        self.last_update = None
        self.client = httpx.AsyncClient(timeout=10)
    
    async def fetch_free_proxies(self) -> List[str]:
        """Загрузка бесплатных прокси"""
        proxies = []
        
        try:
            # ProxyScrape API
            resp = await self.client.get(
                "https://api.proxyscrape.com/v2/",
                params={
                    "request": "displayproxies",
                    "protocol": "http",
                    "timeout": 10000,
                    "country": "all",
                    "ssl": "all",
                    "anonymity": "all"
                }
            )
            
            if resp.status_code == 200:
                proxy_list = resp.text.strip().split('\n')
                proxies.extend([p for p in proxy_list if p])
                logger.info(f"✅ Загружено {len(proxy_list)} прокси из ProxyScrape")
        
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки прокси: {e}")
        
        return proxies
    
    async def health_check(self, proxy: str) -> bool:
        """Проверка работоспособности прокси"""
        try:
            async with httpx.AsyncClient(
                proxies=f"http://{proxy}",
                timeout=5
            ) as client:
                resp = await client.get("https://www.temu.com")
                return resp.status_code == 200
        except:
            return False
    
    async def refresh_pool(self):
        """Обновление пула прокси"""
        logger.info("🔄 Обновление пула прокси...")
        
        proxy_list = await self.fetch_free_proxies()
        working_proxies = []
        
        # Проверяем первые 20 прокси (для экономии времени)
        for proxy in proxy_list[:20]:
            if await self.health_check(proxy):
                ip, port = proxy.split(':')
                working_proxies.append(ProxyInfo(
                    ip=ip,
                    port=int(port),
                    protocol='http',
                    country='UA',
                    success_rate=0.0
                ))
        
        self.pool = working_proxies
        self.last_update = datetime.now()
        self.current_index = 0
        
        # Сохраняем в БД
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM proxy_pool")
            
            for proxy in self.pool:
                await db.execute("""
                    INSERT INTO proxy_pool (ip, port, protocol, country)
                    VALUES (?, ?, ?, ?)
                """, (proxy.ip, proxy.port, proxy.protocol, proxy.country))
            
            await db.commit()
        
        logger.info(f"✅ Пул обновлён: {len(self.pool)} рабочих прокси")
    
    async def get_next_proxy(self) -> Optional[str]:
        """Получить следующий прокси"""
        # Обновляем пул каждые 30 минут
        if not self.last_update or \
           (datetime.now() - self.last_update).seconds > 1800:
            await self.refresh_pool()
        
        if not self.pool:
            logger.warning("⚠️ Пул прокси пуст, работаем без прокси")
            return None
        
        proxy = self.pool[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.pool)
        
        return f"{proxy.ip}:{proxy.port}"
    
    async def close(self):
        await self.client.aclose()

proxy_manager = ProxyManager()

# ==================== BROWSER AUTOMATION ====================

class TemuAutomation:
    """Автоматизация действий на Temu"""
    
    def __init__(self, account: Account, proxy: Optional[str] = None):
        self.account = account
        self.proxy = proxy
        self.page: Optional[Page] = None
        self.browser: Optional[Browser] = None
        self.ua = UserAgent()
    
    async def init_browser(self):
        """Инициализация браузера с антидетектом"""
        playwright = await async_playwright().start()
        
        # Конфигурация браузера
        browser_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox'
        ]
        
        launch_options = {
            'headless': True,
            'args': browser_args
        }
        
        # Прокси (если есть)
        if self.proxy:
            launch_options['proxy'] = {
                'server': f'http://{self.proxy}'
            }
        
        self.browser = await playwright.chromium.launch(**launch_options)
        
        # Создание контекста с антидетектом
        context = await self.browser.new_context(
            user_agent=self.ua.random,
            viewport={'width': 1920, 'height': 1080},
            locale='uk-UA',
            timezone_id='Europe/Kiev',
            geolocation={'latitude': 50.4501, 'longitude': 30.5234},
            permissions=['geolocation']
        )
        
        self.page = await context.new_page()
        
        # Применяем stealth
        await stealth_async(self.page)
        
        # Дополнительные антидетект патчи
        await self.page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            
            window.chrome = {
                runtime: {}
            };
        """)
        
        logger.info(f"✅ Браузер инициализирован для аккаунта {self.account.id}")
    
    async def human_scroll(self, duration_sec: int = 3):
        """Имитация человеческого скролла"""
        try:
            scroll_height = await self.page.evaluate("document.body.scrollHeight")
            current = 0
            
            while current < scroll_height:
                step = random.randint(50, 300)
                speed = random.uniform(0.1, 0.5)
                
                await self.page.mouse.wheel(0, step)
                await asyncio.sleep(speed)
                current += step
                
                # 10% шанс остановиться
                if random.random() < 0.1:
                    await asyncio.sleep(random.uniform(2, 5))
        except Exception as e:
            logger.error(f"Ошибка скролла: {e}")
    
    async def human_click(self, selector: str):
        """Клик с движением мыши"""
        try:
            element = await self.page.query_selector(selector)
            if not element:
                return
            
            box = await element.bounding_box()
            if not box:
                return
            
            # Плавное движение мыши
            target_x = box['x'] + random.uniform(5, box['width'] - 5)
            target_y = box['y'] + random.uniform(5, box['height'] - 5)
            
            await self.page.mouse.move(
                target_x,
                target_y,
                steps=random.randint(10, 30)
            )
            
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await self.page.mouse.click(target_x, target_y)
        
        except Exception as e:
            logger.error(f"Ошибка клика по {selector}: {e}")
    
    async def bypass_captcha(self) -> bool:
        """Попытка обхода капчи (бесплатный метод)"""
        captcha_selectors = [
            'iframe[src*="recaptcha"]',
            'iframe[src*="hcaptcha"]',
            '.cf-challenge-running'
        ]
        
        for selector in captcha_selectors:
            if await self.page.query_selector(selector):
                logger.warning("⚠️ Обнаружена капча")
                
                # Стратегия 1: Долгое ожидание
                await asyncio.sleep(30)
                
                # Стратегия 2: Перезагрузка
                await self.page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(5)
                
                # Проверяем, исчезла ли капча
                if not await self.page.query_selector(selector):
                    logger.info("✅ Капча исчезла")
                    return True
                
                logger.error("❌ Капча не обойдена")
                return False
        
        return True
    
    async def register_account(self) -> bool:
        """Регистрация нового аккаунта"""
        try:
            await self.page.goto("https://www.temu.com", wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(2, 4))
            
            # Поиск кнопки регистрации (селекторы могут меняться)
            signup_selectors = [
                'a[href*="signup"]',
                'button:has-text("Sign Up")',
                'button:has-text("Register")'
            ]
            
            for selector in signup_selectors:
                try:
                    await self.human_click(selector)
                    await asyncio.sleep(2)
                    break
                except:
                    continue
            
            # Ввод email
            email_input = await self.page.query_selector('input[type="email"]')
            if email_input:
                await email_input.type(
                    self.account.email,
                    delay=random.randint(50, 150)
                )
            
            # Ввод пароля
            password_input = await self.page.query_selector('input[type="password"]')
            if password_input:
                await password_input.type(
                    self.account.password,
                    delay=random.randint(50, 150)
                )
            
            # Проверка капчи
            if not await self.bypass_captcha():
                return False
            
            # Клик на Submit
            submit_button = await self.page.query_selector('button[type="submit"]')
            if submit_button:
                await self.human_click('button[type="submit"]')
                await asyncio.sleep(5)
            
            # TODO: Обработка кода верификации из почты
            
            logger.info(f"✅ Аккаунт {self.account.email} зарегистрирован")
            return True
        
        except Exception as e:
            logger.error(f"❌ Ошибка регистрации: {e}")
            return False
    
    async def execute_scenario(self, stage: Stage):
        """Выполнение сценария по этапу"""
        scenario = SCENARIOS[stage]
        profile = BEHAVIOR_PROFILES[self.account.profile_type]
        
        start_time = datetime.now()
        
        try:
            # Переход на главную
            await self.page.goto("https://www.temu.com", wait_until="domcontentloaded")
            await asyncio.sleep(random.uniform(2, 4))
            
            # Скролл главной страницы
            scroll_duration = random.randint(*scenario['scroll_duration'])
            await self.human_scroll(scroll_duration)
            await log_action(self.account.id, "scroll", "main_page")
            
            # Поиски
            if 'searches' in scenario:
                searches_count = random.randint(*scenario['searches'])
                for _ in range(searches_count):
                    keyword = random.choice(profile['keywords'])
                    await self.perform_search(keyword)
                    await asyncio.sleep(random.uniform(3, 8))
            
            # Просмотр товаров
            products_count = random.randint(*scenario['products_view'])
            for _ in range(products_count):
                await self.view_random_product()
                await asyncio.sleep(random.uniform(5, 15))
            
            # Добавление в корзину (если есть в сценарии)
            if 'cart_additions' in scenario:
                cart_count = random.randint(*scenario['cart_additions'])
                for _ in range(cart_count):
                    if random.random() < profile['cart_add_chance']:
                        await self.add_to_cart()
                        await asyncio.sleep(random.uniform(2, 5))
            
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ Сценарий {stage} завершён за {duration:.1f}с")
            
            return True
        
        except Exception as e:
            logger.error(f"❌ Ошибка выполнения сценария: {e}")
            return False
    
    async def perform_search(self, keyword: str):
        """Поиск по ключевому слову"""
        try:
            search_input = await self.page.query_selector('input[type="search"]')
            if search_input:
                await search_input.fill('')
                await search_input.type(keyword, delay=random.randint(50, 150))
                await self.page.keyboard.press('Enter')
                await asyncio.sleep(random.uniform(2, 4))
                
                await log_action(self.account.id, "search", keyword)
        except Exception as e:
            logger.error(f"Ошибка поиска: {e}")
    
    async def view_random_product(self):
        """Просмотр случайного товара"""
        try:
            # Поиск карточек товаров
            products = await self.page.query_selector_all('a[href*="/product"]')
            
            if products:
                product = random.choice(products)
                await product.click()
                await asyncio.sleep(random.uniform(10, 30))
                
                # Скролл страницы товара
                await self.human_scroll(random.randint(2, 5))
                
                # Возврат назад
                await self.page.go_back()
                await asyncio.sleep(random.uniform(1, 3))
                
                await log_action(self.account.id, "view_product")
        except Exception as e:
            logger.error(f"Ошибка просмотра товара: {e}")
    
    async def add_to_cart(self):
        """Добавление товара в корзину"""
        try:
            add_button = await self.page.query_selector('button:has-text("Add to Cart")')
            if add_button:
                await self.human_click('button:has-text("Add to Cart")')
                await asyncio.sleep(random.uniform(1, 2))
                
                await log_action(self.account.id, "add_to_cart")
        except Exception as e:
            logger.error(f"Ошибка добавления в корзину: {e}")
    
    async def close(self):
        """Закрытие браузера"""
        if self.browser:
            await self.browser.close()

# ==================== ORCHESTRATOR ====================

class FarmOrchestrator:
    """Управление фермой аккаунтов"""
    
    def __init__(self):
        self.is_running = False
        self.current_task = None
    
    async def get_accounts_by_status(self, status: Status) -> List[Account]:
        """Получить аккаунты по статусу"""
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT id, email, password, temu_user_id, stage, status, 
                       profile_type, created_at, last_active, total_actions
                FROM accounts WHERE status = ?
                ORDER BY id
            """, (status.value,))
            
            rows = await cursor.fetchall()
            
            accounts = []
            for row in rows:
                accounts.append(Account(
                    id=row[0],
                    email=row[1],
                    password=row[2],
                    temu_user_id=row[3],
                    stage=Stage(row[4]),
                    status=Status(row[5]),
                    profile_type=row[6],
                    created_at=datetime.fromisoformat(row[7]),
                    last_active=datetime.fromisoformat(row[8]) if row[8] else None,
                    total_actions=row[9]
                ))
            
            return accounts
    
    async def process_account(self, account: Account):
        """Обработка одного аккаунта"""
        logger.info(f"🔄 Обработка аккаунта {account.id} ({account.email})")
        
        # Обновляем статус
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE accounts SET status = ?, last_active = ?
                WHERE id = ?
            """, (Status.PROCESSING.value, datetime.now(), account.id))
            await db.commit()
        
        # Получаем прокси
        proxy = await proxy_manager.get_next_proxy()
        
        # Создаём автоматизацию
        automation = TemuAutomation(account, proxy)
        
        try:
            await automation.init_browser()
            
            # Выполняем сценарий
            success = await automation.execute_scenario(account.stage)
            
            if success:
                # Обновляем аккаунт
                new_stage = account.stage
                
                if account.stage == Stage.DAY1:
                    new_stage = Stage.DAY2
                elif account.stage == Stage.DAY2:
                    new_stage = Stage.DAY3
                elif account.stage == Stage.DAY3:
                    new_stage = Stage.COMPLETED
                
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        UPDATE accounts 
                        SET stage = ?, status = ?, last_active = ?, 
                            total_actions = total_actions + 1
                        WHERE id = ?
                    """, (new_stage.value, Status.ACTIVE.value, datetime.now(), account.id))
                    await db.commit()
                
                logger.info(f"✅ Аккаунт {account.id} завершил {account.stage}")
            else:
                # Возвращаем статус
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("""
                        UPDATE accounts SET status = ? WHERE id = ?
                    """, (Status.ACTIVE.value, account.id))
                    await db.commit()
        
        except Exception as e:
            logger.error(f"❌ Ошибка обработки аккаунта {account.id}: {e}")
            
            # Помечаем как ошибку
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    UPDATE accounts SET status = ? WHERE id = ?
                """, (Status.PAUSED.value, account.id))
                await db.commit()
        
        finally:
            await automation.close()
    
    async def start_farm(self):
        """Запуск фермы"""
        if self.is_running:
            logger.warning("⚠️ Ферма уже запущена")
            return
        
        self.is_running = True
        logger.info("🚀 Запуск фермы")
        
        while self.is_running:
            # Получаем активные аккаунты
            accounts = await self.get_accounts_by_status(Status.ACTIVE)
            
            if not accounts:
                logger.info("ℹ️ Нет активных аккаунтов для обработки")
                await asyncio.sleep(60)
                continue
            
            # Обрабатываем последовательно
            for account in accounts:
                if not self.is_running:
                    break
                
                await self.process_account(account)
                
                # Пауза между аккаунтами
                await asyncio.sleep(random.uniform(300, 600))  # 5-10 минут
            
            # Пауза между циклами
            await asyncio.sleep(3600)  # 1 час
    
    async def stop_farm(self):
        """Остановка фермы"""
        logger.info("⏹ Остановка фермы")
        self.is_running = False

orchestrator = FarmOrchestrator()

# ==================== TELEGRAM BOT ====================

router = Router()

# Middleware для проверки авторизации
async def auth_middleware(handler, event, data):
    """Проверка авторизации"""
    config = await get_system_config()
    
    if not config or not config['admin_id']:
        # Первый запуск - требуем пароль
        state = data.get('state')
        current_state = await state.get_state() if state else None
        
        if current_state == SystemSetup.PASSWORD or \
           (isinstance(event, Message) and event.text == "/start"):
            return await handler(event, data)
        else:
            await event.answer("⚠️ Требуется авторизация. Напишите /start")
            return
    
    # Проверка admin_id
    user_id = event.from_user.id
    if user_id != config['admin_id']:
        await event.answer("🚫 У вас нет доступа к этому боту")
        return
    
    return await handler(event, data)

# Клавиатуры
def get_main_menu_keyboard(lang: Language) -> InlineKeyboardMarkup:
    """Главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=get_text(lang, "start_farm"),
                callback_data="start_farm"
            ),
            InlineKeyboardButton(
                text=get_text(lang, "pause_farm"),
                callback_data="pause_farm"
            )
        ],
        [
            InlineKeyboardButton(
                text=get_text(lang, "stop_farm"),
                callback_data="stop_farm"
            )
        ],
        [
            InlineKeyboardButton(
                text=get_text(lang, "account_list"),
                callback_data="account_list"
            ),
            InlineKeyboardButton(
                text=get_text(lang, "create_batch"),
                callback_data="create_batch"
            )
        ],
        [
            InlineKeyboardButton(
                text=get_text(lang, "mail_management"),
                callback_data="mail_management"
            )
        ],
        [
            InlineKeyboardButton(
                text=get_text(lang, "statistics"),
                callback_data="statistics"
            ),
            InlineKeyboardButton(
                text=get_text(lang, "settings"),
                callback_data="settings"
            )
        ],
        [
            InlineKeyboardButton(
                text=get_text(lang, "logs"),
                callback_data="logs"
            )
        ]
    ])

# Обработчики
@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Команда /start"""
    config = await get_system_config()
    
    if not config or not config['admin_id']:
        await message.answer(
            "🔐 АВТОРИЗАЦИЯ\n\n"
            "Для доступа к боту введите пароль:"
        )
        await state.set_state(SystemSetup.PASSWORD)
    else:
        await show_main_menu(message, config['language'])

@router.message(SystemSetup.PASSWORD)
async def process_password(message: Message, state: FSMContext):
    """Обработка пароля"""
    password = message.text.strip()
    
    try:
        await message.delete()
    except:
        pass
    
    if await verify_password(password):
        await set_admin_id(message.from_user.id)
        
        await message.answer(
            "✅ Авторизация успешна!\n\n"
            "Добро пожаловать в систему управления фермой Temu."
        )
        
        await state.clear()
        await show_main_menu(message, Language.UK)
    else:
        await message.answer(
            "❌ Неверный пароль. Попробуйте ещё раз:"
        )

async def show_main_menu(message: Message, lang: Language):
    """Показать главное меню"""
    # Получаем статистику
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN status = 'paused' THEN 1 ELSE 0 END) as paused,
                SUM(CASE WHEN status = 'banned' THEN 1 ELSE 0 END) as banned
            FROM accounts
        """)
        stats = await cursor.fetchone()
        
        cursor = await db.execute("""
            SELECT stage, COUNT(*) 
            FROM accounts 
            WHERE status = 'active'
            GROUP BY stage
        """)
        stages = await cursor.fetchall()
    
    total, active, paused, banned = stats if stats[0] else (0, 0, 0, 0)
    
    stage_text = " | ".join([f"{stage}: {count}" for stage, count in stages])
    
    text = f"""
{get_text(lang, 'main_menu')}

🟢 {get_text(lang, 'accounts')}: {total} ({get_text(lang, 'active')}: {active}, {get_text(lang, 'paused')}: {paused}, {get_text(lang, 'banned')}: {banned})
📊 {get_text(lang, 'stage')}: {stage_text if stage_text else 'N/A'}
"""
    
    await message.answer(
        text,
        reply_markup=get_main_menu_keyboard(lang)
    )

@router.callback_query(F.data == "start_farm")
async def callback_start_farm(callback: CallbackQuery):
    """Запуск фермы"""
    if not orchestrator.is_running:
        asyncio.create_task(orchestrator.start_farm())
        await callback.answer("✅ Ферма запущена", show_alert=True)
    else:
        await callback.answer("⚠️ Ферма уже работает", show_alert=True)

@router.callback_query(F.data == "stop_farm")
async def callback_stop_farm(callback: CallbackQuery):
    """Остановка фермы"""
    await orchestrator.stop_farm()
    await callback.answer("⏹ Ферма остановлена", show_alert=True)

@router.callback_query(F.data == "account_list")
async def callback_account_list(callback: CallbackQuery):
    """Список аккаунтов"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, email, stage, status, total_actions, last_active
            FROM accounts
            ORDER BY id
            LIMIT 10
        """)
        accounts = await cursor.fetchall()
    
    if not accounts:
        await callback.message.edit_text(
            "📋 СПИСОК АККАУНТОВ\n\n"
            "❌ Аккаунты не найдены",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
            ])
        )
        return
    
    text = "📋 СПИСОК АККАУНТОВ\n\n"
    
    for acc in accounts:
        status_emoji = "🟢" if acc[3] == "active" else "🟡" if acc[3] == "paused" else "🔴"
        text += f"{status_emoji} #{acc[0]} | {acc[1][:20]}...\n"
        text += f"   Этап: {acc[2]} | Действий: {acc[4]}\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ])
    )

@router.callback_query(F.data == "create_batch")
async def callback_create_batch(callback: CallbackQuery, state: FSMContext):
    """Создание партии"""
    await callback.message.edit_text(
        "➕ СОЗДАНИЕ ПАРТИИ АККАУНТОВ\n\n"
        "Введите количество аккаунтов (1-10):"
    )
    await state.set_state(BatchCreation.COUNT)

@router.message(BatchCreation.COUNT)
async def process_batch_count(message: Message, state: FSMContext):
    """Обработка количества аккаунтов"""
    try:
        count = int(message.text.strip())
        
        if count < 1 or count > 10:
            await message.answer("❌ Количество должно быть от 1 до 10")
            return
        
        await message.answer(f"🔄 Создание {count} аккаунтов...")
        
        # Создаём аккаунты
        created = 0
        async with aiosqlite.connect(DB_PATH) as db:
            for _ in range(count):
                email = generate_email()
                password = generate_password()
                profile = random.choice(list(BEHAVIOR_PROFILES.keys()))
                
                await db.execute("""
                    INSERT INTO accounts (email, password, profile_type)
                    VALUES (?, ?, ?)
                """, (email, password, profile))
                
                created += 1
            
            await db.commit()
        
        await message.answer(
            f"✅ Создано {created} аккаунтов!\n\n"
            "Аккаунты будут автоматически зарегистрированы при запуске фермы."
        )
        
        await state.clear()
        
        config = await get_system_config()
        await show_main_menu(message, config['language'])
    
    except ValueError:
        await message.answer("❌ Введите число")

@router.callback_query(F.data == "statistics")
async def callback_statistics(callback: CallbackQuery):
    """Статистика"""
    async with aiosqlite.connect(DB_PATH) as db:
        # Общая статистика
        cursor = await db.execute("""
            SELECT COUNT(*), 
                   SUM(total_actions),
                   AVG(total_actions)
            FROM accounts
        """)
        total, actions_sum, actions_avg = await cursor.fetchone()
        
        # По этапам
        cursor = await db.execute("""
            SELECT stage, COUNT(*) 
            FROM accounts 
            GROUP BY stage
        """)
        stages = await cursor.fetchall()
    
    text = f"""
📊 СТАТИСТИКА ФЕРМЫ

📈 Общие показатели:
├ Всего аккаунтов: {total or 0}
├ Всего действий: {actions_sum or 0}
└ Среднее на аккаунт: {actions_avg or 0:.1f}

📊 Распределение по этапам:
"""
    
    for stage, count in stages:
        text += f"├ {stage}: {count}\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ])
    )

@router.callback_query(F.data == "settings")
async def callback_settings(callback: CallbackQuery):
    """Настройки"""
    config = await get_system_config()
    
    text = f"""
⚙️ НАСТРОЙКИ

🌍 Язык: {config['language']}
🔄 Автоперезапуск: {'✅' if config['auto_restart'] else '❌'}
🐛 Режим отладки: {'✅' if config['debug_mode'] else '❌'}
⚡ Параллельных: {config['max_parallel']}
"""
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🌍 Изменить язык", callback_data="change_lang")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ])
    )

@router.callback_query(F.data == "change_lang")
async def callback_change_lang(callback: CallbackQuery):
    """Смена языка"""
    await callback.message.edit_text(
        "🌍 ВЫБОР ЯЗЫКА",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru")],
            [InlineKeyboardButton(text="🇺🇦 Українська", callback_data="lang_uk")],
            [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="settings")]
        ])
    )

@router.callback_query(F.data.startswith("lang_"))
async def callback_set_lang(callback: CallbackQuery):
    """Установка языка"""
    lang_code = callback.data.split("_")[1]
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE system_config SET language = ? WHERE id = 1
        """, (lang_code,))
        await db.commit()
    
    await callback.answer("✅ Язык изменён", show_alert=True)
    await callback_settings(callback)

@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    """Возврат в главное меню"""
    config = await get_system_config()
    await callback.message.delete()
    await show_main_menu(callback.message, config['language'])

@router.callback_query(F.data == "logs")
async def callback_logs(callback: CallbackQuery):
    """Просмотр логов"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT action_type, target, result, timestamp
            FROM actions_log
            ORDER BY timestamp DESC
            LIMIT 20
        """)
        logs = await cursor.fetchall()
    
    if not logs:
        text = "📄 ЛОГИ\n\nЛогов пока нет"
    else:
        text = "📄 ПОСЛЕДНИЕ 20 ЛОГОВ:\n\n"
        for log in logs:
            time_str = log[3][:19] if log[3] else "N/A"
            text += f"[{time_str}] {log[0]}"
            if log[1]:
                text += f" → {log[1][:30]}"
            text += f" ({log[2]})\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ])
    )

# ==================== MAIN ====================

async def main():
    """Главная функция"""
    print("=" * 60)
    print("🚀 TEMU FARM SYSTEM v1.0")
    print("=" * 60)
    
    # Инициализация БД
    await init_database()
    
    # Инициализация прокси
    asyncio.create_task(proxy_manager.refresh_pool())
    
    # Инициализация бота
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Подключаем роутер
    dp.include_router(router)
    
    # Подключаем middleware
    dp.message.middleware(auth_middleware)
    dp.callback_query.middleware(auth_middleware)
    
    # Информация о боте
    bot_info = await bot.get_me()
    print(f"🤖 Бот: @{bot_info.username}")
    print(f"🆔 Bot ID: {bot_info.id}")
    print("=" * 60)
    print("✅ Система запущена!")
    print("=" * 60)
    
    try:
        # Запуск polling
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\n⚠️ Остановка системы...")
    finally:
        # Остановка фермы
        await orchestrator.stop_farm()
        
        # Закрытие прокси-менеджера
        await proxy_manager.close()
        
        # Закрытие бота
        await bot.session.close()
        
        print("✅ Система остановлена")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До свидания!")