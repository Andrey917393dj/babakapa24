import asyncio
import os
import sys
import base64
from datetime import datetime
from typing import Callable, Dict, Any, Awaitable

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import aiosqlite
from cryptography.fernet import Fernet
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

# ==================== КОНФИГУРАЦИЯ ====================

load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
PASSWORD = "130290"  # ← ИЗМЕНИТЕ ЭТОТ ПАРОЛЬ ПЕРЕД ДЕПЛОЕМ!
DB_PATH = 'data/database.db'

if not TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в .env файле!")
    print("📝 Создайте файл .env и добавьте: BOT_TOKEN=ваш_токен")
    sys.exit(1)

print(f"🔐 Пароль для первого входа: {PASSWORD}")
print("⚠️  ВАЖНО: Измените PASSWORD в коде перед деплоем!")

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
    SELECT_ACCOUNT = State()
    ENTER_TEXT = State()

class CooldownSettings(StatesGroup):
    SELECT_ACCOUNT = State()
    ENTER_VALUES = State()

# ==================== ИНИЦИАЛИЗАЦИЯ БД ====================

async def init_database(password: str):
    """Инициализация базы данных"""
    os.makedirs('data', exist_ok=True)
    os.makedirs('data/sessions', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        # Таблица системных настроек
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
        
        # Таблица аккаунтов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE NOT NULL,
                session_data TEXT NOT NULL,
                greeting_text TEXT DEFAULT 'Привет!',
                cooldown_search INTEGER DEFAULT 20,
                cooldown_send INTEGER DEFAULT 3,
                cooldown_skip INTEGER DEFAULT 15,
                status TEXT DEFAULT 'idle',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP,
                error_message TEXT
            )
        """)
        
        # Таблица диалогов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS dialogs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                username TEXT,
                user_id INTEGER,
                first_message TEXT,
                content_type TEXT,
                outcome TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)
        
        # Таблица сообщений
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
        
        # Таблица статистики
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                date DATE NOT NULL,
                total_dialogs INTEGER DEFAULT 0,
                total_skips INTEGER DEFAULT 0,
                total_replies INTEGER DEFAULT 0,
                total_timeouts INTEGER DEFAULT 0,
                active_time_minutes INTEGER DEFAULT 0,
                FOREIGN KEY (account_id) REFERENCES accounts(id),
                UNIQUE(account_id, date)
            )
        """)
        
        # Таблица логов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER,
                level TEXT,
                message TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.commit()

# ==================== УТИЛИТЫ ====================

def get_status_emoji(status: str, is_active: bool) -> str:
    """Эмодзи для статуса"""
    if not is_active:
        return "⚫"
    status_map = {
        'idle': '🔵', 'searching': '🟡', 'in_dialog': '🟢',
        'waiting_reply': '🟠', 'paused': '⏸', 'error': '🔴', 'stopped': '⏹'
    }
    return status_map.get(status, '⚪')

def get_status_text_ru(status: str) -> str:
    """Русский текст статуса"""
    status_map = {
        'idle': 'Не активен', 'searching': 'Поиск собеседника', 'in_dialog': 'В диалоге',
        'waiting_reply': 'Ожидание ответа', 'paused': 'На паузе', 'error': 'Ошибка', 'stopped': 'Остановлен'
    }
    return status_map.get(status, 'Неизвестно')

async def log_to_db(account_id: int = None, level: str = "INFO", message: str = ""):
    """Запись лога в БД"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO logs (account_id, level, message, timestamp)
            VALUES (?, ?, ?, ?)
        """, (account_id, level, message, datetime.now()))
        await db.commit()

def encrypt_session(session_string: str, key: str) -> str:
    """Шифрование сессии"""
    fernet = Fernet(key.encode())
    encrypted = fernet.encrypt(session_string.encode())
    return base64.b64encode(encrypted).decode()

def decrypt_session(encrypted_session: str, key: str) -> str:
    """Расшифровка сессии"""
    fernet = Fernet(key.encode())
    encrypted_bytes = base64.b64decode(encrypted_session.encode())
    decrypted = fernet.decrypt(encrypted_bytes)
    return decrypted.decode()

# ==================== ПРОВЕРКИ АВТОРИЗАЦИИ ====================

async def is_system_initialized() -> bool:
    """Проверка инициализации системы"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT is_initialized FROM system_config WHERE id = 1")
        result = await cursor.fetchone()
        return result[0] if result else False

async def get_admin_id() -> int:
    """Получить ID администратора"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT admin_id FROM system_config WHERE id = 1")
        result = await cursor.fetchone()
        return result[0] if result else None

async def verify_password(password: str) -> bool:
    """Проверка пароля"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT password FROM system_config WHERE id = 1")
        result = await cursor.fetchone()
        return result[0] == password if result else False

async def get_system_config():
    """Получить системную конфигурацию"""
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
    """Middleware для проверки авторизации"""
    
    # Получаем состояние FSM
    state = data.get('state')
    if state:
        current_state = await state.get_state()
        # Если пользователь в процессе настройки - пропускаем
        if current_state:
            return await handler(event, data)
    
    user_id = event.from_user.id
    is_init = await is_system_initialized()
    
    if not is_init:
        # Разрешаем только /start и callback для настройки
        if isinstance(event, Message) and event.text == "/start":
            return await handler(event, data)
        elif isinstance(event, CallbackQuery) and event.data.startswith("init_"):
            return await handler(event, data)
        else:
            text = "⚠️ Система не настроена. Напишите /start"
            if isinstance(event, Message):
                await event.answer(text)
            else:
                await event.answer(text, show_alert=True)
            return
    
    # Если система инициализирована - проверяем права
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
    """Главное меню"""
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
            InlineKeyboardButton(text="📩 Сообщения", callback_data="messages_menu"),
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats_menu")
        ],
        [InlineKeyboardButton(text="📄 Логи", callback_data="logs_menu")]
    ])

# ==================== ВОРКЕРЫ ====================

class WorkerManager:
    """Менеджер воркеров"""
    def __init__(self):
        self.workers = {}  # account_id -> worker_task
    
    async def start_worker(self, account_id: int, bot):
        """Запуск воркера для аккаунта"""
        if account_id in self.workers:
            return False
        
        # Получение данных аккаунта
        config = await get_system_config()
        if not config:
            return False
        
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT phone, session_data, greeting_text, cooldown_search, cooldown_send, cooldown_skip
                FROM accounts WHERE id = ?
            """, (account_id,))
            account = await cursor.fetchone()
        
        if not account:
            return False
        
        phone, encrypted_session, greeting, cd_search, cd_send, cd_skip = account
        
        # Расшифровка сессии
        session_string = decrypt_session(encrypted_session, config['encryption_key'])
        
        # Создание клиента
        client = TelegramClient(
            StringSession(session_string),
            config['api_id'],
            config['api_hash']
        )
        
        # Запуск воркера
        task = asyncio.create_task(
            self._worker_loop(account_id, client, greeting, cd_search, cd_send, cd_skip, bot)
        )
        self.workers[account_id] = task
        
        await log_to_db(account_id, "INFO", f"Воркер аккаунта {account_id} запущен")
        return True
    
    async def _worker_loop(self, account_id, client, greeting, cd_search, cd_send, cd_skip, bot):
        """Основной цикл воркера"""
        try:
            await client.connect()
            await log_to_db(account_id, "INFO", f"Подключение установлено")
            
            # Обновление статуса
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    UPDATE accounts SET status = 'searching', last_active = ? WHERE id = ?
                """, (datetime.now(), account_id))
                await db.commit()
            
            # TODO: Здесь будет логика работы с @ZnakomstvaAnonimniyChatBot
            # Пока просто держим соединение открытым
            await log_to_db(account_id, "INFO", "Воркер работает (TODO: реализовать логику)")
            
            # Имитация работы (удалить потом)
            while account_id in self.workers:
                await asyncio.sleep(10)
                await log_to_db(account_id, "INFO", "Воркер активен")
                
        except Exception as e:
            await log_to_db(account_id, "ERROR", f"Ошибка воркера: {e}")
            
            # Обновление статуса ошибки
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    UPDATE accounts SET status = 'error', error_message = ? WHERE id = ?
                """, (str(e), account_id))
                await db.commit()
        finally:
            await client.disconnect()
    
    async def stop_worker(self, account_id: int):
        """Остановка воркера"""
        if account_id in self.workers:
            self.workers[account_id].cancel()
            del self.workers[account_id]
            
            # Обновление статуса
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    UPDATE accounts SET status = 'stopped' WHERE id = ?
                """, (account_id,))
                await db.commit()
            
            await log_to_db(account_id, "INFO", f"Воркер аккаунта {account_id} остановлен")
            return True
        return False
    
    async def stop_all_workers(self):
        """Остановка всех воркеров"""
        account_ids = list(self.workers.keys())
        for account_id in account_ids:
            await self.stop_worker(account_id)

# Глобальный менеджер воркеров
worker_manager = WorkerManager()

# ==================== ОБРАБОТЧИКИ: ИНИЦИАЛИЗАЦИЯ ====================

router_init = Router()

@router_init.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработка /start"""
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
    """Обработка пароля"""
    password = message.text.strip()
    
    try:
        await message.delete()
    except:
        pass
    
    if await verify_password(password):
        text = """
✅ Пароль верный!

🔧 ПЕРВИЧНАЯ НАСТРОЙКА

Для работы бота нужно выполнить настройку.

1️⃣ Получите API_ID и API_HASH:
   • Перейдите на https://my.telegram.org
   • Войдите с номером телефона
   • Откройте "API development tools"
   • Создайте приложение
   • Скопируйте api_id и api_hash

2️⃣ Ваш Telegram ID будет определён автоматически
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
    """Начало настройки"""
    await callback.message.edit_text(
        "📱 Шаг 1/2: Введите API_ID (число)\n\n"
        "Пример: 12345678"
    )
    await state.set_state(SystemSetup.API_ID)
    await callback.answer()

@router_init.message(SystemSetup.API_ID)
async def process_api_id(message: Message, state: FSMContext):
    """Обработка API_ID"""
    api_id = message.text.strip()
    
    if not api_id.isdigit():
        await message.answer("❌ API_ID должен быть числом. Попробуйте ещё раз:")
        return
    
    await state.update_data(api_id=api_id)
    await message.answer(
        "🔐 Шаг 2/2: Введите API_HASH (длинная строка)\n\n"
        "Пример: abcdef1234567890abcdef1234567890"
    )
    await state.set_state(SystemSetup.API_HASH)

@router_init.message(SystemSetup.API_HASH)
async def process_api_hash(message: Message, state: FSMContext):
    """Обработка API_HASH"""
    api_hash = message.text.strip()
    
    if len(api_hash) < 32:
        await message.answer("❌ API_HASH слишком короткий. Попробуйте ещё раз:")
        return
    
    data = await state.get_data()
    api_id = data['api_id']
    admin_id = message.from_user.id
    
    # Сохранение в БД
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
        f"└ Admin ID: {admin_id}\n\n"
        f"🎉 Теперь вы можете добавить аккаунты!"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_account")],
        [InlineKeyboardButton(text="📊 Главное меню", callback_data="main_menu")]
    ])
    
    await message.answer("Что дальше?", reply_markup=keyboard)
    await state.clear()

@router_init.message(Command("reset_config"))
async def reset_config(message: Message):
    """Сброс настроек"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, сбросить", callback_data="reset_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="reset_cancel")]
    ])
    
    await message.answer(
        "⚠️ ВНИМАНИЕ!\n\n"
        "Это удалит ВСЕ настройки и аккаунты.\n"
        "Потребуется заново вводить пароль и API данные.\n\n"
        "Вы уверены?",
        reply_markup=keyboard
    )

@router_init.callback_query(F.data == "reset_confirm")
async def reset_confirm(callback: CallbackQuery):
    """Подтверждение сброса"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT password, encryption_key FROM system_config WHERE id = 1")
        result = await cursor.fetchone()
        password = result[0] if result else PASSWORD
        encryption_key = result[1] if result else Fernet.generate_key().decode()
        
        await db.execute("DELETE FROM accounts")
        await db.execute("DELETE FROM dialogs")
        await db.execute("DELETE FROM messages")
        await db.execute("DELETE FROM stats")
        await db.execute("DELETE FROM logs")
        
        await db.execute("""
            UPDATE system_config 
            SET api_id = NULL, api_hash = NULL, admin_id = NULL, is_initialized = FALSE, encryption_key = ?
            WHERE id = 1
        """, (encryption_key,))
        await db.commit()
    
    await callback.message.edit_text("✅ Настройки сброшены.\n\nНапишите /start для новой настройки.")
    await callback.answer()

@router_init.callback_query(F.data == "reset_cancel")
async def reset_cancel(callback: CallbackQuery):
    """Отмена сброса"""
    await callback.message.edit_text("❌ Сброс отменён.")
    await callback.answer()

# ==================== ОБРАБОТЧИКИ: ГЛАВНОЕ МЕНЮ ====================

router_start = Router()

async def get_accounts_status():
    """Получить статус всех аккаунтов"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT id, phone, status, is_active FROM accounts ORDER BY id
        """)
        return await cursor.fetchall()

async def show_main_menu(message: Message):
    """Показать главное меню"""
    accounts = await get_accounts_status()
    
    if not accounts:
        status_text = "📊 Статус работы:\n\n❌ Аккаунты не добавлены\n\nДобавьте хотя бы один аккаунт для начала работы."
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
    """Обработка кнопки главного меню"""
    await callback.message.delete()
    await show_main_menu(callback.message)
    await callback.answer()

# ==================== ОБРАБОТЧИКИ: АККАУНТЫ ====================

router_accounts = Router()

@router_accounts.callback_query(F.data == "add_account")
async def add_account_start(callback: CallbackQuery, state: FSMContext):
    """Начало добавления аккаунта"""
    await callback.message.edit_text(
        "📱 Введите номер телефона\n\n"
        "Формат: +79991234567"
    )
    await state.set_state(AccountAuth.PHONE)
    await callback.answer()

@router_accounts.message(Command("cancel"))
async def cancel_auth(message: Message, state: FSMContext):
    """Отмена авторизации"""
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer("❌ Операция отменена")
        await show_main_menu(message)

@router_accounts.message(AccountAuth.PHONE)
async def process_phone(message: Message, state: FSMContext):
    """Обработка номера телефона"""
    phone = message.text.strip()
    
    if not phone.startswith('+') or not phone[1:].isdigit():
        await message.answer("❌ Неверный формат. Пример: +79991234567\n\nОтменить: /cancel")
        return
    
    config = await get_system_config()
    if not config:
        await message.answer("❌ Системная конфигурация не найдена. Выполните /reset_config")
        await state.clear()
        return
    
    client = TelegramClient(StringSession(), config['api_id'], config['api_hash'])
    
    try:
        await client.connect()
        await client.send_code_request(phone)
        
        await state.update_data(
            phone=phone,
            client=client,
            encryption_key=config['encryption_key']
        )
        
        await message.answer("🔐 Введите код из SMS\n\nКод придёт в Telegram или SMS\n\nОтменить: /cancel")
        await state.set_state(AccountAuth.CODE)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\n\nОтменить: /cancel")
        await client.disconnect()

@router_accounts.message(AccountAuth.CODE)
async def process_code(message: Message, state: FSMContext):
    """Обработка кода авторизации"""
    code = message.text.strip().replace('-', '').replace(' ', '')
    data = await state.get_data()
    
    client = data['client']
    phone = data['phone']
    
    try:
        await client.sign_in(phone, code)
        
        # Проверка авторизации
        if not await client.is_user_authorized():
            await message.answer("🔒 Введите пароль двухфакторной аутентификации\n\nОтменить: /cancel")
            await state.set_state(AccountAuth.PASSWORD)
            return
        
        # Авторизация успешна
        await save_account_session(client, phone, data['encryption_key'])
        await message.answer(f"✅ Аккаунт {phone} успешно добавлен!")
        
        await client.disconnect()
        await state.clear()
        await show_main_menu(message)
        
    except SessionPasswordNeededError:
        # Требуется 2FA пароль
        await message.answer("🔒 Введите пароль двухфакторной аутентификации\n\nОтменить: /cancel")
        await state.set_state(AccountAuth.PASSWORD)
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}\n\nПопробуйте ещё раз или отменить: /cancel")
        await client.disconnect()

@router_accounts.message(AccountAuth.PASSWORD)
async def process_2fa_password(message: Message, state: FSMContext):
    """Обработка пароля 2FA"""
    password = message.text.strip()
    data = await state.get_data()
    
    client = data['client']
    phone = data['phone']
    
    try:
        await client.sign_in(password=password)
        await save_account_session(client, phone, data['encryption_key'])
        await message.answer(f"✅ Аккаунт {phone} успешно добавлен!")
        
        await client.disconnect()
        await state.clear()
        await show_main_menu(message)
    except Exception as e:
        await message.answer(f"❌ Неверный пароль: {e}\n\nПопробуйте ещё раз или отменить: /cancel")

async def save_account_session(client: TelegramClient, phone: str, encryption_key: str):
    """Сохранение сессии аккаунта в БД"""
    session_string = client.session.save()
    encrypted_session = encrypt_session(session_string, encryption_key)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO accounts (phone, session_data)
            VALUES (?, ?)
        """, (phone, encrypted_session))
        await db.commit()
    
    await log_to_db(None, "INFO", f"Добавлен новый аккаунт: {phone}")

@router_accounts.callback_query(F.data == "accounts_list")
async def accounts_list(callback: CallbackQuery):
    """Список аккаунтов"""
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
        text += f"{emoji} Аккаунт {acc_id}\n"
        text += f"   Номер: {phone_masked}\n"
        text += f"   Статус: {status_ru}\n\n"
        
        buttons.append([InlineKeyboardButton(
            text=f"{emoji} Аккаунт {acc_id}",
            callback_data=f"account_detail_{acc_id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router_accounts.callback_query(F.data.startswith("account_detail_"))
async def account_detail(callback: CallbackQuery):
    """Детали аккаунта"""
    account_id = int(callback.data.split("_")[2])
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT phone, status, greeting_text, cooldown_search, cooldown_send, cooldown_skip, 
                   is_active, last_active, error_message
            FROM accounts WHERE id = ?
        """, (account_id,))
        account = await cursor.fetchone()
    
    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    phone, status, greeting, cd_search, cd_send, cd_skip, is_active, last_active, error = account
    status_ru = get_status_text_ru(status)
    
    # Проверка, запущен ли воркер
    is_running = account_id in worker_manager.workers
    
    text = f"📱 АККАУНТ {account_id}\n\n"
    text += f"Номер: {phone}\n"
    text += f"Статус: {status_ru}\n"
    text += f"Активен: {'Да' if is_active else 'Нет'}\n"
    text += f"Воркер: {'🟢 Запущен' if is_running else '⚫ Остановлен'}\n\n"
    text += f"📝 Текст приветствия:\n{greeting}\n\n"
    text += f"⏱ Задержки:\n"
    text += f"├ Поиск: {cd_search} сек\n"
    text += f"├ Отправка: {cd_send} сек\n"
    text += f"└ Скип: {cd_skip} сек\n"
    
    if last_active:
        text += f"\n🕐 Последняя активность: {last_active}\n"
    
    if error:
        text += f"\n❌ Ошибка: {error}\n"
    
    # Кнопки управления
    buttons = []
    
    if is_running:
        buttons.append([InlineKeyboardButton(text="⏹ Остановить", callback_data=f"stop_worker_{account_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="▶️ Запустить", callback_data=f"start_worker_{account_id}")])
    
    buttons.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_account_{account_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="accounts_list")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router_accounts.callback_query(F.data.startswith("start_worker_"))
async def start_worker(callback: CallbackQuery):
    """Запуск воркера аккаунта"""
    account_id = int(callback.data.split("_")[2])
    
    success = await worker_manager.start_worker(account_id, callback.bot)
    
    if success:
        await callback.answer("✅ Воркер запущен", show_alert=True)
    else:
        await callback.answer("❌ Не удалось запустить воркер", show_alert=True)
    
    # Обновить детали аккаунта
    await account_detail(callback)

@router_accounts.callback_query(F.data.startswith("stop_worker_"))
async def stop_worker(callback: CallbackQuery):
    """Остановка воркера аккаунта"""
    account_id = int(callback.data.split("_")[2])
    
    success = await worker_manager.stop_worker(account_id)
    
    if success:
        await callback.answer("✅ Воркер остановлен", show_alert=True)
    else:
        await callback.answer("❌ Воркер не был запущен", show_alert=True)
    
    # Обновить детали аккаунта
    await account_detail(callback)

@router_accounts.callback_query(F.data.startswith("delete_account_"))
async def delete_account(callback: CallbackQuery):
    """Удаление аккаунта"""
    account_id = int(callback.data.split("_")[2])
    
    # Остановить воркер если запущен
    await worker_manager.stop_worker(account_id)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        await db.commit()
    
    await log_to_db(account_id, "INFO", f"Аккаунт {account_id} удалён")
    await callback.answer("✅ Аккаунт удалён", show_alert=True)
    await accounts_list(callback)

# ==================== ОБРАБОТЧИКИ: НАСТРОЙКИ ====================

router_settings = Router()

@router_settings.callback_query(F.data == "set_texts")
async def set_texts_menu(callback: CallbackQuery):
    """Меню настройки текстов"""
    accounts = await get_accounts_status()
    
    if not accounts:
        await callback.answer("❌ Добавьте аккаунты сначала", show_alert=True)
        return
    
    buttons = []
    for acc_id, phone, _, _ in accounts:
        phone_masked = f"{phone[:4]}***{phone[-3:]}"
        buttons.append([InlineKeyboardButton(
            text=f"Аккаунт {acc_id} ({phone_masked})",
            callback_data=f"set_text_acc_{acc_id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="📋 Посмотреть все", callback_data="view_all_texts")])
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("📝 Выберите аккаунт для настройки текста:", reply_markup=keyboard)
    await callback.answer()

@router_settings.callback_query(F.data.startswith("set_text_acc_"))
async def set_text_account(callback: CallbackQuery, state: FSMContext):
    """Установка текста для аккаунта"""
    account_id = int(callback.data.split("_")[3])
    
    await callback.message.edit_text(
        f"📝 Введите текст приветствия для Аккаунта {account_id}:\n\n"
        "Этот текст будет отправляться каждому новому собеседнику.\n\n"
        "Отменить: /cancel"
    )
    
    await state.update_data(account_id=account_id)
    await state.set_state(TextSettings.ENTER_TEXT)
    await callback.answer()

@router_settings.message(TextSettings.ENTER_TEXT)
async def process_greeting_text(message: Message, state: FSMContext):
    """Обработка текста приветствия"""
    data = await state.get_data()
    account_id = data['account_id']
    greeting_text = message.text
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE accounts SET greeting_text = ? WHERE id = ?
        """, (greeting_text, account_id))
        await db.commit()
    
    await message.answer(f"✅ Текст для Аккаунта {account_id} сохранён!")
    await state.clear()
    await show_main_menu(message)

@router_settings.callback_query(F.data == "view_all_texts")
async def view_all_texts(callback: CallbackQuery):
    """Просмотр всех текстов"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT id, phone, greeting_text FROM accounts ORDER BY id")
        accounts = await cursor.fetchall()
    
    if not accounts:
        await callback.answer("❌ Аккаунты не добавлены", show_alert=True)
        return
    
    text = "📝 ТЕКСТЫ ПРИВЕТСТВИЙ:\n\n"
    for acc_id, phone, greeting in accounts:
        phone_masked = f"{phone[:4]}***{phone[-3:]}"
        text += f"Аккаунт {acc_id} ({phone_masked}):\n"
        text += f"└ {greeting}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="set_texts")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router_settings.callback_query(F.data == "set_cooldowns")
async def set_cooldowns_menu(callback: CallbackQuery):
    """Меню настройки задержек"""
    accounts = await get_accounts_status()
    
    if not accounts:
        await callback.answer("❌ Добавьте аккаунты сначала", show_alert=True)
        return
    
    buttons = []
    for acc_id, phone, _, _ in accounts:
        phone_masked = f"{phone[:4]}***{phone[-3:]}"
        buttons.append([InlineKeyboardButton(
            text=f"Аккаунт {acc_id} ({phone_masked})",
            callback_data=f"set_cooldown_acc_{acc_id}"
        )])
    
    buttons.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text("⏱ Выберите аккаунт для настройки задержек:", reply_markup=keyboard)
    await callback.answer()

@router_settings.callback_query(F.data.startswith("set_cooldown_acc_"))
async def set_cooldown_account(callback: CallbackQuery, state: FSMContext):
    """Установка задержек для аккаунта"""
    account_id = int(callback.data.split("_")[3])
    
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT cooldown_search, cooldown_send, cooldown_skip FROM accounts WHERE id = ?
        """, (account_id,))
        result = await cursor.fetchone()
    
    if not result:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    cd_search, cd_send, cd_skip = result
    
    await callback.message.edit_text(
        f"⏱ Текущие задержки для Аккаунта {account_id}:\n\n"
        f"├ Между поисками: {cd_search} сек\n"
        f"├ Перед отправкой: {cd_send} сек\n"
        f"└ После скипа: {cd_skip} сек\n\n"
        f"Введите новые значения через пробел:\n"
        f"Пример: 25 5 20\n\n"
        f"Отменить: /cancel"
    )
    
    await state.update_data(account_id=account_id)
    await state.set_state(CooldownSettings.ENTER_VALUES)
    await callback.answer()

@router_settings.message(CooldownSettings.ENTER_VALUES)
async def process_cooldown_values(message: Message, state: FSMContext):
    """Обработка значений задержек"""
    data = await state.get_data()
    account_id = data['account_id']
    
    try:
        values = message.text.strip().split()
        if len(values) != 3:
            await message.answer("❌ Нужно ввести 3 числа через пробел. Попробуйте ещё раз:\n\nОтменить: /cancel")
            return
        
        cd_search, cd_send, cd_skip = map(int, values)
        
        if any(v <= 0 for v in [cd_search, cd_send, cd_skip]):
            await message.answer("❌ Все значения должны быть больше нуля. Попробуйте ещё раз:\n\nОтменить: /cancel")
            return
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE accounts 
                SET cooldown_search = ?, cooldown_send = ?, cooldown_skip = ?
                WHERE id = ?
            """, (cd_search, cd_send, cd_skip, account_id))
            await db.commit()
        
        await message.answer(
            f"✅ Задержки для Аккаунта {account_id} сохранены:\n\n"
            f"├ Между поисками: {cd_search} сек\n"
            f"├ Перед отправкой: {cd_send} сек\n"
            f"└ После скипа: {cd_skip} сек"
        )
        await state.clear()
        await show_main_menu(message)
    except ValueError:
        await message.answer("❌ Неверный формат. Введите 3 числа через пробел:\n\nОтменить: /cancel")

# ==================== ОБРАБОТЧИКИ: УПРАВЛЕНИЕ ====================

router_control = Router()

@router_control.callback_query(F.data == "start_all")
async def start_all_accounts(callback: CallbackQuery):
    """Запуск всех аккаунтов"""
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
    await log_to_db(None, "INFO", f"Запущены все аккаунты ({started_count})")
    await callback_main_menu(callback)

@router_control.callback_query(F.data == "pause_all")
async def pause_all_accounts(callback: CallbackQuery):
    """Пауза всех аккаунтов"""
    # TODO: Реализовать паузу (не остановку, а временную приостановку)
    await callback.answer("⏸ Все аккаунты поставлены на паузу", show_alert=True)
    await log_to_db(None, "INFO", "Все аккаунты на паузе")
    await callback_main_menu(callback)

@router_control.callback_query(F.data == "stop_all")
async def stop_all_accounts(callback: CallbackQuery):
    """Остановка всех аккаунтов"""
    await worker_manager.stop_all_workers()
    await callback.answer("⏹ Все аккаунты остановлены", show_alert=True)
    await log_to_db(None, "INFO", "Все аккаунты остановлены")
    await callback_main_menu(callback)

# ==================== ОБРАБОТЧИКИ: СООБЩЕНИЯ ====================

router_messages = Router()

@router_messages.callback_query(F.data == "messages_menu")
async def messages_menu(callback: CallbackQuery):
    """Меню сообщений"""
    text = "📩 ВХОДЯЩИЕ СООБЩЕНИЯ\n\nФункция в разработке..."
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# ==================== ОБРАБОТЧИКИ: СТАТИСТИКА ====================

router_stats = Router()

@router_stats.callback_query(F.data == "stats_menu")
async def stats_menu(callback: CallbackQuery):
    """Меню статистики"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT 
                SUM(total_dialogs),
                SUM(total_skips),
                SUM(total_replies),
                SUM(total_timeouts)
            FROM stats
        """)
        result = await cursor.fetchone()
    
    total_dialogs = result[0] or 0
    total_skips = result[1] or 0
    total_replies = result[2] or 0
    total_timeouts = result[3] or 0
    
    text = "📊 СТАТИСТИКА\n\n"
    text += f"Всего диалогов: {total_dialogs}\n"
    text += f"├ Скипов: {total_skips}\n"
    text += f"├ Ответов: {total_replies}\n"
    text += f"└ Таймаутов: {total_timeouts}\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

# ==================== ОБРАБОТЧИКИ: ЛОГИ ====================

router_logs = Router()

@router_logs.callback_query(F.data == "logs_menu")
async def logs_menu(callback: CallbackQuery):
    """Меню логов"""
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
        [InlineKeyboardButton(text="💾 Скачать все логи", callback_data="download_logs")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await callback.answer()

@router_logs.callback_query(F.data == "download_logs")
async def download_logs(callback: CallbackQuery):
    """Скачать логи"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            SELECT account_id, level, message, timestamp 
            FROM logs 
            ORDER BY timestamp DESC
        """)
        logs = await cursor.fetchall()
    
    if not logs:
        await callback.answer("❌ Логов нет", show_alert=True)
        return
    
    # Создание текстового файла
    log_content = "TELEGRAM AUTOMATION BOT - LOGS\n"
    log_content += "=" * 60 + "\n\n"
    
    for account_id, level, message, timestamp in logs:
        acc_str = f"ACC_{account_id}" if account_id else "SYSTEM"
        log_content += f"[{timestamp}] [{acc_str}] [{level}] {message}\n"
    
    # Сохранение в файл
    log_file_path = "logs/bot_logs.txt"
    os.makedirs('logs', exist_ok=True)
    
    with open(log_file_path, 'w', encoding='utf-8') as f:
        f.write(log_content)
    
    # Отправка файла
    from aiogram.types import FSInputFile
    log_file = FSInputFile(log_file_path)
    
    await callback.message.answer_document(
        log_file,
        caption="📄 Полные логи бота"
    )
    
    await callback.answer("✅ Логи отправлены")

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

async def main():
    """Главная функция"""
    print("=" * 60)
    print("🚀 Запуск Telegram Automation Bot")
    print("=" * 60)
    
    # Инициализация БД
    print("📦 Инициализация базы данных...")
    await init_database(PASSWORD)
    print("=" * 60)
    
    # Создание бота
    bot = Bot(token=TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Регистрация роутеров
    dp.include_router(router_init)
    dp.include_router(router_start)
    dp.include_router(router_accounts)
    dp.include_router(router_settings)
    dp.include_router(router_control)
    dp.include_router(router_messages)
    dp.include_router(router_stats)
    dp.include_router(router_logs)
    
    # Регистрация middleware
    dp.message.middleware(check_authorization_middleware)
    dp.callback_query.middleware(check_authorization_middleware)
    
    # Информация о боте
    bot_info = await bot.get_me()
    print(f"🤖 Бот: @{bot_info.username}")
    print(f"🆔 Bot ID: {bot_info.id}")
    print("=" * 60)
    print("✅ Бот запущен и готов к работе!")
    print("=" * 60)
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\n⚠️  Получен сигнал остановки")
    finally:
        print("\n🛑 Остановка бота...")
        await worker_manager.stop_all_workers()
        await bot.session.close()
        print("✅ Бот остановлен")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До свидания!")