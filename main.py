#!/usr/bin/env python3
"""
Telegram Image to Sticker Pack Bot - ФИНАЛЬНАЯ ВЕРСИЯ
С поддержкой пользовательских названий стикерпаков
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
    print("📝 Создайте файл .env со строкой:")
    print("   BOT_TOKEN=ваш_токен_от_BotFather")
    sys.exit(1)

# BOT_USERNAME будет получен автоматически при запуске
BOT_USERNAME = None

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
STICKER_SIZE = 512
GRID_SIZES = {
    '3x4': (3, 4),
    '4x6': (4, 6),
    '5x8': (5, 8),
    '7x9': (7, 9),
    '9x11': (9, 11),
}

# ==================== FSM СОСТОЯНИЯ ====================

class ImageProcessing(StatesGroup):
    WAITING_IMAGE = State()
    SELECTING_GRID = State()
    ENTERING_PACK_NAME = State()

# ==================== ПРОЦЕССОР ИЗОБРАЖЕНИЙ ====================

class ImageProcessor:
    """Обработка изображений"""
    
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
        
        final_width = grid_cols * STICKER_SIZE
        final_height = grid_rows * STICKER_SIZE
        
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
    def prepare_sticker(image: Image.Image) -> BytesIO:
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        width, height = image.size
        if width > height:
            new_width = STICKER_SIZE
            new_height = int(height * (STICKER_SIZE / width))
        else:
            new_height = STICKER_SIZE
            new_width = int(width * (STICKER_SIZE / height))
        
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        output = BytesIO()
        image.save(output, format='PNG', optimize=True)
        output.seek(0)
        output.name = 'sticker.png'
        
        return output

# ==================== МЕНЕДЖЕР СТИКЕРПАКОВ ====================

class StickerPackManager:
    """Управление стикерпаками"""
    
    @staticmethod
    def generate_pack_name(user_id: int, bot_username: str) -> str:
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        pack_name = f"u{user_id}_{timestamp}_by_{bot_username}"
        
        if len(pack_name) > 64:
            timestamp_short = datetime.now().strftime('%y%m%d%H%M')
            pack_name = f"u{user_id}_{timestamp_short}_by_{bot_username}"
        
        logger.info(f"Имя пака: {pack_name}")
        return pack_name
    
    @staticmethod
    async def create_sticker_pack(
        bot: Bot,
        user_id: int,
        pack_name: str,
        pack_title: str,
        stickers: list[BytesIO],
    ) -> tuple[bool, Optional[str]]:
        try:
            first_sticker_data = stickers[0]
            first_sticker_data.seek(0)
            
            first_input_sticker = InputSticker(
                sticker=BufferedInputFile(
                    first_sticker_data.read(),
                    filename="sticker.png"
                ),
                emoji_list=["🖼️"],
                format="static"
            )
            
            await bot.create_new_sticker_set(
                user_id=user_id,
                name=pack_name,
                title=pack_title,
                stickers=[first_input_sticker]
            )
            
            logger.info(f"✅ Создан: {pack_name}")
            
            for idx, sticker_data in enumerate(stickers[1:], start=2):
                try:
                    sticker_data.seek(0)
                    
                    input_sticker = InputSticker(
                        sticker=BufferedInputFile(
                            sticker_data.read(),
                            filename=f"sticker_{idx}.png"
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
                    logger.info(f"✅ Стикер {idx}/{len(stickers)}")
                    
                except Exception as e:
                    logger.error(f"⚠️  Ошибка стикера {idx}: {e}")
                    continue
            
            return True, None
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Ошибка пака: {error_msg}")
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
        total_stickers = cols * rows
        button = InlineKeyboardButton(
            text=f"{size_label} ({total_stickers} стикеров)",
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

# ==================== ОБРАБОТЧИКИ ====================

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    
    welcome_text = """
👋 Добро пожаловать!

📸 Я конвертирую изображения в стикерпаки для мозаичных эффектов!

💡 Как использовать:
1️⃣ Загрузите изображение
2️⃣ Выберите размер сетки
3️⃣ Задайте название пака
4️⃣ Получите готовый стикерпак!

🚀 Готовы?
"""
    
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard())

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
ℹ️ ПОМОЩЬ

📋 Размеры сетки:
• 3x4 = 12 стикеров
• 4x6 = 24 стикера
• 5x8 = 40 стикеров
• 7x9 = 63 стикера
• 9x11 = 99 стикеров

💡 Советы:
• Отправляйте как файл
• Минимум 512px
• Добавьте размер в название пака

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

@router.callback_query(F.data == "upload_image")
async def callback_upload_image(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "📸 Отправьте изображение\n\n"
        "💡 Для лучшего качества — как файл\n"
        "📏 Минимум: 512px",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(ImageProcessing.WAITING_IMAGE)
    await callback.answer()

@router.callback_query(F.data == "show_help")
async def callback_show_help(callback: CallbackQuery):
    help_text = """
ℹ️ КАК ИСПОЛЬЗОВАТЬ

1️⃣ Отправьте изображение
2️⃣ Выберите сетку
3️⃣ Задайте название
4️⃣ Откройте стикерпак

🎨 Отправляйте стикеры по порядку:
слева-направо, сверху-вниз
"""
    
    await callback.message.edit_text(help_text, reply_markup=get_main_menu_keyboard())
    await callback.answer()

@router.callback_query(F.data == "back_to_menu")
async def callback_back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "📊 Главное меню",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "✅ Отменено",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("grid_"))
async def callback_grid_selection(callback: CallbackQuery, state: FSMContext):
    """Выбор сетки → запрос названия"""
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
    
    # Сохраняем параметры сетки
    await state.update_data(grid_size=grid_size, grid_cols=cols, grid_rows=rows)
    
    # Запрашиваем название
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
    """Использовать стандартное название"""
    grid_size = callback.data.replace('default_name_', '')
    
    await state.update_data(pack_title=grid_size)
    await callback.answer("✅ Стандартное название")
    
    # Запускаем обработку
    await process_image_and_create_pack(callback, state)

@router.callback_query(F.data == "back_to_grid")
async def callback_back_to_grid(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору сетки"""
    await callback.message.edit_text(
        "🎯 Выберите размер сетки:",
        reply_markup=get_grid_size_keyboard()
    )
    await state.set_state(ImageProcessing.SELECTING_GRID)
    await callback.answer()

@router.message(ImageProcessing.ENTERING_PACK_NAME, F.text)
async def handle_pack_name_input(message: Message, state: FSMContext):
    """Обработка введённого названия"""
    pack_title = message.text.strip()
    
    # Проверка длины
    if len(pack_title) > 15:
        await message.answer(
            f"❌ Слишком длинное ({len(pack_title)} символов)\n"
            "Максимум 15. Попробуйте ещё:"
        )
        return
    
    if len(pack_title) < 1:
        await message.answer("❌ Не может быть пустым:")
        return
    
    # Сохраняем
    await state.update_data(pack_title=pack_title)
    
    processing_msg = await message.answer(
        f"⚙️ Обработка...\n"
        f"📝 {pack_title}\n\n"
        "⏳ Подождите 1-2 минуты..."
    )
    
    # Создаём обёртку для переиспользования функции
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
    """Основная обработка и создание пака"""
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
        # Скачиваем
        file = await callback.bot.get_file(file_id)
        image_path = os.path.join(temp_dir, 'original.jpg')
        await callback.bot.download_file(file.file_path, image_path)
        
        # Обрабатываем
        with Image.open(image_path) as img:
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            
            min_dimension = min(img.width, img.height)
            if min_dimension < 512:
                await callback.message.edit_text(
                    f"❌ Слишком маленькое ({img.width}x{img.height})\n"
                    f"Минимум: 512px",
                    reply_markup=get_main_menu_keyboard()
                )
                await state.clear()
                return
            
            processor = ImageProcessor()
            processed_img = processor.resize_and_crop(img, cols, rows)
            slices = processor.slice_image(processed_img, cols, rows)
            
            sticker_files = []
            for slice_img in slices:
                sticker_data = processor.prepare_sticker(slice_img)
                sticker_files.append(sticker_data)
            
            logger.info(f"Создано {len(sticker_files)} стикеров")
        
        # Создаём пак
        pack_manager = StickerPackManager()
        pack_name = pack_manager.generate_pack_name(callback.from_user.id, BOT_USERNAME)
        
        await callback.message.edit_text(
            f"📦 Создание с {len(sticker_files)} стикерами...\n"
            f"📝 {pack_title}\n\n"
            "⏳ Ещё минуту..."
        )
        
        success, error_msg = await pack_manager.create_sticker_pack(
            bot=callback.bot,
            user_id=callback.from_user.id,
            pack_name=pack_name,
            pack_title=pack_title,
            stickers=sticker_files,
        )
        
        if success:
            pack_url = f"https://t.me/addstickers/{pack_name}"
            
            result_text = f"""
✅ Готово!

🎨 {pack_title}
📊 {grid_size} ({cols*rows} стикеров)

🔗 {pack_url}

💡 Отправляйте стикеры по порядку (слева-направо, сверху-вниз)!
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Открыть", url=pack_url)],
                [InlineKeyboardButton(text="📸 Ещё", callback_data="upload_image")],
                [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")]
            ])
            
            await callback.message.edit_text(result_text, reply_markup=keyboard)
        else:
            error_details = f"\n\n🔍 {error_msg}" if error_msg else ""
            await callback.message.edit_text(
                f"❌ Не удалось создать{error_details}\n\n"
                "💡 Попробуйте:\n"
                "• Другое изображение\n"
                "• Меньшую сетку",
                reply_markup=get_main_menu_keyboard()
            )
        
        await state.clear()
    
    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ Ошибка:\n{str(e)[:200]}",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
    
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Очистка: {e}")

@router.message(ImageProcessing.WAITING_IMAGE, F.photo | F.document)
async def handle_image(message: Message, state: FSMContext):
    """Обработка изображения"""
    if message.photo:
        file_id = message.photo[-1].file_id
        await message.answer(
            "📸 Получено!\n"
            "💡 В следующий раз — как файл\n"
            "⏳ Готовлю опции..."
        )
    elif message.document:
        document = message.document
        if not document.mime_type or not document.mime_type.startswith('image/'):
            await message.answer(
                "❌ Отправьте изображение",
                reply_markup=get_cancel_keyboard()
            )
            return
        file_id = document.file_id
        await message.answer("📁 Файл получен!\n⏳ Готовлю...")
    else:
        await message.answer(
            "❌ Отправьте изображение",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await state.update_data(image_file_id=file_id)
    
    await message.answer(
        "🎯 Выберите размер сетки:",
        reply_markup=get_grid_size_keyboard()
    )
    
    await state.set_state(ImageProcessing.SELECTING_GRID)

@router.message(ImageProcessing.WAITING_IMAGE)
async def handle_wrong_content(message: Message):
    await message.answer(
        "❌ Отправьте изображение",
        reply_markup=get_cancel_keyboard()
    )

@router.message()
async def handle_any_message(message: Message):
    await message.answer(
        "👋 Используйте /start",
        reply_markup=get_main_menu_keyboard()
    )

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

async def main():
    """Запуск бота"""
    global BOT_USERNAME
    
    print("=" * 60)
    print("🚀 Image to Sticker Pack Bot")
    print("=" * 60)
    
    os.makedirs('logs', exist_ok=True)
    
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    dp.include_router(router)
    
    # Получаем username автоматически
    bot_info = await bot.get_me()
    BOT_USERNAME = bot_info.username
    
    print(f"🤖 Бот: @{bot_info.username}")
    print(f"🆔 ID: {bot_info.id}")
    print(f"📝 Username: {BOT_USERNAME}")
    print("=" * 60)
    print("✅ Запущен!")
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
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)