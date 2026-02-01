#!/usr/bin/env python3
"""
Telegram Image to Sticker Pack Bot
Полностью рабочий код для конвертации изображений в стикерпаки
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
    BufferedInputFile
)
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from PIL import Image

# ==================== КОНФИГУРАЦИЯ ====================

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
BOT_USERNAME = os.getenv('BOT_USERNAME', 'myimagebot')

if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не найден в .env файле!")
    print("📝 Создайте файл .env со строкой:")
    print("   BOT_TOKEN=ваш_токен_от_BotFather")
    sys.exit(1)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы
STICKER_SIZE = 512  # Один размер должен быть 512px для Telegram
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
        """
        Изменить размер и обрезать изображение под сетку
        
        Args:
            image: PIL Image объект
            grid_cols: Количество колонок
            grid_rows: Количество строк
            
        Returns:
            Обработанное изображение
        """
        # Целевое соотношение сторон
        target_ratio = grid_cols / grid_rows
        current_ratio = image.width / image.height
        
        # Определяем новые размеры
        if current_ratio > target_ratio:
            # Изображение шире - обрезаем ширину
            new_height = image.height
            new_width = int(new_height * target_ratio)
        else:
            # Изображение выше - обрезаем высоту
            new_width = image.width
            new_height = int(new_width / target_ratio)
        
        # Центральная обрезка
        left = (image.width - new_width) // 2
        top = (image.height - new_height) // 2
        right = left + new_width
        bottom = top + new_height
        
        cropped = image.crop((left, top, right, bottom))
        
        # Ресайз для высокого качества (каждый стикер будет 512px)
        final_width = grid_cols * STICKER_SIZE
        final_height = grid_rows * STICKER_SIZE
        
        resized = cropped.resize((final_width, final_height), Image.Resampling.LANCZOS)
        
        return resized
    
    @staticmethod
    def slice_image(image: Image.Image, grid_cols: int, grid_rows: int) -> list[Image.Image]:
        """
        Разрезать изображение на сетку
        
        Args:
            image: PIL Image для разрезки
            grid_cols: Количество колонок
            grid_rows: Количество строк
            
        Returns:
            Список PIL Image объектов (слева-направо, сверху-вниз)
        """
        slice_width = image.width // grid_cols
        slice_height = image.height // grid_rows
        
        slices = []
        
        # Итерация строка за строкой, слева направо
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
        """
        Конвертировать кусок изображения в формат стикера Telegram
        
        Args:
            image: PIL Image объект
            
        Returns:
            BytesIO объект с PNG данными
        """
        # Конвертация в RGBA для PNG с прозрачностью
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # Ресайз до 512px на длинной стороне (должно быть уже 512x512)
        width, height = image.size
        if width > height:
            new_width = STICKER_SIZE
            new_height = int(height * (STICKER_SIZE / width))
        else:
            new_height = STICKER_SIZE
            new_width = int(width * (STICKER_SIZE / height))
        
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # Сохранение в BytesIO как PNG
        output = BytesIO()
        image.save(output, format='PNG', optimize=True)
        output.seek(0)
        
        return output

# ==================== МЕНЕДЖЕР СТИКЕРПАКОВ ====================

class StickerPackManager:
    """Управление созданием стикерпаков Telegram"""
    
    @staticmethod
    def generate_pack_name(user_id: int) -> str:
        """
        Генерация уникального имени стикерпака
        
        Args:
            user_id: Telegram ID пользователя
            
        Returns:
            Уникальное имя пака
        """
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        return f"u{user_id}_{timestamp}_by_{BOT_USERNAME}"
    
    @staticmethod
    async def create_sticker_pack(
        bot: Bot,
        user_id: int,
        pack_name: str,
        pack_title: str,
        stickers: list[BytesIO],
    ) -> bool:
        """
        Создать новый стикерпак со всеми стикерами
        
        Процесс:
        1. Создаём пак с первым стикером
        2. Добавляем остальные стикеры по одному
        3. Обрабатываем rate limits и ошибки
        
        Args:
            bot: Telegram Bot объект
            user_id: ID пользователя
            pack_name: Уникальное имя пака
            pack_title: Читаемое название
            stickers: Список BytesIO объектов с PNG данными
            
        Returns:
            True если успешно, False иначе
        """
        try:
            # Шаг 1: Создаём стикерсет с первым стикером
            first_sticker_data = stickers[0]
            first_sticker_data.seek(0)
            
            first_sticker = BufferedInputFile(
                first_sticker_data.read(),
                filename="sticker.png"
            )
            
            await bot.create_new_sticker_set(
                user_id=user_id,
                name=pack_name,
                title=pack_title,
                stickers=[{
                    'sticker': first_sticker,
                    'emoji_list': ['🖼️'],
                    'format': 'static'
                }]
            )
            
            logger.info(f"Создан стикерпак: {pack_name}")
            
            # Шаг 2: Добавляем остальные стикеры по одному
            # ВАЖНО: У Telegram есть rate limits, поэтому добавляем задержку
            for idx, sticker_data in enumerate(stickers[1:], start=2):
                try:
                    # Сброс указателя файла
                    sticker_data.seek(0)
                    
                    sticker = BufferedInputFile(
                        sticker_data.read(),
                        filename=f"sticker_{idx}.png"
                    )
                    
                    await bot.add_sticker_to_set(
                        user_id=user_id,
                        name=pack_name,
                        sticker={
                            'sticker': sticker,
                            'emoji_list': ['🖼️'],
                            'format': 'static'
                        }
                    )
                    
                    # Небольшая задержка для избежания rate limits (50ms)
                    await asyncio.sleep(0.05)
                    
                    logger.info(f"Добавлен стикер {idx}/{len(stickers)} в пак {pack_name}")
                    
                except Exception as e:
                    logger.error(f"Ошибка добавления стикера {idx}: {e}")
                    # Продолжаем с остальными стикерами даже если один не прошёл
                    continue
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка создания стикерпака: {e}")
            return False

# ==================== КЛАВИАТУРЫ ====================

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню бота"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Загрузить изображение", callback_data="upload_image")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="show_help")]
    ])

def get_grid_size_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора размера сетки"""
    keyboard = []
    row = []
    
    for idx, (size_label, (cols, rows)) in enumerate(GRID_SIZES.items()):
        total_stickers = cols * rows
        button = InlineKeyboardButton(
            text=f"{size_label} ({total_stickers} стикеров)",
            callback_data=f"grid_{size_label}"
        )
        row.append(button)
        
        # Создаём новую строку после каждых 2 кнопок
        if len(row) == 2:
            keyboard.append(row)
            row = []
    
    # Добавляем оставшиеся кнопки
    if row:
        keyboard.append(row)
    
    keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура отмены"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="cancel")]
    ])

# ==================== РОУТЕРЫ ====================

router = Router()

# ==================== ОБРАБОТЧИКИ КОМАНД ====================

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()
    
    welcome_text = """
👋 Добро пожаловать в Image to Sticker Pack Bot!

📸 Я конвертирую ваши изображения в стикерпаки, которые вы можете использовать для создания мозаичных эффектов в чатах!

💡 Как использовать:
1️⃣ Отправьте мне изображение
2️⃣ Выберите размер сетки
3️⃣ Получите готовый стикерпак
4️⃣ Используйте стикеры в чатах!

✨ Функции:
• Бесплатно и без ограничений
• Несколько размеров сетки (от 3x4 до 9x11)
• Высокое качество изображений
• Быстрая обработка

🚀 Готовы начать?
"""
    
    await message.answer(welcome_text, reply_markup=get_main_menu_keyboard())

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = """
ℹ️ ПОМОЩЬ

📋 Как использовать бота:

1️⃣ Отправьте изображение
   • Как файл (лучше качество)
   • Или как фото

2️⃣ Выберите размер сетки:
   • 3x4 = 12 стикеров
   • 4x6 = 24 стикера
   • 5x8 = 40 стикеров
   • 7x9 = 63 стикера
   • 9x11 = 99 стикеров

3️⃣ Дождитесь обработки
   • Обычно занимает 30-60 секунд

4️⃣ Добавьте стикерпак в Telegram
   • Кликните на ссылку
   • Используйте стикеры по порядку

💡 Советы:
• Отправляйте изображения как файлы для лучшего качества
• Большие изображения работают лучше
• Минимальный размер: 512px на меньшей стороне

❓ Проблемы?
• /start - начать заново
• /cancel - отменить текущую операцию
"""
    
    await message.answer(help_text, reply_markup=get_main_menu_keyboard())

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Обработчик команды /cancel"""
    current_state = await state.get_state()
    
    if current_state is None:
        await message.answer("❌ Нечего отменять", reply_markup=get_main_menu_keyboard())
        return
    
    await state.clear()
    await message.answer("✅ Операция отменена", reply_markup=get_main_menu_keyboard())

# ==================== ОБРАБОТЧИКИ CALLBACK ====================

@router.callback_query(F.data == "upload_image")
async def callback_upload_image(callback: CallbackQuery, state: FSMContext):
    """Начало загрузки изображения"""
    await callback.message.edit_text(
        "📸 Отправьте мне изображение\n\n"
        "💡 Для лучшего качества отправляйте как файл (не сжатое фото)\n\n"
        "Минимальный размер: 512px на меньшей стороне",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(ImageProcessing.WAITING_IMAGE)
    await callback.answer()

@router.callback_query(F.data == "show_help")
async def callback_show_help(callback: CallbackQuery):
    """Показать помощь"""
    help_text = """
ℹ️ ПОМОЩЬ

📋 Доступные размеры сетки:
• 3x4 (12 стикеров)
• 4x6 (24 стикера)
• 5x8 (40 стикеров)
• 7x9 (63 стикера)
• 9x11 (99 стикеров)

💡 Чем больше сетка, тем детальнее будет мозаика!

🎨 После получения стикерпака:
1. Откройте стикерпак по ссылке
2. Отправляйте стикеры по порядку (слева-направо, сверху-вниз)
3. Создавайте крутые мозаичные картины в чатах!
"""
    
    await callback.message.edit_text(help_text, reply_markup=get_main_menu_keyboard())
    await callback.answer()

@router.callback_query(F.data == "back_to_menu")
async def callback_back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Вернуться в главное меню"""
    await state.clear()
    await callback.message.edit_text(
        "📊 Главное меню",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "cancel")
async def callback_cancel(callback: CallbackQuery, state: FSMContext):
    """Отмена операции"""
    await state.clear()
    await callback.message.edit_text(
        "✅ Операция отменена",
        reply_markup=get_main_menu_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("grid_"))
async def callback_grid_selection(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора размера сетки"""
    grid_size = callback.data.replace('grid_', '')
    
    if grid_size not in GRID_SIZES:
        await callback.answer("❌ Неверный размер сетки", show_alert=True)
        return
    
    cols, rows = GRID_SIZES[grid_size]
    
    # Получаем сохранённые данные изображения
    data = await state.get_data()
    file_id = data.get('image_file_id')
    
    if not file_id:
        await callback.message.edit_text(
            "❌ Данные изображения не найдены. Пожалуйста, отправьте изображение снова.",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
        return
    
    # Обновляем сообщение
    await callback.message.edit_text(
        f"⚙️ Обработка изображения в сетку {grid_size} ({cols}x{rows} = {cols*rows} стикеров)...\n\n"
        "Это может занять 1-2 минуты. Пожалуйста, подождите! ⏳"
    )
    await callback.answer()
    
    # Создаём временную директорию
    temp_dir = tempfile.mkdtemp()
    
    try:
        # Скачиваем изображение
        file = await callback.bot.get_file(file_id)
        image_path = os.path.join(temp_dir, 'original.jpg')
        await callback.bot.download_file(file.file_path, image_path)
        
        # Открываем и обрабатываем изображение
        with Image.open(image_path) as img:
            # Конвертируем в RGB если нужно
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')
            
            # Проверяем минимальный размер
            min_dimension = min(img.width, img.height)
            if min_dimension < 512:
                await callback.message.edit_text(
                    f"❌ Изображение слишком маленькое ({img.width}x{img.height}).\n"
                    f"Пожалуйста, отправьте изображение минимум 512px на меньшей стороне.",
                    reply_markup=get_main_menu_keyboard()
                )
                await state.clear()
                return
            
            # Обрабатываем изображение
            processor = ImageProcessor()
            
            # Ресайз и обрезка под соотношение сторон сетки
            processed_img = processor.resize_and_crop(img, cols, rows)
            
            # Разрезаем на сетку
            slices = processor.slice_image(processed_img, cols, rows)
            
            # Конвертируем куски в формат стикеров
            sticker_files = []
            for slice_img in slices:
                sticker_data = processor.prepare_sticker(slice_img)
                sticker_files.append(sticker_data)
            
            logger.info(f"Создано {len(sticker_files)} стикеров для пользователя {callback.from_user.id}")
        
        # Создаём стикерпак
        pack_manager = StickerPackManager()
        pack_name = pack_manager.generate_pack_name(callback.from_user.id)
        pack_title = f"My {grid_size} Grid Image"
        
        await callback.message.edit_text(
            f"📦 Создание стикерпака с {len(sticker_files)} стикерами...\n"
            "Это может занять минуту! ⏳"
        )
        
        success = await pack_manager.create_sticker_pack(
            bot=callback.bot,
            user_id=callback.from_user.id,
            pack_name=pack_name,
            pack_title=pack_title,
            stickers=sticker_files,
        )
        
        if success:
            pack_url = f"https://t.me/addstickers/{pack_name}"
            
            result_text = f"""
✅ Готово! Ваш стикерпак создан!

🎨 Название: {pack_title}
📊 Сетка: {grid_size} ({cols*rows} стикеров)

🔗 Добавить в Telegram:
{pack_url}

💡 Как использовать:
1. Откройте стикерпак по ссылке выше
2. Отправляйте стикеры по порядку (слева-направо, сверху-вниз)
3. Создавайте мозаику в чатах!

📸 Отправьте ещё одно изображение для создания нового пака!
"""
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔗 Открыть стикерпак", url=pack_url)],
                [InlineKeyboardButton(text="📸 Создать ещё", callback_data="upload_image")],
                [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_menu")]
            ])
            
            await callback.message.edit_text(result_text, reply_markup=keyboard)
        else:
            await callback.message.edit_text(
                "❌ Не удалось создать стикерпак. Пожалуйста, попробуйте ещё раз или обратитесь в поддержку.",
                reply_markup=get_main_menu_keyboard()
            )
        
        await state.clear()
    
    except Exception as e:
        logger.error(f"Ошибка обработки изображения: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ Произошла ошибка при обработке:\n{str(e)}\n\n"
            "Пожалуйста, попробуйте с другим изображением.",
            reply_markup=get_main_menu_keyboard()
        )
        await state.clear()
    
    finally:
        # Очистка временной директории
        try:
            shutil.rmtree(temp_dir)
            logger.info(f"Очищена временная директория: {temp_dir}")
        except Exception as e:
            logger.error(f"Ошибка очистки временной директории: {e}")

# ==================== ОБРАБОТЧИКИ СООБЩЕНИЙ ====================

@router.message(ImageProcessing.WAITING_IMAGE, F.photo | F.document)
async def handle_image(message: Message, state: FSMContext):
    """Обработка полученного изображения"""
    # Получаем file_id в зависимости от типа сообщения
    if message.photo:
        # Пользователь отправил сжатое фото
        file_id = message.photo[-1].file_id  # Берём самое высокое разрешение
        await message.answer(
            "📸 Получено фото!\n\n"
            "💡 Для лучшего качества в следующий раз отправьте как файл\n\n"
            "⏳ Подготовка опций..."
        )
    elif message.document:
        # Пользователь отправил файл
        document = message.document
        # Проверяем, что это изображение
        if not document.mime_type or not document.mime_type.startswith('image/'):
            await message.answer(
                "❌ Пожалуйста, отправьте файл изображения (JPG, PNG и т.д.)",
                reply_markup=get_cancel_keyboard()
            )
            return
        file_id = document.file_id
        await message.answer("📁 Получен файл изображения!\n⏳ Подготовка опций...")
    else:
        await message.answer(
            "❌ Пожалуйста, отправьте изображение",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Сохраняем file_id в состоянии
    await state.update_data(image_file_id=file_id)
    
    # Показываем клавиатуру выбора размера сетки
    await message.answer(
        "🎯 Выберите размер сетки:\n\n"
        "Сетка определяет, на сколько частей будет разрезано изображение.",
        reply_markup=get_grid_size_keyboard()
    )
    
    await state.set_state(ImageProcessing.SELECTING_GRID)

@router.message(ImageProcessing.WAITING_IMAGE)
async def handle_wrong_content(message: Message):
    """Обработка неправильного типа контента"""
    await message.answer(
        "❌ Пожалуйста, отправьте изображение (фото или файл)",
        reply_markup=get_cancel_keyboard()
    )

@router.message()
async def handle_any_message(message: Message):
    """Обработка любых других сообщений"""
    await message.answer(
        "👋 Используйте /start для начала работы сботом",
        reply_markup=get_main_menu_keyboard()
    )

# ==================== ГЛАВНАЯ ФУНКЦИЯ ====================

async def main():
    """Главная функция запуска бота"""
    print("=" * 60)
    print("🚀 Запуск Image to Sticker Pack Bot")
    print("=" * 60)
    
    # Создаём необходимые директории
    os.makedirs('logs', exist_ok=True)
    
    # Инициализация бота
    bot = Bot(token=BOT_TOKEN)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Подключаем роутер
    dp.include_router(router)
    
    # Получаем информацию о боте
    bot_info = await bot.get_me()
    print(f"🤖 Бот: @{bot_info.username}")
    print(f"🆔 Bot ID: {bot_info.id}")
    print(f"📝 Bot Username (для стикерпаков): {BOT_USERNAME}")
    print("=" * 60)
    print("✅ Бот успешно запущен!")
    print("💡 Нажмите Ctrl+C для остановки")
    print("=" * 60)
    
    try:
        # Запуск polling
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except KeyboardInterrupt:
        print("\n⚠️  Получен сигнал остановки...")
    finally:
        await bot.session.close()
        print("✅ Бот остановлен")

# ==================== ТОЧКА ВХОДА ====================

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 До свидания!")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)