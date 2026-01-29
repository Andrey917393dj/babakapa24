"""
Telegram Multi-Account Automation Bot v2.0
Полностью улучшенная версия с исправлением всех критических проблем
"""

import asyncio
import os
import sys
import base64
import random
import time
import json
from datetime import datetime
from typing import Callable, Dict, Any, Awaitable, Optional

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import aiosqlite
from cryptography.fernet import Fernet
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, FloodWaitError

# ==================== КОНФИГУРАЦИЯ ====================

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
PASSWORD = "130290"  # ← ИЗМЕНИТЕ ПАРОЛЬ!
DB_PATH = 'data/database.db'
TARGET_BOT = '@ZnakomstvaAnonimniyChatBot'

if not TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в .env файле!")
    sys.exit(1)

print(f"🔐 Пароль для первого входа: {PASSWORD}")

# ==================== FSM СОСТОЯНИЯ ====================

class SystemSetup(StatesGroup):
    PASSWORD = State()
    API_ID = State()
    API_HASH = State()

class AccountAuth(StatesGroup):
    PHONE = State()
    CODE = State()
    PASSWORD = State()

class TextSettings(StatesGroup):
    ENTER_TEXT = State()

class CooldownSettings(StatesGroup):
    ENTER_VALUES = State()

class TimeoutSettings(StatesGroup):
    ENTER_TIMEOUT = State()

class PatternSettings(StatesGroup):
    EDIT_FIELD = State()

class WorkerState:
    IDLE = "idle"
    SEARCHING = "searching"
    IN_DIALOG = "in_dialog"
    WAITING_REPLY = "waiting_reply"
    PAUSED = "paused"
    ERROR = "error"
    STOPPED = "stopped"

# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================

async def init_database(password: str):
    os.makedirs('data', exist_ok=True)
    os.makedirs('data/sessions', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                password TEXT NOT NULL,
                api_id TEXT,
                api_hash TEXT,
                admin_id INTEGER,
                encryption_key TEXT NOT NULL,
                is_initialized BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor = await db.execute("SELECT COUNT(*) FROM system_config")
        count = (await cursor.fetchone())[0]
        
        if count == 0:
            encryption_key = Fernet.generate_key().decode()
            await db.execute("""
                INSERT INTO system_config 
                (id, password, encryption_key, is_initialized)
                VALUES (1, ?, ?, FALSE)
            """, (password, encryption_key))
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE NOT NULL,
                session_data TEXT NOT NULL,
                greeting_text TEXT DEFAULT 'Привет!',
                cooldown_search INTEGER DEFAULT 20,
                cooldown_send INTEGER DEFAULT 3,
                cooldown_skip INTEGER DEFAULT 15,
                timeout_reply INTEGER DEFAULT 90,
                status TEXT DEFAULT 'idle',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP,
                error_message TEXT
            )
        """)
        
        # Добавляем колонку timeout_reply если её нет
        try:
            await db.execute("ALTER TABLE accounts ADD COLUMN timeout_reply INTEGER DEFAULT 90")
        except:
            pass
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dialogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                username TEXT,
                user_id INTEGER,
                first_message TEXT,
                content_type TEXT,
                outcome TEXT,
                response_time REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dialog_id INTEGER NOT NULL,
                sender_id INTEGER NOT NULL,
                content TEXT,
                content_type TEXT,
                is_read BOOLEAN DEFAULT FALSE,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (dialog_id) REFERENCES dialogs(id)
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                date DATE NOT NULL,
                total_dialogs INTEGER DEFAULT 0,
                total_skips INTEGER DEFAULT 0,
                total_replies INTEGER DEFAULT 0,
                total_timeouts INTEGER DEFAULT 0,
                avg_response_time REAL DEFAULT 0,
                active_time_minutes INTEGER DEFAULT 0,
                FOREIGN KEY (account_id) REFERENCES accounts(id),
                UNIQUE(account_id, date)
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                level TEXT,
                message TEXT,
                extra TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bot_patterns (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                partner_found TEXT DEFAULT 'Нашёл собеседника!',
                partner_skipped TEXT DEFAULT '🤚|||завершил диалог',
                already_in_dialog TEXT DEFAULT '🔴|||недоступна в диалоге',
                system_messages TEXT DEFAULT '🛑 Подпишись|||оставить отзыв'
            )
        """)
        
        cursor = await db.execute("SELECT COUNT(*) FROM bot_patterns")
        count = (await cursor.fetchone())[0]
        
        if count == 0:
            await db.execute("""
                INSERT INTO bot_patterns (id, partner_found, partner_skipped, already_in_dialog, system_messages)
                VALUES (1, 'Нашёл собеседника!', '🤚|||завершил диалог', '🔴|||недоступна в диалоге', '🛑 Подпишись|||оставить отзыв')
            """)
        
        await db.commit()

# ==================== УТИЛИТЫ ====================

def get_status_emoji(status: str, is_active: bool) -> str:
    if not is_active:
        return "⚫"
    status_map = {
        'idle': '🔵', 'searching': '🟡', 'in_dialog': '🟢',
        'waiting_reply': '🟠', 'paused': '⏸', 'error': '🔴', 'stopped': '⏹'
    }
    return status_map.get(status, '⚪')

def get_status_text_ru(status: str) -> str:
    status_map = {
        'idle': 'Не активен', 'searching': 'Поиск собеседника', 'in_dialog': 'В диалоге',
        'waiting_reply': 'Ожидание ответа', 'paused': 'На паузе', 'error': 'Ошибка', 'stopped': 'Остановлен'
    }
    return status_map.get(status, 'Неизвестно')

async def log_to_db(account_id: int = None, level: str = "INFO", message: str = "", extra: dict = None):
    """Структурированное логирование"""
    async with aiosqlite.connect(DB_PATH) as db:
        extra_json = json.dumps(extra) if extra else None
        await db.execute("""
            INSERT INTO logs (account_id, level, message, extra, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (account_id, level, message, extra_json, datetime.now()))
        await db.commit()

def encrypt_session(session_string: str, key: str) -> str:
    fernet = Fernet(key.encode())
    encrypted = fernet.encrypt(session_string.encode())
    return base64.b64encode(encrypted).decode()

def decrypt_session(encrypted_session: str, key: str) -> str:
    fernet = Fernet(key.encode())
    encrypted_bytes = base64.b64decode(encrypted_session.encode())
    decrypted = fernet.decrypt(encrypted_bytes)
    return decrypted.decode()

async def update_account_status(account_id: int, status: str, error_message: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE accounts 
            SET status = ?, last_active = ?, error_message = ?
            WHERE id = ?
        """, (status, datetime.now(), error_message, account_id))
        await db.commit()

async def is_system_initialized() -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT is_initialized FROM system_config WHERE id = 1")
        result = await cursor.fetchone()
        return result[0] if result else False

async def get_admin_id() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT admin_id FROM system_config WHERE id = 1")
        result = await cursor.fetchone()
        return result[0] if result else None

async def verify_password(password: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT password FROM system_config WHERE id = 1")
        result = await cursor.fetchone()
        return result[0] == password if result else False

async def get_system_config():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT api_id, api_hash, encryption_key FROM system_config WHERE id = 1"
        )
        result = await cursor.fetchone()
        return {
            'api_id': int(result[0]),
            'api_hash': result[1],
            'encryption_key': result[2]
        } if result else None

# ==================== MIDDLEWARE ====================

async def check_authorization_middleware(
    handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
    event: Message | CallbackQuery,
    data: Dict[str, Any]
) -> Any:
    user_id = event.from_user.id
    is_init = await is_system_initialized()
    
    # Для неинициализированной системы
    if not is_init:
        state = data.get('state')
        current_state = await state.get_state() if state else None
        
        # Разрешаем только состояния настройки
        allowed_states = [
            SystemSetup.PASSWORD,
            SystemSetup.API_ID,
            SystemSetup.API_HASH
        ]
        
        if current_state in allowed_states or \
           (isinstance(event, Message) and event.text == "/start") or \
           (isinstance(event, CallbackQuery) and event.data.startswith("init_")):
            return await handler(event, data)
        else:
            text = "⚠️ Система не настроена. Завершите настройку или напишите /start"
            if isinstance(event, Message):
                await event.answer(text)
            else:
                await event.answer(text, show_alert=True)
            return
    
    # Для инициализированной системы проверяем admin_id
    admin_id = await get_admin_id()
    if user_id != admin_id:
        text = "🚫 У вас нет доступа к этому боту."
        if isinstance(event, Message):
            await event.answer(text)
        else:
            await event.answer(text, show_alert=True)
        return
    
    return await handler(event, data)

# ==================== КЛАВИАТУРЫ ====================

def get_main_menu_keyboard(has_accounts: bool = False) -> InlineKeyboardMarkup:
    if not has_accounts:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_account")],
            [InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings_menu")]
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏸ Пауза всех", callback_data="pause_all"),
            InlineKeyboardButton(text="▶️ Запустить всех", callback_data="start_all")
        ],
        [InlineKeyboardButton(text="⏹ Стоп всех", callback_data="stop_all")],
        [
            InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_account"),
            InlineKeyboardButton(text="📋 Аккаунты", callback_data="accounts_list")
        ],
        [
            InlineKeyboardButton(text="📝 Тексты", callback_data="set_texts"),
            InlineKeyboardButton(text="⏱ Задержки", callback_data="set_cooldowns")
        ],
        [
            InlineKeyboardButton(text="⏰ Таймауты", callback_data="set_timeouts"),
            InlineKeyboardButton(text="🔤 Паттерны", callback_data="set_patterns")
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats_menu"),
            InlineKeyboardButton(text="📄 Логи", callback_data="logs_menu")
        ]
    ])

# ==================== ВОРКЕР ====================

class AccountWorker:
    def __init__(self, account_id: int, client: TelegramClient, greeting: str, 
                 cd_search: int, cd_send: int, cd_skip: int, timeout_reply: int,
                 bot: Bot, admin_id: int):
        self.account_id = account_id
        self.client = client
        self.greeting = greeting
        self.cd_search = cd_search
        self.cd_send = cd_send
        self.cd_skip = cd_skip
        self.timeout_reply = timeout_reply
        self.bot = bot
        self.admin_id = admin_id
        
        self.state = WorkerState.IDLE
        self.is_running = True
        self.timer_task = None
        self._shutdown_event = asyncio.Event()
        
        # Метрики
        self.metrics = {
            'dialogs_started': 0,
            'replies_received': 0,
            'avg_response_time': 0,
            'errors_count': 0,
            'skips': 0,
            'timeouts': 0
        }
        self.dialog_start_time = None
        self.my_user_id = None
    
    async def start(self):
        try:
            await self.client.connect()
            
            # Получаем свой ID
            me = await self.client.get_me()
            self.my_user_id = me.id
            
            await log_to_db(self.account_id, "INFO", "Подключение установлено", 
                          extra={'user_id': self.my_user_id})
            
            @self.client.on(events.NewMessage(chats=TARGET_BOT))
            async def message_handler(event):
                await self.handle_message(event)
            
            await self.search_dialog()
            
            # Graceful shutdown
            while self.is_running:
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=1.0
                    )
                    break
                except asyncio.TimeoutError:
                    continue
        
        except asyncio.CancelledError:
            await log_to_db(self.account_id, "WARNING", "Принудительная остановка")
        except Exception as e:
            await log_to_db(self.account_id, "ERROR", f"Критическая ошибка: {e}")
            await update_account_status(self.account_id, WorkerState.ERROR, str(e))
            self.metrics['errors_count'] += 1
        finally:
            if self.client.is_connected():
                try:
                    await asyncio.wait_for(
                        self.client.disconnect(),
                        timeout=5.0
                    )
                    await log_to_db(self.account_id, "INFO", "Отключение завершено")
                except asyncio.TimeoutError:
                    await log_to_db(self.account_id, "WARNING", "Таймаут отключения")
    
    async def search_dialog(self, retry_count=0):
        if not self.is_running or self.state == WorkerState.PAUSED:
            return
        
        self.state = WorkerState.SEARCHING
        await update_account_status(self.account_id, WorkerState.SEARCHING)
        await log_to_db(self.account_id, "INFO", "🔍 Начало поиска")
        
        delay = self.cd_search + random.randint(-5, 5)
        await asyncio.sleep(max(1, delay))
        
        try:
            await self.client.send_message(TARGET_BOT, '/search')
            await log_to_db(self.account_id, "INFO", "📤 /search отправлен")
        
        except FloodWaitError as e:
            wait_time = e.seconds
            await log_to_db(self.account_id, "WARNING", 
                          f"FloodWait: {wait_time} сек", 
                          extra={'wait_seconds': wait_time})
            await asyncio.sleep(wait_time)
            await self.search_dialog(retry_count)
        
        except Exception as e:
            await log_to_db(self.account_id, "ERROR", f"Ошибка /search: {e}")
            self.metrics['errors_count'] += 1
            
            if retry_count < 3:
                await log_to_db(self.account_id, "INFO", 
                              f"Повтор через 10 сек (попытка {retry_count + 1}/3)")
                await asyncio.sleep(10)
                await self.search_dialog(retry_count + 1)
            else:
                self.state = WorkerState.ERROR
                await update_account_status(self.account_id, WorkerState.ERROR, str(e))
    
    async def handle_message(self, event):
        text = event.message.message if event.message.message else ""
        sender = await event.message.get_sender()
        
        # Игнорируем свои сообщения
        if sender and sender.id == self.my_user_id:
            return
        
        await log_to_db(self.account_id, "INFO", f"📨 Получено: {text[:50]}...",
                       extra={'sender_id': sender.id if sender else None})
        
        # Получение паттернов
        patterns = await self.get_patterns()
        
        # 1. НАИВЫСШИЙ ПРИОРИТЕТ: Системные сообщения
        if any(p in text for p in patterns['system_messages']):
            await log_to_db(self.account_id, "INFO", "Системное сообщение (игнор)")
            return
        
        # 2. Уже в диалоге
        if any(p in text for p in patterns['already_in_dialog']):
            await log_to_db(self.account_id, "WARNING", "Уже в диалоге")
            return
        
        # 3. Собеседник найден
        if any(p in text for p in patterns['partner_found']):
            await self.on_partner_found()
            return
        
        # 4. Собеседник скипнул
        if any(p in text for p in patterns['partner_skipped']):
            await self.on_partner_skipped()
            return
        
        # 5. Ответ собеседника (ТОЛЬКО в состоянии ожидания)
        if self.state == WorkerState.WAITING_REPLY:
            # Проверяем, что это не бот и есть контент
            if sender and not sender.bot:
                if text.strip() or event.message.photo or event.message.sticker or event.message.voice:
                    await self.on_partner_replied(event.message)
                    return
        
        # 6. Неизвестное сообщение
        await log_to_db(self.account_id, "WARNING", f"Неизвестное: {text[:50]}")
    
    async def get_patterns(self):
        """Получить паттерны из БД"""
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("SELECT * FROM bot_patterns WHERE id = 1")
            result = await cursor.fetchone()
            
            if result:
                return {
                    'partner_found': result[1].split('|||'),
                    'partner_skipped': result[2].split('|||'),
                    'already_in_dialog': result[3].split('|||'),
                    'system_messages': result[4].split('|||')
                }
            else:
                return {
                    'partner_found': ['Нашёл собеседника!'],
                    'partner_skipped': ['🤚', 'завершил диалог'],
                    'already_in_dialog': ['🔴', 'недоступна в диалоге'],
                    'system_messages': ['🛑 Подпишись', 'оставить отзыв']
                }
    
    async def on_partner_found(self):
        self.state = WorkerState.IN_DIALOG
        self.dialog_start_time = time.time()
        self.metrics['dialogs_started'] += 1
        
        await update_account_status(self.account_id, WorkerState.IN_DIALOG)
        await log_to_db(self.account_id, "INFO", "✅ Собеседник найден")
        
        delay = self.cd_send + random.uniform(-1, 1)
        await asyncio.sleep(max(0.5, delay))
        
        try:
            await self.client.send_message(TARGET_BOT, self.greeting)
            await log_to_db(self.account_id, "INFO", f"📤 Отправлен текст: {self.greeting}")
            
            self.state = WorkerState.WAITING_REPLY
            await update_account_status(self.account_id, WorkerState.WAITING_REPLY)
            
            if self.timer_task:
                self.timer_task.cancel()
            self.timer_task = asyncio.create_task(self.inactivity_timer())
            
        except FloodWaitError as e:
            await log_to_db(self.account_id, "WARNING", 
                          f"FloodWait при отправке: {e.seconds} сек")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            await log_to_db(self.account_id, "ERROR", f"Ошибка отправки: {e}")
            self.metrics['errors_count'] += 1
    
    async def on_partner_skipped(self):
        self.metrics['skips'] += 1
        await log_to_db(self.account_id, "INFO", "⏭ Собеседник скипнул")
        
        if self.timer_task:
            self.timer_task.cancel()
        
        delay = self.cd_skip + random.randint(-3, 3)
        await asyncio.sleep(max(1, delay))
        await self.search_dialog()
    
    async def on_partner_replied(self, message):
        if self.timer_task:
            self.timer_task.cancel()
        
        # Вычисляем время ответа
        response_time = None
        if self.dialog_start_time:
            response_time = time.time() - self.dialog_start_time
            
            # Обновляем среднее время
            n = self.metrics['replies_received']
            old_avg = self.metrics['avg_response_time']
            self.metrics['avg_response_time'] = (old_avg * n + response_time) / (n + 1)
        
        self.metrics['replies_received'] += 1
        
        # Определяем тип контента
        if message.text:
            content_type = "текст"
            content = message.text
        elif message.photo:
            content_type = "фото"
            content = "[Фото]"
        elif message.sticker:
            content_type = "стикер"
            content = "[Стикер]"
        elif message.voice:
            content_type = "голосовое"
            content = "[Голосовое]"
        else:
            content_type = "медиа"
            content = "[Медиа]"
        
        sender = await message.get_sender()
        username = sender.username if sender and sender.username else "Нет username"
        user_id = sender.id if sender else 0
        
        await log_to_db(self.account_id, "INFO", f"📩 Ответ: {content_type}",
                       extra={
                           'username': username,
                           'user_id': user_id,
                           'content_type': content_type,
                           'response_time': response_time
                       })
        
        # Сохраняем в БД
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO dialogs (account_id, username, user_id, first_message, content_type, outcome, response_time)
                VALUES (?, ?, ?, ?, ?, 'replied', ?)
            """, (self.account_id, username, user_id, content, content_type, response_time))
            await db.commit()
        
        # Уведомляем админа
        await self.notify_admin_reply(username, user_id, content, content_type, response_time)
        
        # Продолжаем ждать (может быть ещё сообщения)
        if self.state == WorkerState.WAITING_REPLY:
            self.timer_task = asyncio.create_task(self.inactivity_timer())
    
    async def inactivity_timer(self):
        try:
            await asyncio.sleep(self.timeout_reply)
            
            if self.state == WorkerState.WAITING_REPLY:
                self.metrics['timeouts'] += 1
                await log_to_db(self.account_id, "WARNING", 
                              f"⏰ Таймаут {self.timeout_reply} сек")
                self.state = WorkerState.PAUSED
                await update_account_status(self.account_id, WorkerState.PAUSED)
                await self.notify_admin_timeout()
        except asyncio.CancelledError:
            pass
    
    async def notify_admin_reply(self, username: str, user_id: int, content: str, 
                                content_type: str, response_time: Optional[float]):
        time_str = f"{response_time:.1f} сек" if response_time else "N/A"
        
        text = f"""
💬 Аккаунт {self.account_id}: Собеседник ответил!

👤 Username: @{username}
🆔 User ID: {user_id}
💬 Тип: {content_type}
📝 Сообщение: {content[:100]}
⏱ Время ответа: {time_str}
⏰ Время: {datetime.now().strftime('%H:%M:%S')}

⚠️ Бот продолжает работать
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏸ Остановить диалог", callback_data=f"worker_stop_dialog_{self.account_id}")],
            [InlineKeyboardButton(text="⏭ Скип и продолжить", callback_data=f"worker_skip_{self.account_id}")],
            [InlineKeyboardButton(text="📊 Главное меню", callback_data="main_menu")]
        ])
        
        try:
            await self.bot.send_message(self.admin_id, text, reply_markup=keyboard)
        except Exception as e:
            await log_to_db(self.account_id, "ERROR", f"Ошибка уведомления: {e}")
    
    async def notify_admin_timeout(self):
        text = f"""
⏰ Аккаунт {self.account_id}: Таймаут {self.timeout_reply} сек

Собеседник не ответил. Что делать?
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Скип", callback_data=f"worker_skip_{self.account_id}")],
            [InlineKeyboardButton(text="⏳ Ждать ещё", callback_data=f"worker_wait_{self.account_id}")],
            [InlineKeyboardButton(text="📊 Главное меню", callback_data="main_menu")]
        ])
        
        try:
            await self.bot.send_message(self.admin_id, text, reply_markup=keyboard)
        except Exception as e:
            await log_to_db(self.account_id, "ERROR", f"Ошибка уведомления: {e}")
    
    async def skip_dialog(self):
        try:
            await self.client.send_message(TARGET_BOT, '/next')
            await log_to_db(self.account_id, "INFO", "Отправлен /next")
            await asyncio.sleep(2)
            self.state = WorkerState.IDLE
            await self.search_dialog()
        except Exception as e:
            await log_to_db(self.account_id, "ERROR", f"Ошибка /next: {e}")
            self.metrics['errors_count'] += 1
    
    async def wait_more(self):
        self.state = WorkerState.WAITING_REPLY
        await update_account_status(self.account_id, WorkerState.WAITING_REPLY)
        
        if self.timer_task:
            self.timer_task.cancel()
        self.timer_task = asyncio.create_task(self.inactivity_timer())
        await log_to_db(self.account_id, "INFO", "⏳ Ожидание продолжено")
    
    async def resume(self):
        self.state = WorkerState.IDLE
        await self.search_dialog()
    
    async def pause(self):
        self.state = WorkerState.PAUSED
        await update_account_status(self.account_id, WorkerState.PAUSED)
        if self.timer_task:
            self.timer_task.cancel()
    
    async def stop(self):
        self.is_running = False
        self.state = WorkerState.STOPPED
        await update_account_status(self.account_id, WorkerState.STOPPED)
        if self.timer_task:
            self.timer_task.cancel()
        self._shutdown_event.set()

# ==================== МЕНЕДЖЕР ВОРКЕРОВ ====================

class WorkerManager:
    def __init__(self):
        self.workers: Dict[int, tuple[AccountWorker, asyncio.Task]] = {}
        self._locks: Dict[int, asyncio.Lock] = {}
    
    def _get_lock(self, account_id: int) -> asyncio.Lock:
        """Получить lock для аккаунта (thread-safe)"""
        if account_id not in self._locks:
            self._locks[account_id] = asyncio.Lock()
        return self._locks[account_id]
    
    async def start_worker(self, account_id: int, bot: Bot) -> bool:
        client = None
        try:
            async with self._get_lock(account_id):
                if account_id in self.workers:
                    return False
                
                config = await get_system_config()
                admin_id = await get_admin_id()
                if not config or not admin_id:
                    return False
                
                async with aiosqlite.connect(DB_PATH) as db:
                    cursor = await db.execute("""
                        SELECT phone, session_data, greeting_text, cooldown_search, 
                               cooldown_send, cooldown_skip, timeout_reply
                        FROM accounts WHERE id = ?
                    """, (account_id,))
                    account = await cursor.fetchone()
                
                if not account:
                    return False
                
                phone, encrypted_session, greeting, cd_search, cd_send, cd_skip, timeout_reply = account
                session_string = decrypt_session(encrypted_session, config['encryption_key'])
                
                client = TelegramClient(
                    StringSession(session_string),
                    config['api_id'],
                    config['api_hash']
                )
                
                # Подключаемся сразу для проверки
                await client.connect()
                
                worker = AccountWorker(
                    account_id, client, greeting, cd_search, cd_send, cd_skip, 
                    timeout_reply, bot, admin_id
                )
                task = asyncio.create_task(worker.start())
                
                self.workers[account_id] = (worker, task)
                await log_to_db(account_id, "INFO", "Воркер запущен")
                return True
        
        except Exception as e:
            if client and client.is_connected():
                await client.disconnect()
            await log_to_db(account_id, "ERROR", f"Ошибка запуска воркера: {e}")
            return False
    
    async def stop_worker(self, account_id: int) -> bool:
        async with self._get_lock(account_id):
            if account_id in self.workers:
                worker, task = self.workers[account_id]
                await worker.stop()
                
                try:
                    await asyncio.wait_for(task, timeout=10.0)
                except asyncio.TimeoutError:
                    task.cancel()
                    await log_to_db(account_id, "WARNING", "Принудительная остановка по таймауту")
                
                del self.workers[account_id]
                await log_to_db(account_id, "INFO", "Воркер остановлен")
                return True
            return False
    
    async def get_worker(self, account_id: int) -> Optional[AccountWorker]:
        if account_id in self.workers:
            return self.workers[account_id][0]
        return None
    
    async def pause_all_workers(self):
        for account_id in list(self.workers.keys()):
            worker = await self.get_worker(account_id)
            if worker:
                await worker.pause()
    
    async def resume_all_workers(self):
        for account_id in list(self.workers.keys()):
            worker = await self.get_worker(account_id)
            if worker and worker.state == WorkerState.PAUSED:
                await worker.resume()
    
    async def stop_all_workers(self):
        account_ids = list(self.workers.keys())
        for account_id in account_ids:
            await self.stop_worker(account_id)

worker_manager = WorkerManager()

# ==================== ОБРАБОТЧИКИ ====================

router_init = Router()
router_start = Router()
router_accounts = Router()
router_settings = Router()
router_control = Router()
router_stats = Router()
router_logs = Router()

# ==================== ИНИЦИАЛИЗАЦИЯ ====================

@router_init.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    
    is_init = await is_system_initialized()
    
    if not is_init:
        text = "🔐 АВТОРИЗАЦИЯ\n\nДля доступа к боту введите пароль:"
        await message.answer(text)
        await state.set_state(SystemSetup.PASSWORD)
    else:
        await show_main_menu(message)

@router_init.message(SystemSetup.PASSWORD)
async def process_password(message: Message, state: FSMContext):
    password = message.text.strip()
    
    try:
        await message.delete()
    except:
        pass
    
    if await verify_password(password):
        text = """
✅ Пароль верный!

🔧 ПЕРВИЧНАЯ НАСТРОЙКА

1️⃣ Получите API_ID и API_HASH:
   • https://my.telegram.org
   • API development tools
   • Создайте приложение

2️⃣ ID определится автоматически
"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Начать настройку", callback_data="init_start")]
        ])
        await message.answer(text, reply_markup=keyboard)
        await state.clear()
    else:
        await message.answer("❌ Неверный пароль. Попробуйте ещё раз:")

@router_init.callback_query(F.data == "init_start")
async def init_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📱 Шаг 1/2: Введите API_ID (число)\n\nПример: 12345678")
    await state.set_state(SystemSetup.API_ID)
    await callback.answer()

@router_init.message(SystemSetup.API_ID)
async def process_api_id(message: Message, state: FSMContext):
    api_id = message.text.strip()
    
    if not api_id.isdigit():
        await message.answer("❌ API_ID должен быть числом. Попробуйте ещё раз:")
        return
    
    await state.update_data(api_id=api_id)
    await message.answer("🔐 Шаг 2/2: Введите API_HASH\n\nПример: abcdef1234567890abcdef1234567890")
    await state.set_state(SystemSetup.API_HASH)

@router_init.message(SystemSetup.API_HASH)
async def process_api_hash(message: Message, state: FSMContext):
    api_hash = message.text.strip()
    
    if len(api_hash) < 32:
        await message.answer("❌ API_HASH слишком короткий. Попробуйте ещё раз:")
        return
    
    data = await state.get_data()
    api_id = data['api_id']
    admin_id = message.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE system_config 
            SET api_id = ?, api_hash = ?, admin_id = ?, is_initialized = TRUE, updated_at = CURRENT_TIMESTAMP
            WHERE id = 1
        """, (api_id, api_hash, admin_id))
        await db.commit()
    
    await message.answer(
        f"✅ Настройка завершена!\n\n"
        f"📋 Данные сохранены:\n"
        f"├ API_ID: {api_id}\n"
        f"├ API_HASH: {api_hash[:8]}...{api_hash[-4:]}\n"
        f"└ Admin ID: {admin_id}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_account")],
        [InlineKeyboardButton(text="📊 Главное меню", callback_data="main_menu")]
    ])
    
    await message.answer("Что дальше?", reply_markup=keyboard)
    await state.clear()

# ==================== ГЛАВНОЕ МЕНЮ ====================

async def get_accounts_status():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, phone, status, is_active FROM accounts ORDER BY id")
        return await cursor.fetchall()

async def show_main_menu(message: Message):
    accounts = await get_accounts_status()
    
    if not accounts:
        status_text = "📊 Статус работы:\n\n❌ Аккаунты не добавлены\n\nДобавьте хотя бы один аккаунт."
        keyboard = get_main_menu_keyboard(has_accounts=False)
    else:
        status_text = "📊 Статус работы:\n\n"
        for acc_id, phone, status, is_active in accounts:
            emoji = get_status_emoji(status, is_active)
            status_ru = get_status_text_ru(status)
            phone_masked = f"{phone[:4]}***{phone[-3:]}" if len(phone) > 7 else phone
            status_text += f"{emoji} Аккаунт {acc_id} ({phone_masked}): {status_ru}\n"
        keyboard = get_main_menu_keyboard(has_accounts=True)
    
    await message.answer(status_text, reply_markup=keyboard)

@router_start.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    await callback.message.delete()
    await show_main_menu(callback.message)
    await callback.answer()

# ==================== АККАУНТЫ ====================

@router_accounts.callback_query(F.data == "add_account")
async def add_account_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("📱 Введите номер телефона\n\nФормат: +79991234567")
    await state.set_state(AccountAuth.PHONE)
    await callback.answer()

@router_accounts.message(Command("cancel"))
async def cancel_auth(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer("❌ Операция отменена")
        await show_main_menu(message)

@router_accounts.message(AccountAuth.PHONE)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    
    if not phone.startswith('+') or not phone[1:].isdigit():
        await message.answer("❌ Неверный формат. Пример: +79991234567\n\nОтменить: /cancel")
        return
    
    config = await get_system_config()
    if not config:
        await message.answer("❌ Конфигурация не найдена")
        await state.clear()
        return
    
    client = TelegramClient(StringSession(), config['api_id'], config['api_hash'])
    
    try:
        await client.connect()
        await client.send_code_request(phone)
        
        await state.update_data(phone=phone, client=client, encryption_key=config['encryption_key'])
        await message.answer("🔐 Введите код из SMS\n\nОтменить: /cancel")
        await state.set_state(AccountAuth.CODE)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await client.disconnect()

@router_accounts.message(AccountAuth.CODE)
async def process_code(message: Message, state: FSMContext):
    code = message.text.strip().replace('-', '').replace(' ', '')
    data = await state.get_data()
    
    client = data['client']
    phone = data['phone']
    
    try:
        await client.sign_in(phone, code)
        
        if not await client.is_user_authorized():
            await message.answer("🔒 Введите пароль 2FA\n\nОтменить: /cancel")
            await state.set_state(AccountAuth.PASSWORD)
            return
        
        await save_account_session(client, phone, data['encryption_key'])
        await message.answer(f"✅ Аккаунт {phone} добавлен!")
        
        await client.disconnect()
        await state.clear()
        await show_main_menu(message)
        
    except SessionPasswordNeededError:
        await message.answer("🔒 Введите пароль 2FA\n\nОтменить: /cancel")
        await state.set_state(AccountAuth.PASSWORD)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await client.disconnect()

@router_accounts.message(AccountAuth.PASSWORD)
async def process_2fa_password(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    
    client = data['client']
    phone = data['phone']
    
    try:
        await client.sign_in(password=password)
        await save_account_session(client, phone, data['encryption_key'])
        await message.answer(f"✅ Аккаунт {phone} добавлен!")
        
        await client.disconnect()
        await state.clear()
        await show_main_menu(message)
    except Exception as e:
        await message.answer(f"❌ Неверный пароль: {e}")

async def save_account_session(client: TelegramClient, phone: str, encryption_key: str):
    session_string = client.session.save()
    encrypted_session = encrypt_session(session_string, encryption_key)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO accounts (phone, session_data) VALUES (?, ?)", 
                        (phone, encrypted_session))
        await db.commit()
    
    await log_to_db(None, "INFO", f"Добавлен аккаунт: {phone}")

@router_accounts.callback_query(F.data == "accounts_list")
async def accounts_list(callback: CallbackQuery):
    accounts = await get_accounts_status()
    
    if not accounts:
        await callback.answer("❌ Аккаунты не добавлены", show_alert=True)
        return
    
    text = "📋 СПИСОК АККАУНТОВ:\n\n"
    buttons = []
    
    for acc_id, phone, status, is_active in accounts:
        emoji = get_status_emoji(status, is_active)
        status_ru = get_status_text_ru(status)
        phone_masked = f"{phone[:4]}***{phone[-3:]}"
        text += f"{emoji} Аккаунт {acc_id}\n   Номер: {phone_masked}\n   Статус: {status_ru}\n\n"
        
        buttons.append([InlineKeyboardButton(text=f"{emoji} Аккаунт {acc_id}", 
                                            callback_data=f"account_detail_{acc_id}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router_accounts.callback_query(F.data.startswith("account_detail_"))
async def account_detail(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT phone, status, greeting_text, cooldown_search, cooldown_send, 
                   cooldown_skip, timeout_reply, is_active, last_active, error_message
            FROM accounts WHERE id = ?
        """, (account_id,))
        account = await cursor.fetchone()
    
    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    phone, status, greeting, cd_search, cd_send, cd_skip, timeout_reply, is_active, last_active, error = account
    status_ru = get_status_text_ru(status)
    is_running = account_id in worker_manager.workers
    
    text = f"📱 АККАУНТ {account_id}\n\n"
    text += f"Номер: {phone}\n"
    text += f"Статус: {status_ru}\n"
    text += f"Воркер: {'🟢 Запущен' if is_running else '⚫ Остановлен'}\n\n"
    text += f"📝 Текст: {greeting}\n\n"
    text += f"⏱ Задержки:\n├ Поиск: {cd_search} сек\n├ Отправка: {cd_send} сек\n└ Скип: {cd_skip} сек\n\n"
    text += f"⏰ Таймаут ответа: {timeout_reply} сек\n"
    
    if error:
        text += f"\n❌ Ошибка: {error}\n"
    
    buttons = []
    if is_running:
        buttons.append([InlineKeyboardButton(text="⏹ Остановить", 
                                            callback_data=f"stop_worker_{account_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="▶️ Запустить", 
                                            callback_data=f"start_worker_{account_id}")])
    
    buttons.append([InlineKeyboardButton(text="🗑 Удалить", 
                                        callback_data=f"delete_account_{account_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="accounts_list")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router_accounts.callback_query(F.data.startswith("start_worker_"))
async def start_worker(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    success = await worker_manager.start_worker(account_id, callback.bot)
    
    if success:
        await callback.answer("✅ Воркер запущен", show_alert=True)
    else:
        await callback.answer("❌ Не удалось запустить", show_alert=True)
    
    await account_detail(callback)

@router_accounts.callback_query(F.data.startswith("stop_worker_"))
async def stop_worker(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    success = await worker_manager.stop_worker(account_id)
    
    if success:
        await callback.answer("✅ Воркер остановлен", show_alert=True)
    else:
        await callback.answer("❌ Воркер не был запущен", show_alert=True)
    
    await account_detail(callback)

@router_accounts.callback_query(F.data.startswith("delete_account_"))
async def delete_account(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    await worker_manager.stop_worker(account_id)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        await db.commit()
    
    await log_to_db(account_id, "INFO", "Аккаунт удалён")
    await callback.answer("✅ Аккаунт удалён", show_alert=True)
    await accounts_list(callback)

# ==================== НАСТРОЙКИ ТЕКСТОВ ====================

@router_settings.callback_query(F.data == "set_texts")
async def set_texts_menu(callback: CallbackQuery):
    accounts = await get_accounts_status()
    
    if not accounts:
        await callback.answer("❌ Добавьте аккаунты", show_alert=True)
        return
    
    buttons = []
    for acc_id, phone, _, _ in accounts:
        phone_masked = f"{phone[:4]}***{phone[-3:]}"
        buttons.append([InlineKeyboardButton(text=f"Аккаунт {acc_id} ({phone_masked})", 
                                            callback_data=f"set_text_acc_{acc_id}")])
    
    buttons.append([InlineKeyboardButton(text="📋 Посмотреть все", callback_data="view_all_texts")])
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("📝 Выберите аккаунт:", reply_markup=keyboard)
    await callback.answer()

@router_settings.callback_query(F.data.startswith("set_text_acc_"))
async def set_text_account(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[3])
    
    await callback.message.edit_text(f"📝 Введите текст для Аккаунта {account_id}:\n\nОтменить: /cancel")
    await state.update_data(account_id=account_id)
    await state.set_state(TextSettings.ENTER_TEXT)
    await callback.answer()

@router_settings.message(TextSettings.ENTER_TEXT)
async def process_greeting_text(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data['account_id']
    greeting_text = message.text
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE accounts SET greeting_text = ? WHERE id = ?", 
                        (greeting_text, account_id))
        await db.commit()
    
    await message.answer(f"✅ Текст для Аккаунта {account_id} сохранён!")
    await state.clear()
    await show_main_menu(message)

@router_settings.callback_query(F.data == "view_all_texts")
async def view_all_texts(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, phone, greeting_text FROM accounts ORDER BY id")
        accounts = await cursor.fetchall()
    
    if not accounts:
        await callback.answer("❌ Аккаунты не добавлены", show_alert=True)
        return
    
    text = "📝 ТЕКСТЫ:\n\n"
    for acc_id, phone, greeting in accounts:
        phone_masked = f"{phone[:4]}***{phone[-3:]}"
        text += f"Аккаунт {acc_id} ({phone_masked}):\n└ {greeting}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="set_texts")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# ==================== НАСТРОЙКИ ЗАДЕРЖЕК ====================

@router_settings.callback_query(F.data == "set_cooldowns")
async def set_cooldowns_menu(callback: CallbackQuery):
    accounts = await get_accounts_status()
    
    if not accounts:
        await callback.answer("❌ Добавьте аккаунты", show_alert=True)
        return
    
    buttons = []
    for acc_id, phone, _, _ in accounts:
        phone_masked = f"{phone[:4]}***{phone[-3:]}"
        buttons.append([InlineKeyboardButton(text=f"Аккаунт {acc_id} ({phone_masked})", 
                                            callback_data=f"set_cooldown_acc_{acc_id}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("⏱ Выберите аккаунт:", reply_markup=keyboard)
    await callback.answer()

@router_settings.callback_query(F.data.startswith("set_cooldown_acc_"))
async def set_cooldown_account(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[3])
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT cooldown_search, cooldown_send, cooldown_skip 
            FROM accounts WHERE id = ?
        """, (account_id,))
        result = await cursor.fetchone()
    
    if not result:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    cd_search, cd_send, cd_skip = result
    
    await callback.message.edit_text(
        f"⏱ Текущие задержки Аккаунта {account_id}:\n\n"
        f"├ Между поисками: {cd_search} сек\n"
        f"├ Перед отправкой: {cd_send} сек\n"
        f"└ После скипа: {cd_skip} сек\n\n"
        f"Введите новые (через пробел):\n"
        f"Пример: 25 5 20\n\nОтменить: /cancel"
    )
    
    await state.update_data(account_id=account_id)
    await state.set_state(CooldownSettings.ENTER_VALUES)
    await callback.answer()

@router_settings.message(CooldownSettings.ENTER_VALUES)
async def process_cooldown_values(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data['account_id']
    
    try:
        values = message.text.strip().split()
        if len(values) != 3:
            await message.answer("❌ Введите 3 числа через пробел")
            return
        
        cd_search, cd_send, cd_skip = map(int, values)
        
        if any(v <= 0 for v in [cd_search, cd_send, cd_skip]):
            await message.answer("❌ Все значения должны быть > 0")
            return
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE accounts 
                SET cooldown_search = ?, cooldown_send = ?, cooldown_skip = ?
                WHERE id = ?
            """, (cd_search, cd_send, cd_skip, account_id))
            await db.commit()
        
        await message.answer(f"✅ Задержки для Аккаунта {account_id} сохранены")
        await state.clear()
        await show_main_menu(message)
    except ValueError:
        await message.answer("❌ Неверный формат")

# ==================== НАСТРОЙКИ ТАЙМАУТОВ ====================

@router_settings.callback_query(F.data == "set_timeouts")
async def set_timeouts_menu(callback: CallbackQuery):
    accounts = await get_accounts_status()
    
    if not accounts:
        await callback.answer("❌ Добавьте аккаунты", show_alert=True)
        return
    
    buttons = []
    for acc_id, phone, _, _ in accounts:
        phone_masked = f"{phone[:4]}***{phone[-3:]}"
        buttons.append([InlineKeyboardButton(text=f"Аккаунт {acc_id} ({phone_masked})", 
                                            callback_data=f"set_timeout_acc_{acc_id}")])
    
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("⏰ Выберите аккаунт:", reply_markup=keyboard)
    await callback.answer()

@router_settings.callback_query(F.data.startswith("set_timeout_acc_"))
async def set_timeout_account(callback: CallbackQuery, state: FSMContext):
    account_id = int(callback.data.split("_")[3])
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT timeout_reply FROM accounts WHERE id = ?
        """, (account_id,))
        result = await cursor.fetchone()
    
    if not result:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    timeout_reply = result[0]
    
    await callback.message.edit_text(
        f"⏰ Текущий таймаут ожидания ответа:\n"
        f"Аккаунт {account_id}: {timeout_reply} секунд\n\n"
        f"Введите новое значение в секундах:\n"
        f"Пример: 120 (для 2 минут)\n\n"
        f"Рекомендуемые значения:\n"
        f"├ 60 сек (1 минута)\n"
        f"├ 90 сек (1.5 минуты) - по умолчанию\n"
        f"├ 120 сек (2 минуты)\n"
        f"└ 180 сек (3 минуты)\n\n"
        f"Отменить: /cancel"
    )
    
    await state.update_data(account_id=account_id)
    await state.set_state(TimeoutSettings.ENTER_TIMEOUT)
    await callback.answer()

@router_settings.message(TimeoutSettings.ENTER_TIMEOUT)
async def process_timeout_value(message: Message, state: FSMContext):
    data = await state.get_data()
    account_id = data['account_id']
    
    try:
        timeout_value = int(message.text.strip())
        
        if timeout_value < 30:
            await message.answer("❌ Минимальное значение: 30 секунд")
            return
        
        if timeout_value > 600:
            await message.answer("❌ Максимальное значение: 600 секунд (10 минут)")
            return
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE accounts 
                SET timeout_reply = ?
                WHERE id = ?
            """, (timeout_value, account_id))
            await db.commit()
        
        await message.answer(
            f"✅ Таймаут для Аккаунта {account_id} обновлён!\n\n"
            f"Новое значение: {timeout_value} секунд ({timeout_value // 60} мин {timeout_value % 60} сек)\n\n"
            f"⚠️ Перезапустите воркер, чтобы изменения вступили в силу."
        )
        await state.clear()
        await show_main_menu(message)
    except ValueError:
        await message.answer("❌ Введите целое число")

# ==================== НАСТРОЙКИ ПАТТЕРНОВ ====================

@router_settings.callback_query(F.data == "set_patterns")
async def patterns_menu(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT partner_found, partner_skipped, already_in_dialog, system_messages 
            FROM bot_patterns WHERE id = 1
        """)
        result = await cursor.fetchone()
    
    if not result:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO bot_patterns (id, partner_found, partner_skipped, already_in_dialog, system_messages)
                VALUES (1, 'Нашёл собеседника!', '🤚|||завершил диалог', '🔴|||недоступна в диалоге', '🛑 Подпишись|||оставить отзыв')
            """)
            await db.commit()
        result = ('Нашёл собеседника!', '🤚|||завершил диалог', '🔴|||недоступна в диалоге', '🛑 Подпишись|||оставить отзыв')
    
    partner_found, partner_skipped, already_in_dialog, system_messages = result
    
    text = f"""
🔤 ПАТТЕРНЫ БОТА

Эти фразы бот ищет в сообщениях для определения событий.

📌 Разделяйте фразы через |||

1️⃣ Собеседник найден:
{partner_found}

2️⃣ Собеседник скипнул:
{partner_skipped}

3️⃣ Уже в диалоге:
{already_in_dialog}

4️⃣ Системные сообщения (игнорировать):
{system_messages}
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Изменить: Найден", callback_data="pattern_partner_found")],
        [InlineKeyboardButton(text="2️⃣ Изменить: Скипнул", callback_data="pattern_partner_skipped")],
        [InlineKeyboardButton(text="3️⃣ Изменить: В диалоге", callback_data="pattern_already_in_dialog")],
        [InlineKeyboardButton(text="4️⃣ Изменить: Системные", callback_data="pattern_system_messages")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router_settings.callback_query(F.data.startswith("pattern_"))
async def edit_pattern(callback: CallbackQuery, state: FSMContext):
    field = callback.data.replace("pattern_", "")
    
    field_names = {
        'partner_found': '1️⃣ Собеседник найден',
        'partner_skipped': '2️⃣ Собеседник скипнул',
        'already_in_dialog': '3️⃣ Уже в диалоге',
        'system_messages': '4️⃣ Системные сообщения'
    }
    
    await callback.message.edit_text(
        f"✏️ Редактирование: {field_names[field]}\n\n"
        f"Введите новые фразы через |||\n\n"
        f"Пример:\n"
        f"Нашёл собеседника!|||Собеседник найден\n\n"
        f"Отменить: /cancel"
    )
    
    await state.update_data(pattern_field=field)
    await state.set_state(PatternSettings.EDIT_FIELD)
    await callback.answer()

@router_settings.message(PatternSettings.EDIT_FIELD)
async def process_pattern(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data['pattern_field']
    value = message.text.strip()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"""
            UPDATE bot_patterns SET {field} = ? WHERE id = 1
        """, (value,))
        await db.commit()
    
    await message.answer("✅ Паттерн обновлён!")
    await state.clear()
    await show_main_menu(message)

# ==================== УПРАВЛЕНИЕ ====================

@router_control.callback_query(F.data == "start_all")
async def start_all_accounts(callback: CallbackQuery):
    accounts = await get_accounts_status()
    
    if not accounts:
        await callback.answer("❌ Нет аккаунтов", show_alert=True)
        return
    
    started_count = 0
    for acc_id, _, _, is_active in accounts:
        if is_active and acc_id not in worker_manager.workers:
            if await worker_manager.start_worker(acc_id, callback.bot):
                started_count += 1
    
    await callback.answer(f"▶️ Запущено {started_count} аккаунтов", show_alert=True)
    await log_to_db(None, "INFO", f"Запущены все ({started_count})")
    await callback_main_menu(callback)

@router_control.callback_query(F.data == "pause_all")
async def pause_all_accounts(callback: CallbackQuery):
    await worker_manager.pause_all_workers()
    await callback.answer("⏸ Все на паузе", show_alert=True)
    await log_to_db(None, "INFO", "Все на паузе")
    await callback_main_menu(callback)

@router_control.callback_query(F.data == "stop_all")
async def stop_all_accounts(callback: CallbackQuery):
    await worker_manager.stop_all_workers()
    await callback.answer("⏹ Все остановлены", show_alert=True)
    await log_to_db(None, "INFO", "Все остановлены")
    await callback_main_menu(callback)

@router_control.callback_query(F.data.startswith("worker_stop_dialog_"))
async def worker_stop_dialog(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[3])
    worker = await worker_manager.get_worker(account_id)
    
    if worker:
        try:
            await worker.client.send_message(TARGET_BOT, '/stop')
            await log_to_db(account_id, "INFO", "Отправлен /stop")
        except Exception as e:
            await log_to_db(account_id, "ERROR", f"Ошибка /stop: {e}")
        
        await worker.pause()
        await callback.answer("✅ Диалог остановлен, воркер на паузе", show_alert=True)
    else:
        await callback.answer("❌ Воркер не найден", show_alert=True)
    
    await callback.message.delete()

@router_control.callback_query(F.data.startswith("worker_skip_"))
async def worker_skip(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    worker = await worker_manager.get_worker(account_id)
    
    if worker:
        await worker.skip_dialog()
        await callback.answer("✅ Скип выполнен", show_alert=True)
    else:
        await callback.answer("❌ Воркер не найден", show_alert=True)
    
    await callback.message.delete()

@router_control.callback_query(F.data.startswith("worker_wait_"))
async def worker_wait(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    worker = await worker_manager.get_worker(account_id)
    
    if worker:
        await worker.wait_more()
        await callback.answer("✅ Ожидание продолжено", show_alert=True)
    else:
        await callback.answer("❌ Воркер не найден", show_alert=True)
    
    await callback.message.delete()

# ==================== СТАТИСТИКА ====================

@router_stats.callback_query(F.data == "stats_menu")
async def stats_menu(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT SUM(total_dialogs), SUM(total_skips), SUM(total_replies), 
                   SUM(total_timeouts), AVG(avg_response_time)
            FROM stats
        """)
        result = await cursor.fetchone()
    
    total_dialogs = result[0] or 0
    total_skips = result[1] or 0
    total_replies = result[2] or 0
    total_timeouts = result[3] or 0
    avg_response = result[4] or 0
    
    # Живые метрики из активных воркеров
    live_metrics = {
        'dialogs': 0,
        'replies': 0,
        'skips': 0,
        'timeouts': 0,
        'avg_time': 0
    }
    
    active_workers = 0
    for acc_id in worker_manager.workers:
        worker = await worker_manager.get_worker(acc_id)
        if worker:
            active_workers += 1
            live_metrics['dialogs'] += worker.metrics['dialogs_started']
            live_metrics['replies'] += worker.metrics['replies_received']
            live_metrics['skips'] += worker.metrics['skips']
            live_metrics['timeouts'] += worker.metrics['timeouts']
            if worker.metrics['avg_response_time'] > 0:
                live_metrics['avg_time'] += worker.metrics['avg_response_time']
    
    if active_workers > 0:
        live_metrics['avg_time'] /= active_workers
    
    text = f"""
📊 СТАТИСТИКА

📈 Всего за всё время:
├ Диалогов: {total_dialogs}
├ Скипов: {total_skips}
├ Ответов: {total_replies}
├ Таймаутов: {total_timeouts}
└ Средний ответ: {avg_response:.1f} сек

🔴 Текущая сессия ({active_workers} активных):
├ Диалогов: {live_metrics['dialogs']}
├ Скипов: {live_metrics['skips']}
├ Ответов: {live_metrics['replies']}
├ Таймаутов: {live_metrics['timeouts']}
└ Средний ответ: {live_metrics['avg_time']:.1f} сек
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# ==================== ЛОГИ ====================

@router_logs.callback_query(F.data == "logs_menu")
async def logs_menu(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT level, message, timestamp 
            FROM logs 
            ORDER BY timestamp DESC 
            LIMIT 10
        """)
        logs = await cursor.fetchall()
    
    if not logs:
        text = "📄 ЛОГИ\n\nЛогов пока нет"
    else:
        text = "📄 ПОСЛЕДНИЕ 10 ЛОГОВ:\n\n"
        for level, message, timestamp in logs:
            emoji = "ℹ️" if level == "INFO" else "⚠️" if level == "WARNING" else "❌"
            time_str = timestamp.split('.')[0] if '.' in timestamp else timestamp
            text += f"{emoji} [{time_str}] {message}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Скачать полные логи", callback_data="download_logs")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router_logs.callback_query(F.data == "download_logs")
async def download_logs(callback: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT account_id, level, message, extra, timestamp 
            FROM logs 
            ORDER BY timestamp DESC
        """)
        logs = await cursor.fetchall()
    
    if not logs:
        await callback.answer("❌ Логов нет", show_alert=True)
        return
    
    log_content = "TELEGRAM AUTOMATION BOT v2.0 - LOGS\n" + "=" * 60 + "\n\n"
    
    for account_id, level, message, extra, timestamp in logs:
        acc_str = f"ACC_{account_id}" if account_id else "SYSTEM"
        log_content += f"[{timestamp}] [{acc_str}] [{level}] {message}\n"
        if extra:
            log_content += f"  Extra: {extra}\n"
    
    log_file_path = "logs/bot_logs.txt"
    os.makedirs('logs', exist_ok=True)
    
    with open(log_file_path, 'w', encoding='utf-8') as f:
        f.write(log_content)
    
    log_file = FSInputFile(log_file_path)
    await callback.message.answer_document(log_file, caption="📄 Полные логи")
    await callback.answer("✅ Логи отправлены")

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

async def main():
    print("=" * 60)
    print("🚀 Запуск Telegram Automation Bot v2.0")
    print("=" * 60)
    
    print("📦 Инициализация БД...")
    await init_database(PASSWORD)
    print("✅ БД готова")
    print("=" * 60)
    
    bot = Bot(token=TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Подключаем все роутеры
    dp.include_router(router_init)
    dp.include_router(router_start)
    dp.include_router(router_accounts)
    dp.include_router(router_settings)
    dp.include_router(router_control)
    dp.include_router(router_stats)
    dp.include_router(router_logs)
    
    # Подключаем middleware
    dp.message.middleware(check_authorization_middleware)
    dp.callback_query.middleware(check_authorization_middleware)
    
    bot_info = await bot.get_me()
    print(f"🤖 Бот: @{bot_info.username}")
    print(f"🆔 Bot ID: {bot_info.id}")
    print("=" * 60)
    print("✅ Бот запущен и готов к работе!")
    print("📱 Отправьте /start боту для начала работы")
    print("=" * 60)
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\n⚠️  Получен сигнал остановки...")
    finally:
        print("\n🛑 Остановка всех воркеров...")
        await worker_manager.stop_all_workers()
        await bot.session.close()
        print("✅ Бот полностью остановлен")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До свидания!")