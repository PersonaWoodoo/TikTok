import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from playwright.async_api import async_playwright

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
            "📚 Помощь\n\nИспользуйте кнопки для управления ботом.",
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
                "📭 У вас нет аккаунтов.",
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
                "🚀 Выберите аккаунт:",
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
                "⏹ Выберите аккаунт:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
            )
        await callback.answer()
        return
    
    # Админ-панель
    if data == "admin_panel" and is_admin_user:
        await callback.message.edit_text("🔐 Админ-панель:", reply_markup=get_admin_keyboard())
        await callback.answer()
        return
    
    if data == "admin_stats" and is_admin_user:
        accounts = await get_all_accounts()
        total = len(accounts)
        running = sum(1 for acc in accounts if acc['id'] in active_workers)
        users = len(set(acc['telegram_id'] for acc in accounts))
        text = f"📊 Статистика:\n👥 Пользователей: {users}\n📱 Аккаунтов: {total}\n🚀 Работает: {running}"
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
        text = "👥 Пользователи:\n\n"
        for uid, accs in users.items():
            text += f"ID {uid}: {len(accs)} акк.\n"
        await callback.message.edit_text(text, reply_markup=get_admin_keyboard())
        await callback.answer()
        return
    
    if data == "admin_stop_all" and is_admin_user:
        count = len(active_workers)
        for aid, worker in list(active_workers.items()):
            await worker.stop()
            del active_workers[aid]
        await callback.message.edit_text(f"✅ Остановлено {count} воркеров", reply_markup=get_admin_keyboard())
        await callback.answer()
        return
    
    # Действия с аккаунтом
    if data.startswith("account_"):
        account_id = int(data.split("_")[1])
        account = await get_account_by_id(account_id)
        if account and (account['telegram_id'] == user_id or is_admin_user):
            is_running = account_id in active_workers
            text = f"🔐 Аккаунт ID {account_id}\n📱 {account['username']}\n🚀 {'Работает' if is_running else 'Остановлен'}"
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
            await callback.message.edit_text(f"✅ Запущен {account['username']}", reply_markup=get_back_keyboard())
            await callback.answer("✅ Запущено!")
        else:
            await callback.answer("❌ Ошибка")
        return
    
    if data.startswith("stop_"):
        account_id = int(data.split("_")[1])
        if account_id in active_workers:
            await active_workers[account_id].stop()
            del active_workers[account_id]
            await callback.message.edit_text(f"✅ Остановлен ID {account_id}", reply_markup=get_back_keyboard())
            await callback.answer("✅ Остановлено!")
        else:
            await callback.answer("❌ Не работает")
        return
    
    if data.startswith("delete_"):
        account_id = int(data.split("_")[1])
        if account_id in active_workers:
            await active_workers[account_id].stop()
            del active_workers[account_id]
        await delete_account(account_id)
        await callback.message.edit_text("🗑 Аккаунт удален", reply_markup=get_back_keyboard())
        await callback.answer("✅ Удалено!")
        return
    
    if data.startswith("test_"):
        account_id = int(data.split("_")[1])
        account = await get_account_by_id(account_id)
        if account:
            await callback.message.edit_text(f"🔄 Проверка входа...", reply_markup=get_back_keyboard())
            success = await _test_tiktok_login(account['username'], account['password'])
            if success:
                await callback.message.edit_text(f"✅ Вход успешен!\n{account['username']}", reply_markup=get_back_keyboard())
            else:
                await callback.message.edit_text(f"❌ Вход не удался!\n{account['username']}", reply_markup=get_back_keyboard())
        await callback.answer()
        return
    
    await callback.answer()

# ========== ТЕСТ ВХОДА ==========

async def _test_tiktok_login(username, password):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto("https://www.tiktok.com")
            await asyncio.sleep(2)
            await browser.close()
            return True
    except:
        return False

# ========== ДОБАВЛЕНИЕ АККАУНТА ==========

@dp.message(AddAccountState.waiting_for_username)
async def add_username(message: Message, state: FSMContext):
    await state.update_data(username=message.text.strip())
    await state.set_state(AddAccountState.waiting_for_password)
    await message.answer("🔐 Введите пароль:", reply_markup=get_back_keyboard())

@dp.message(AddAccountState.waiting_for_password)
async def add_password(message: Message, state: FSMContext):
    data = await state.get_data()
    username = data['username']
    password = message.text.strip()
    
    try:
        account_id = await add_account(message.from_user.id, username, password)
        await message.answer(
            f"✅ Аккаунт добавлен!\nID: {account_id}\nЛогин: {username}",
            reply_markup=get_main_keyboard(is_admin(message.from_user.id))
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}", reply_markup=get_main_keyboard(is_admin(message.from_user.id)))
    
    await state.clear()

# ========== ЗАПУСК ==========

async def main():
    await init_db()
    logger.info("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
