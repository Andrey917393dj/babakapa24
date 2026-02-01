#!/usr/bin/env python3
"""
Telegram Image to Sticker Pack Bot - ИСПРАВЛЕННАЯ ВЕРСИЯ
Полностью рабочий код с правильным API для aiogram 3.x
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
BOT_USERNAME = os.getenv('BOT_USERNAME', 'Crypto_test23_bot')

if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в .env файле!")
    print("📝 Создайте файл .env со строкой:")
    print("   BOT_TOKEN=ваш_токен_от_BotFather")
    sys.exit(1)

if not BOT_USERNAME or BOT_USERNAME == 'myimagebot':
    print("⚠️  ПРЕДУПРЕЖДЕНИЕ: BOT_USERNAME не настроен!")
    print("📝 Добавьте в .env файл:")
    print("   BOT_USERNAME=имя_вашего_бота")
    print("")

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

# ==================== ПРОЦЕССОР ИЗОБРАЖЕНИЙ ====================

class ImageProcessor:
    """Обработка изображений для создания стикеров"""
    
    @staticmethod
    def resize_and_crop(image: Image.Image, grid_cols: int, grid_rows: int) -> Image.Image:
        """Изменить размер и обрезать изображение под сетку"""
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
        """Разрезать изображение на сетку"""
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
        """Конвертировать кусок изображения в формат стикера"""
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
        output.name = 'sticker.png'  # ВАЖНО: добавляем имя файла
        
        return output

# ==================== МЕНЕДЖЕР СТИКЕРПАКОВ ====================

class StickerPackManager:
    """Управление созданием стикерпаков"""
    
    @staticmethod
    def generate_pack_name(user_id: int, bot_username: str) -> str:
        """
        Генерация имени стикерпака по правилам Telegram:
        - Только буквы, цифры и подчёркивания
        - Должно заканчиваться на _by_{bot_username}
        - Длина до 64 символов
        """
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        # Формат: u{user_id}_{timestamp}_by_{bot_username}
        pack_name = f"u{user_id}_{timestamp}_by_{bot_username}"
        
        # Проверка длины (максимум 64 символа)
        if len(pack_name) > 64:
            # Укорачиваем timestamp если имя слишком длинное
            timestamp_short = datetime.now().strftime('%y%m%d%H%M')
            pack_name = f"u{user_id}_{timestamp_short}_by_{bot_username}"
        
        logger.info(f"Сгенерировано имя пака: {pack_name}")
        return pack_name
    
    @staticmethod
    async def create_sticker_pack(
        bot: Bot,
        user_id: int,
        pack_name: str,
        pack_title: str,
        stickers: list[BytesIO],
    ) -> tuple[bool, Optional[str]]:
        """
        Создать стикерпак используя правильный API aiogram 3.x
        
        Returns:
            (success: bool, error_message: Optional[str])
        """
        try:
            # Подготовка первого стикера
            first_sticker_data = stickers[0]
            first_sticker_data.seek(0)
            
            # ИСПРАВЛЕНО: Правильный формат InputSticker для aiogram 3.x
            first_input_sticker = InputSticker(
                sticker=BufferedInputFile(
                    first_sticker_data.read(),
                    filename="sticker.png"
                ),
                emoji_list=["🖼️"],
                format="static"
            )
            
            # Создаём стикерсет
            await bot.create_new_sticker_set(
                user_id=user_id,
                name=pack_name,
                title=pack_title,
                stickers=[first_input_sticker]
            )
            
            logger.info(f"✅ Создан стикерпак: {pack_name}")
            
            # Добавляем остальные стикеры
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
                    
                    # Задержка против rate limits
                    await asyncio.sleep(0.05)
                    
                    logger.info(f"✅ Добавлен стикер {idx}/{len(stickers)}")
                    
                except Exception as e:
                    logger.error(f"⚠️  Ошибка добавления стикера {idx}: {e}")
                    continue
            
            return True, None
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Ошибка создания стикерпака: {error_msg}")
            return False, error_msg

# ==================== КЛАВИАТУРЫ ====================

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Загрузить изображение", callback_data="upload_image")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="show_help")]
    ])

def get_grid_size_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора сетки"""
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
    """Клавиатура отмены"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel")]
    ])

# ==================== РОУТЕР ====================

router = Router()

# ==================== ОБРАБОТЧИКИ ====================

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Команда /start"""
    await state.clear()
    
    welcome_text = """
👋 Добро пожаловать в Image to Sticker Pack Bot!

📸 Я конвертирую ваши изображения в стикерпаки для создания мозаичных эффектов!

💡 Как использовать:
1️⃣ Нажмите "📸 Загрузить изображение"
2️⃣ Отправьте фото или файл
3️⃣ Выберите размер сетки
4️⃣ Получите готовый стикерпак!

✨ Особенности:
• Бесплатно и без ограничений
• 5 размеров сетки (3x4 до 9x11)
• Высокое качество
• Быстрая обработка

🚀 Готовы начать?
"""
    
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard())

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Команда /help"""
    help_text = """
ℹ️ ПОМОЩЬ

📋 Размеры сетки:
• 3x4 = 12 стикеров
• 4x6 = 24 стикера
• 5x8 = 40 стикеров
• 7x9 = 63 стикера
• 9x11 = 99 стикеров

💡 Советы:
• Отправляйте как файл для лучшего качества
• Минимум 512px на меньшей стороне
• Большие изображения дают лучший результат

❓ Команды:
• /start - начать заново
• /cancel - отменить операцию
• /help - эта справка
"""
    
    await message.answer(help_text, reply_markup=get_main_menu_keyboard())

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Команда /cancel"""
    current_state = await state.get_state()
    
    if current_state is None:
        await message.answer("❌ Нечего отменять", reply_markup=get_main_menu_keyboard())
        return
    
    await state.clear()
    await message.answer("✅ Операция отменена", reply_markup=get_main_menu_keyboard())

@router.callback_query(F.data == "upload_image")
async def callback_upload_image(callback: CallbackQuery, state: FSMContext):
    """Начало загрузки"""
    await callback.message.edit_text(
        "📸 Отправьте изображение\n\n"
        "💡 Для лучшего качества отправляйте как файл\n"
        "📏 Минимум: 512px на меньшей стороне",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(ImageProcessing.WAITING_IMAGE)
    await callback.answer()

@router.callback_query(F.data == "show_help")
async def callback_show_help(callback: CallbackQuery):
    """Показать помощь"""
    help_text = """
ℹ️ КАК ИСПОЛЬЗОВАТЬ

1️⃣ Отправьте изображение
2️⃣ Выберите размер сетки
3️⃣ Дождитесь создания пака
4️⃣ Откройте стикерпак

🎨 В чате отправляйте стикеры по порядку:
слева-направо, сверху-вниз

💡 Чем больше сетка = детальнее мозаика!
"""
    
    await callback.message.edit_text(help_text, reply_markup=get_main_menu_keyboard())
    await callback.answer()

@router.callback_query(F.data == "back_to_menu")
async def callback_back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Назад в меню"""
    await state.clear()
    await callback.message.edit_text(
        "📊 Главное меню",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена"""
    await state.clear()
    await callback.message.edit_text(
        "✅ Операция отменена",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("grid_"))
async def callback_grid_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора сетки"""
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
    
    await callback.message.edit_text(
        f"⚙️ Обработка {grid_size} ({cols}x{rows} = {cols*rows} стикеров)...\n\n"
        "⏳ Подождите 1-2 минуты..."
    )
    await callback.answer()
    
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
                    f"❌ Изображение слишком маленькое ({img.width}x{img.height})\n"
                    f"Минимум: 512px на меньшей стороне",
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
        pack_title = f"My {grid_size} Image"
        
        await callback.message.edit_text(
            f"📦 Создание пака с {len(sticker_files)} стикерами...\n"
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
✅ Готово! Стикерпак создан!

🎨 {pack_title}
📊 {grid_size} ({cols*rows} стикеров)

🔗 {pack_url}

💡 Отправляйте стикеры по порядку для создания мозаики!
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Открыть стикерпак", url=pack_url)],
                [InlineKeyboardButton(text="📸 Создать ещё", callback_data="upload_image")],
                [InlineKeyboardButton(text="🔙 Меню", callback_data="back_to_menu")]
            ])
            
            await callback.message.edit_text(result_text, reply_markup=keyboard)
        else:
            error_details = f"\n\n🔍 Детали: {error_msg}" if error_msg else ""
            await callback.message.edit_text(
                f"❌ Не удалось создать стикерпак{error_details}\n\n"
                "💡 Попробуйте:\n"
                "• Проверить BOT_USERNAME в .env\n"
                "• Использовать другое изображение\n"
                "• Попробовать меньшую сетку",
                reply_markup=get_main_menu_keyboard()
            )
        
        await state.clear()
    
    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ Ошибка обработки:\n{str(e)[:200]}",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
    
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Ошибка очистки: {e}")

@router.message(ImageProcessing.WAITING_IMAGE, F.photo | F.document)
async def handle_image(message: Message, state: FSMContext):
    """Обработка изображения"""
    if message.photo:
        file_id = message.photo[-1].file_id
        await message.answer(
            "📸 Фото получено!\n\n"
            "💡 В следующий раз отправьте как файл для лучшего качества\n\n"
            "⏳ Готовлю опции..."
        )
    elif message.document:
        document = message.document
        if not document.mime_type or not document.mime_type.startswith('image/'):
            await message.answer(
                "❌ Отправьте файл изображения (JPG, PNG)",
                reply_markup=get_cancel_keyboard()
            )
            return
        file_id = document.file_id
        await message.answer("📁 Файл получен!\n⏳ Готовлю опции...")
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
    """Неправильный контент"""
    await message.answer(
        "❌ Отправьте изображение (фото или файл)",
        reply_markup=get_cancel_keyboard()
    )

@router.message()
async def handle_any_message(message: Message):
    """Любое другое сообщение"""
    await message.answer(
        "👋 Используйте /start",
        reply_markup=get_main_menu_keyboard()
    )

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

async def main():
    """Запуск бота"""
    print("=" * 60)
    print("🚀 Image to Sticker Pack Bot")
    print("=" * 60)
    
    os.makedirs('logs', exist_ok=True)
    
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    dp.include_router(router)
    
    bot_info = await bot.get_me()
    print(f"🤖 Бот: @{bot_info.username}")
    print(f"🆔 ID: {bot_info.id}")
    print(f"📝 Username для паков: {BOT_USERNAME}")
    print("=" * 60)
    print("✅ Бот запущен!")
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