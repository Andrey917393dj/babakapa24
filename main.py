#!/usr/bin/env python3
"""
Telegram Image to Custom Emoji Pack Bot
Создаёт ЭМОДЗИ паки вместо обычных стикеров
"""

import asyncio
import os
import sys
import logging
from datetime import datetime
from typing import Optional
from io import BytesIO
import tempfile
import shutil

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message, 
    CallbackQuery, 
    InlineKeyboardMarkup, 
    InlineKeyboardButton,
    BufferedInputFile,
    InputSticker
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from PIL import Image

# ==================== КОНФИГУРАЦИЯ ====================

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в .env файле!")
    sys.exit(1)

BOT_USERNAME = None

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы для ЭМОДЗИ (требования другие!)
EMOJI_SIZE = 100  # Custom emoji должны быть 100x100
GRID_SIZES = {
    '3x4': (3, 4),
    '4x6': (4, 6),
    '5x8': (5, 8),
    '7x9': (7, 9),
    '9x11': (9, 11),
}

# ==================== FSM ====================

class ImageProcessing(StatesGroup):
    WAITING_IMAGE = State()
    SELECTING_GRID = State()
    ENTERING_PACK_NAME = State()

# ==================== ПРОЦЕССОР ====================

class ImageProcessor:
    """Обработка изображений для Custom Emoji"""
    
    @staticmethod
    def resize_and_crop(image: Image.Image, grid_cols: int, grid_rows: int) -> Image.Image:
        target_ratio = grid_cols / grid_rows
        current_ratio = image.width / image.height
        
        if current_ratio > target_ratio:
            new_height = image.height
            new_width = int(new_height * target_ratio)
        else:
            new_width = image.width
            new_height = int(new_width / target_ratio)
        
        left = (image.width - new_width) // 2
        top = (image.height - new_height) // 2
        right = left + new_width
        bottom = top + new_height
        
        cropped = image.crop((left, top, right, bottom))
        
        # Для Custom Emoji используем 100x100 на каждый элемент
        final_width = grid_cols * EMOJI_SIZE
        final_height = grid_rows * EMOJI_SIZE
        
        resized = cropped.resize((final_width, final_height), Image.Resampling.LANCZOS)
        
        return resized
    
    @staticmethod
    def slice_image(image: Image.Image, grid_cols: int, grid_rows: int) -> list[Image.Image]:
        slice_width = image.width // grid_cols
        slice_height = image.height // grid_rows
        
        slices = []
        
        for row in range(grid_rows):
            for col in range(grid_cols):
                left = col * slice_width
                top = row * slice_height
                right = left + slice_width
                bottom = top + slice_height
                
                slice_img = image.crop((left, top, right, bottom))
                slices.append(slice_img)
        
        return slices
    
    @staticmethod
    def prepare_emoji(image: Image.Image) -> BytesIO:
        """
        ВАЖНО: Custom Emoji требования:
        - Формат: PNG с прозрачностью
        - Размер: ТОЧНО 100x100 пикселей
        - Максимум 50KB
        """
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # Custom Emoji ДОЛЖНЫ быть ровно 100x100
        image = image.resize((EMOJI_SIZE, EMOJI_SIZE), Image.Resampling.LANCZOS)
        
        output = BytesIO()
        image.save(output, format='PNG', optimize=True)
        output.seek(0)
        output.name = 'emoji.png'
        
        return output

# ==================== МЕНЕДЖЕР ПАКОВ ====================

class EmojiPackManager:
    """Управление Custom Emoji паками"""
    
    @staticmethod
    def generate_pack_name(user_id: int, bot_username: str) -> str:
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        pack_name = f"u{user_id}_{timestamp}_by_{bot_username}"
        
        if len(pack_name) > 64:
            timestamp_short = datetime.now().strftime('%y%m%d%H%M')
            pack_name = f"u{user_id}_{timestamp_short}_by_{bot_username}"
        
        logger.info(f"📝 Имя пака: {pack_name}")
        return pack_name
    
    @staticmethod
    async def create_emoji_pack(
        bot: Bot,
        user_id: int,
        pack_name: str,
        pack_title: str,
        emojis: list[BytesIO],
    ) -> tuple[bool, Optional[str]]:
        """
        ВАЖНО: Создание Custom Emoji пака
        
        API: createNewStickerSet с sticker_type="custom_emoji"
        Требование: У пользователя ДОЛЖЕН быть Telegram Premium!
        """
        try:
            logger.info(f"🎨 Создаю Custom Emoji пак для user {user_id}")
            
            first_emoji_data = emojis[0]
            first_emoji_data.seek(0)
            
            # КЛЮЧЕВОЕ ОТЛИЧИЕ: sticker_type="custom_emoji"
            first_input_sticker = InputSticker(
                sticker=BufferedInputFile(
                    first_emoji_data.read(),
                    filename="emoji.png"
                ),
                emoji_list=["🖼️"],
                format="static"
            )
            
            # Создаём Custom Emoji набор
            await bot.create_new_sticker_set(
                user_id=user_id,
                name=pack_name,
                title=pack_title,
                stickers=[first_input_sticker],
                sticker_type="custom_emoji"  # ← ЭТО ГЛАВНОЕ!
            )
            
            logger.info(f"✅ Custom Emoji пак создан: {pack_name}")
            
            # Добавляем остальные эмодзи
            for idx, emoji_data in enumerate(emojis[1:], start=2):
                try:
                    emoji_data.seek(0)
                    
                    input_sticker = InputSticker(
                        sticker=BufferedInputFile(
                            emoji_data.read(),
                            filename=f"emoji_{idx}.png"
                        ),
                        emoji_list=["🖼️"],
                        format="static"
                    )
                    
                    await bot.add_sticker_to_set(
                        user_id=user_id,
                        name=pack_name,
                        sticker=input_sticker
                    )
                    
                    await asyncio.sleep(0.05)
                    logger.info(f"✅ Эмодзи {idx}/{len(emojis)}")
                    
                except Exception as e:
                    logger.error(f"⚠️  Ошибка эмодзи {idx}: {e}")
                    continue
            
            logger.info(f"🎉 Пак завершён: {len(emojis)} эмодзи")
            return True, None
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Ошибка создания: {error_msg}")
            
            # Проверка на отсутствие Premium
            if "PREMIUM_ACCOUNT_REQUIRED" in error_msg or "premium" in error_msg.lower():
                return False, "Для Custom Emoji нужен Telegram Premium"
            
            return False, error_msg

# ==================== КЛАВИАТУРЫ ====================

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Загрузить изображение", callback_data="upload_image")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="show_help")]
    ])

def get_grid_size_keyboard() -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    
    for size_label, (cols, rows) in GRID_SIZES.items():
        total = cols * rows
        button = InlineKeyboardButton(
            text=f"{size_label} ({total} эмодзи)",
            callback_data=f"grid_{size_label}"
        )
        row.append(button)
        
        if len(row) == 2:
            keyboard.append(row)
            row = []
    
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel")]
    ])

# ==================== РОУТЕР ====================

router = Router()

# ==================== КОМАНДЫ ====================

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    
    welcome_text = """
👋 Добро пожаловать!

🎨 Я конвертирую изображения в **Custom Emoji** паки!

⚠️ **ВАЖНО**: Нужен Telegram Premium для создания Custom Emoji!

💡 Как использовать:
1️⃣ Загрузите изображение
2️⃣ Выберите размер сетки
3️⃣ Задайте название
4️⃣ Получите эмодзи-пак!

🚀 Готовы?
"""
    
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard())

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
ℹ️ ПОМОЩЬ

📋 Размеры сетки:
• 3x4 = 12 эмодзи
• 4x6 = 24 эмодзи
• 5x8 = 40 эмодзи
• 7x9 = 63 эмодзи
• 9x11 = 99 эмодзи

⚠️ Требования:
• Telegram Premium (обязательно!)
• Изображение минимум 300x300px

💡 Что такое Custom Emoji?
Это НЕ стикеры! Это специальные эмодзи которые можно использовать в тексте сообщений.

❓ Команды:
/start /cancel /help
"""
    
    await message.answer(help_text, reply_markup=get_main_menu_keyboard())

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("❌ Нечего отменять", reply_markup=get_main_menu_keyboard())
        return
    await state.clear()
    await message.answer("✅ Отменено", reply_markup=get_main_menu_keyboard())

# ==================== CALLBACKS ====================

@router.callback_query(F.data == "upload_image")
async def callback_upload_image(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📸 Отправьте изображение\n\n"
        "💡 Для лучшего качества — как файл\n"
        "📏 Минимум: 300x300px",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(ImageProcessing.WAITING_IMAGE)
    await callback.answer()

@router.callback_query(F.data == "show_help")
async def callback_show_help(callback: CallbackQuery):
    await cmd_help(callback.message)
    await callback.answer()

@router.callback_query(F.data == "back_to_menu")
async def callback_back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("📊 Главное меню", reply_markup=get_main_menu_keyboard())
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("✅ Отменено", reply_markup=get_main_menu_keyboard())
    await callback.answer()

@router.callback_query(F.data.startswith("grid_"))
async def callback_grid_selection(callback: CallbackQuery, state: FSMContext):
    grid_size = callback.data.replace('grid_', '')
    
    if grid_size not in GRID_SIZES:
        await callback.answer("❌ Неверный размер", show_alert=True)
        return
    
    cols, rows = GRID_SIZES[grid_size]
    data = await state.get_data()
    file_id = data.get('image_file_id')
    
    if not file_id:
        await callback.message.edit_text(
            "❌ Данные потеряны. Отправьте изображение снова.",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
        return
    
    await state.update_data(grid_size=grid_size, grid_cols=cols, grid_rows=rows)
    
    text = f"""
✅ Выбрана сетка: {grid_size}

📝 Введите название пака (до 15 символов):
Или нажмите кнопку для стандартного названия с размером сетки — {grid_size}

💡 Совет — если вы хотите, чтобы паком пользовались другие люди, добавьте в название размер сетки, например 3x5. Так люди смогут понять, как именно надо собирать картинку, сколько эмодзи должно быть в ряду.
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📝 Стандартное название", callback_data=f"default_name_{grid_size}")],
        [InlineKeyboardButton(text="🔙 Изменить сетку", callback_data="back_to_grid")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard)
    await state.set_state(ImageProcessing.ENTERING_PACK_NAME)
    await callback.answer()

@router.callback_query(F.data.startswith("default_name_"))
async def callback_default_name(callback: CallbackQuery, state: FSMContext):
    grid_size = callback.data.replace('default_name_', '')
    await state.update_data(pack_title=grid_size)
    await callback.answer("✅ Стандартное название")
    await process_image_and_create_pack(callback, state)

@router.callback_query(F.data == "back_to_grid")
async def callback_back_to_grid(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🎯 Выберите размер сетки:",
        reply_markup=get_grid_size_keyboard()
    )
    await state.set_state(ImageProcessing.SELECTING_GRID)
    await callback.answer()

@router.message(ImageProcessing.ENTERING_PACK_NAME, F.text)
async def handle_pack_name_input(message: Message, state: FSMContext):
    pack_title = message.text.strip()
    
    if len(pack_title) > 15:
        await message.answer(f"❌ Слишком длинное ({len(pack_title)} символов)\nМаксимум 15:")
        return
    
    if len(pack_title) < 1:
        await message.answer("❌ Не может быть пустым:")
        return
    
    await state.update_data(pack_title=pack_title)
    
    processing_msg = await message.answer(
        f"⚙️ Обработка...\n"
        f"📝 {pack_title}\n\n"
        "⏳ Подождите 1-2 минуты..."
    )
    
    class CallbackWrapper:
        def __init__(self, msg, bot, user):
            self.message = msg
            self.bot = bot
            self.from_user = user
        async def answer(self, text="", show_alert=False):
            pass
    
    wrapper = CallbackWrapper(processing_msg, message.bot, message.from_user)
    await process_image_and_create_pack(wrapper, state)

async def process_image_and_create_pack(callback, state: FSMContext):
    """Обработка и создание Custom Emoji пака"""
    data = await state.get_data()
    
    file_id = data.get('image_file_id')
    grid_size = data.get('grid_size')
    cols = data.get('grid_cols')
    rows = data.get('grid_rows')
    pack_title = data.get('pack_title', grid_size)
    
    if not all([file_id, grid_size, cols, rows]):
        await callback.message.edit_text(
            "❌ Данные потеряны. Начните заново.",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
        return
    
    temp_dir = tempfile.mkdtemp()
    
    try:
        logger.info(f"📥 Скачиваю изображение...")
        file = await callback.bot.get_file(file_id)
        image_path = os.path.join(temp_dir, 'original.jpg')
        await callback.bot.download_file(file.file_path, image_path)
        
        logger.info(f"🖼️  Обрабатываю изображение...")
        with Image.open(image_path) as img:
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            
            min_dimension = min(img.width, img.height)
            if min_dimension < 300:
                await callback.message.edit_text(
                    f"❌ Слишком маленькое ({img.width}x{img.height})\n"
                    f"Минимум: 300x300px",
                    reply_markup=get_main_menu_keyboard()
                )
                await state.clear()
                return
            
            processor = ImageProcessor()
            processed_img = processor.resize_and_crop(img, cols, rows)
            slices = processor.slice_image(processed_img, cols, rows)
            
            emoji_files = []
            for slice_img in slices:
                emoji_data = processor.prepare_emoji(slice_img)
                emoji_files.append(emoji_data)
            
            logger.info(f"✅ Создано {len(emoji_files)} эмодзи")
        
        logger.info(f"📦 Создаю Custom Emoji пак...")
        pack_manager = EmojiPackManager()
        pack_name = pack_manager.generate_pack_name(callback.from_user.id, BOT_USERNAME)
        
        await callback.message.edit_text(
            f"📦 Создание Custom Emoji пака...\n"
            f"📝 {pack_title}\n"
            f"🎨 {len(emoji_files)} эмодзи\n\n"
            "⏳ Ещё минуту..."
        )
        
        success, error_msg = await pack_manager.create_emoji_pack(
            bot=callback.bot,
            user_id=callback.from_user.id,
            pack_name=pack_name,
            pack_title=pack_title,
            emojis=emoji_files,
        )
        
        if success:
            pack_url = f"https://t.me/addemoji/{pack_name}"
            
            result_text = f"""
✅ Готово! Эмодзи-пак создан!

🎨 {pack_title}
📊 {grid_size} ({cols*rows} эмодзи)

🔗 {pack_url}

💡 Нажмите на ссылку чтобы добавить эмодзи!
Используйте их в любом чате как обычные эмодзи.

📝 Отправляйте по порядку (слева-направо, сверху-вниз) для создания мозаики!
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Открыть эмодзи-пак", url=pack_url)],
                [InlineKeyboardButton(text="📸 Создать ещё", callback_data="upload_image")],
                [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")]
            ])
            
            await callback.message.edit_text(result_text, reply_markup=keyboard)
            logger.info(f"🎉 Пак успешно создан и отправлен!")
        else:
            error_details = f"\n\n🔍 {error_msg}" if error_msg else ""
            await callback.message.edit_text(
                f"❌ Не удалось создать{error_details}\n\n"
                "💡 Возможные причины:\n"
                "• Нет Telegram Premium\n"
                "• Слишком большое изображение\n"
                "• Попробуйте меньшую сетку",
                reply_markup=get_main_menu_keyboard()
            )
            logger.error(f"❌ Создание не удалось: {error_msg}")
        
        await state.clear()
    
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ Ошибка:\n{str(e)[:200]}",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
    
    finally:
        try:
            shutil.rmtree(temp_dir)
            logger.info(f"🧹 Очищено: {temp_dir}")
        except Exception as e:
            logger.error(f"⚠️  Очистка: {e}")

@router.message(ImageProcessing.WAITING_IMAGE, F.photo | F.document)
async def handle_image(message: Message, state: FSMContext):
    if message.photo:
        file_id = message.photo[-1].file_id
        await message.answer("📸 Получено!\n💡 В следующий раз — как файл\n⏳ Готовлю...")
    elif message.document:
        document = message.document
        if not document.mime_type or not document.mime_type.startswith('image/'):
            await message.answer("❌ Отправьте изображение", reply_markup=get_cancel_keyboard())
            return
        file_id = document.file_id
        await message.answer("📁 Файл получен!\n⏳ Готовлю...")
    else:
        await message.answer("❌ Отправьте изображение", reply_markup=get_cancel_keyboard())
        return
    
    await state.update_data(image_file_id=file_id)
    await message.answer("🎯 Выберите размер сетки:", reply_markup=get_grid_size_keyboard())
    await state.set_state(ImageProcessing.SELECTING_GRID)

@router.message(ImageProcessing.WAITING_IMAGE)
async def handle_wrong_content(message: Message):
    await message.answer("❌ Отправьте изображение", reply_markup=get_cancel_keyboard())

@router.message()
async def handle_any_message(message: Message):
    await message.answer("👋 Используйте /start", reply_markup=get_main_menu_keyboard())

# ==================== MAIN ====================

async def main():
    global BOT_USERNAME
    
    print("=" * 60)
    print("🎨 Custom Emoji Pack Bot")
    print("=" * 60)
    
    os.makedirs('logs', exist_ok=True)
    
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    dp.include_router(router)
    
    bot_info = await bot.get_me()
    BOT_USERNAME = bot_info.username
    
    print(f"🤖 Бот: @{bot_info.username}")
    print(f"🆔 ID: {bot_info.id}")
    print(f"📝 Username: {BOT_USERNAME}")
    print(f"🎨 Тип: Custom Emoji (НЕ стикеры!)")
    print("=" * 60)
    print("✅ Запущен!")
    print("⚠️  Требуется Telegram Premium у пользователей!")
    print("💡 Ctrl+C для остановки")
    print("=" * 60)
    
    try:
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except KeyboardInterrupt:
        print("\n⚠️  Остановка...")
    finally:
        await bot.session.close()
        print("✅ Остановлен")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До свидания!")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)