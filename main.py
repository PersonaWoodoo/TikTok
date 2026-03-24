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

from database import init_db, add_account, get_accounts_by_user, get_all_accounts, get_account_by_id
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

# Активные воркеры TikTok
active_workers = {}

# Состояния для FSM
class AddAccountState(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()

# Проверка администратора
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# ========== КЛАВИАТУРЫ ==========

def get_main_keyboard(is_admin_user: bool = False):
    """Главная клавиатура"""
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
    """Админ-клавиатура"""
    buttons = [
        [InlineKeyboardButton(text="📊 Общая статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users")],
        [InlineKeyboardButton(text="🛑 Остановить всё", callback_data="admin_stop_all")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_accounts_keyboard(accounts, user_id, is_admin_user=False):
    """Клавиатура со списком аккаунтов"""
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
    """Клавиатура действий для конкретного аккаунта"""
    buttons = []
    
    if is_running:
        buttons.append([InlineKeyboardButton(text="⏹ Остановить", callback_data=f"stop_{account_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="🚀 Запустить", callback_data=f"start_{account_id}")])
        buttons.append([InlineKeyboardButton(text="🔍 Проверить вход", callback_data=f"test_{account_id}"])])
    
    buttons.append([InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{account_id}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="my_accounts")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_back_keyboard():
    """Кнопка назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
    ])

# ========== ОБРАБОТКА КОМАНД ==========

@dp.message(Command("start"))
async def start_cmd(message: Message):
    is_admin_user = is_admin(message.from_user.id)
    await message.answer(
        "🤖 TikTok Bot Manager\n\n"
        "✅ Бот работает!\n\n"
        "Используйте кнопки ниже для управления:",
        reply_markup=get_main_keyboard(is_admin_user)
    )

@dp.message(Command("help"))
async def help_cmd(message: Message):
    is_admin_user = is_admin(message.from_user.id)
    await message.answer(
        "📚 Помощь по командам\n\n"
        "Используйте кнопки для управления ботом.\n\n"
        "📌 Доступные функции:\n"
        "• Добавление аккаунтов TikTok\n"
        "• Автоматический ответ на сообщения\n"
        "• Отправка стикеров раз в 11 часов\n"
        "• Поддержание активности в диалогах",
        reply_markup=get_main_keyboard(is_admin_user)
    )

@dp.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "✅ Операция отменена",
        reply_markup=get_main_keyboard(is_admin(message.from_user.id))
    )

# ========== ОБРАБОТКА ИНЛАЙН КНОПОК ==========

@dp.callback_query()
async def handle_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    is_admin_user = is_admin(user_id)
    data = callback.data
    
    # Главное меню
    if data == "back_to_main":
        await callback.message.edit_text(
            "🤖 TikTok Bot Manager\n\nГлавное меню:",
            reply_markup=get_main_keyboard(is_admin_user)
        )
        await callback.answer()
        return
    
    if data == "help":
        await callback.message.edit_text(
            "📚 Помощь\n\n"
            "• /add - добавить аккаунт\n"
            "• /my - мои аккаунты\n"
            "• /starttiktok - запустить\n"
            "• /stoptiktok - остановить\n"
            "• /status - статус\n\n"
            "Используйте кнопки для управления",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    if data == "add_account":
        await state.set_state(AddAccountState.waiting_for_username)
        await callback.message.edit_text(
            "📱 Введите логин или email TikTok:\n\n"
            "Для отмены отправьте /cancel",
            reply_markup=get_back_keyboard()
        )
        await callback.answer()
        return
    
    if data == "my_accounts":
        await show_my_accounts(callback, user_id)
        await callback.answer()
        return
    
    if data == "status":
        await show_status(callback, user_id)
        await callback.answer()
        return
    
    if data == "start_worker":
        await show_accounts_for_start(callback, user_id)
        await callback.answer()
        return
    
    if data == "stop_worker":
        await show_accounts_for_stop(callback, user_id)
        await callback.answer()
        return
    
    # Админ-панель
    if data == "admin_panel" and is_admin_user:
        await callback.message.edit_text(
            "🔐 Админ-панель\n\nВыберите действие:",
            reply_markup=get_admin_keyboard()
        )
        await callback.answer()
        return
    
    if data == "admin_stats" and is_admin_user:
        await show_admin_stats(callback)
        await callback.answer()
        return
    
    if data == "admin_users" and is_admin_user:
        await show_admin_users(callback)
        await callback.answer()
        return
    
    if data == "admin_stop_all" and is_admin_user:
        await admin_stop_all(callback)
        await callback.answer()
        return
    
    # Действия с аккаунтом
    if data.startswith("account_"):
        account_id = int(data.split("_")[1])
        await show_account_actions(callback, account_id, user_id, is_admin_user)
        await callback.answer()
        return
    
    if data.startswith("start_"):
        account_id = int(data.split("_")[1])
        await start_worker_action(callback, account_id, user_id)
        await callback.answer()
        return
    
    if data.startswith("stop_"):
        account_id = int(data.split("_")[1])
        await stop_worker_action(callback, account_id, user_id)
        await callback.answer()
        return
    
    if data.startswith("test_"):
        account_id = int(data.split("_")[1])
        await test_login_action(callback, account_id, user_id)
        await callback.answer()
        return
    
    if data.startswith("delete_"):
        account_id = int(data.split("_")[1])
        await delete_account_action(callback, account_id, user_id)
        await callback.answer()
        return
    
    await callback.answer("Неизвестная команда")

# ========== ФУНКЦИИ ДЛЯ ОТОБРАЖЕНИЯ ==========

async def show_my_accounts(callback: CallbackQuery, user_id: int):
    """Показать аккаунты пользователя"""
    accounts = await get_accounts_by_user(user_id)
    
    if not accounts:
        await callback.message.edit_text(
            "📭 У вас нет добавленных аккаунтов.\n\n"
            "Нажмите кнопку ниже чтобы добавить:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить аккаунт", callback_data="add_account")],
                [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")]
            ])
        )
        return
    
    text = "📱 Ваши аккаунты:\n\n"
    for acc in accounts:
        status = "🟢" if acc['active'] else "⚪️"
        is_running = "🚀 РАБОТАЕТ" if acc['id'] in active_workers else "⏸ ОСТАНОВЛЕН"
        text += f"{status} ID {acc['id']}: {acc['username']}\n"
        text += f"   └ {is_running}\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=get_accounts_keyboard(accounts, user_id, is_admin(callback.from_user.id))
    )

async def show_status(callback: CallbackQuery, user_id: int):
    """Показать статус работы"""
    accounts = await get_accounts_by_user(user_id)
    
    if not accounts:
        await callback.message.edit_text(
            "📭 Нет добавленных аккаунтов.",
            reply_markup=get_back_keyboard()
        )
        return
    
    text = "📊 Статус работы:\n\n"
    for acc in accounts:
        is_active = acc['id'] in active_workers
        status = "🟢 РАБОТАЕТ" if is_active else "⚪️ ОСТАНОВЛЕН"
        text += f"ID {acc['id']}: {acc['username']}\n"
        text += f"└ {status}\n\n"
    
    await callback.message.edit_text(text, reply_markup=get_back_keyboard())

async def show_accounts_for_start(callback: CallbackQuery, user_id: int):
    """Показать аккаунты для запуска"""
    accounts = await get_accounts_by_user(user_id)
    
    if not accounts:
        await callback.message.edit_text(
            "❌ У вас нет аккаунтов. Сначала добавьте через /add",
            reply_markup=get_back_keyboard()
        )
        return
    
    text = "🚀 Выберите аккаунт для запуска:\n\n"
    buttons = []
    for acc in accounts:
        if acc['id'] not in active_workers:
            buttons.append([InlineKeyboardButton(
                text=f"▶️ ID {acc['id']}: {acc['username']}",
                callback_data=f"start_{acc['id']}"
            )])
    
    if not buttons:
        await callback.message.edit_text(
            "✅ Все ваши автоответчики уже работают!",
            reply_markup=get_back_keyboard()
        )
        return
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

async def show_accounts_for_stop(callback: CallbackQuery, user_id: int):
    """Показать аккаунты для остановки"""
    accounts = await get_accounts_by_user(user_id)
    
    text = "⏹ Выберите аккаунт для остановки:\n\n"
    buttons = []
    for acc in accounts:
        if acc['id'] in active_workers:
            buttons.append([InlineKeyboardButton(
                text=f"⏸ ID {acc['id']}: {acc['username']}",
                callback_data=f"stop_{acc['id']}"
            )])
    
    if not buttons:
        await callback.message.edit_text(
            "❌ Нет работающих автоответчиков для остановки",
            reply_markup=get_back_keyboard()
        )
        return
    
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

async def show_account_actions(callback: CallbackQuery, account_id: int, user_id: int, is_admin_user: bool):
    """Показать действия для аккаунта"""
    account = await get_account_by_id(account_id)
    if not account:
        await callback.message.edit_text("❌ Аккаунт не найден", reply_markup=get_back_keyboard())
        return
    
    if account['telegram_id'] != user_id and not is_admin_user:
        await callback.message.edit_text("⛔️ Это не ваш аккаунт", reply_markup=get_back_keyboard())
        return
    
    is_running = account_id in active_workers
    
    text = (
        f"🔐 Аккаунт ID {account_id}\n\n"
        f"📱 Логин: {account['username']}\n"
        f"🚀 Статус: {'🟢 Работает' if is_running else '⚪️ Остановлен'}\n"
    )
    
    await callback.message.edit_text(text, reply_markup=get_account_actions_keyboard(account_id, account['username'], is_running))

# ========== ДЕЙСТВИЯ С АККАУНТАМИ ==========

async def start_worker_action(callback: CallbackQuery, account_id: int, user_id: int):
    """Запуск воркера"""
    account = await get_account_by_id(account_id)
    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    if account_id in active_workers:
        await callback.answer("⚠️ Уже работает", show_alert=True)
        return
    
    try:
        worker = TikTokWorker(account_id, account['username'], account['password'])
        await worker.start()
        active_workers[account_id] = worker
        
        await callback.message.edit_text(
            f"✅ Автоответчик запущен!\n\n"
            f"📱 Аккаунт: {account['username']}\n"
            f"🆔 ID: {account_id}\n\n"
            f"📌 Что делает:\n"
            f"• Мгновенно отвечает на новые сообщения\n"
            f"• Раз в 11 часов отправляет стикер в активные диалоги\n\n"
            f"Остановить можно в меню аккаунта",
            reply_markup=get_back_keyboard()
        )
        await callback.answer("✅ Запущено!", show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {e}", show_alert=True)

async def stop_worker_action(callback: CallbackQuery, account_id: int, user_id: int):
    """Остановка воркера"""
    if account_id in active_workers:
        await active_workers[account_id].stop()
        del active_workers[account_id]
        await callback.message.edit_text(
            f"✅ Автоответчик для ID {account_id} остановлен",
            reply_markup=get_back_keyboard()
        )
        await callback.answer("✅ Остановлено!", show_alert=True)
    else:
        await callback.answer("❌ Не работает", show_alert=True)

async def test_login_action(callback: CallbackQuery, account_id: int, user_id: int):
    """Тест входа в TikTok"""
    account = await get_account_by_id(account_id)
    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"🔄 Проверяю вход для {account['username']}...\n\n⏳ Это может занять 30-60 секунд",
        reply_markup=get_back_keyboard()
    )
    
    success = await _test_tiktok_login(account['username'], account['password'])
    
    if success:
        await callback.message.edit_text(
            f"✅ Вход выполнен успешно!\n\n"
            f"📱 Аккаунт: {account['username']}\n\n"
            f"Теперь можно запустить автоответчик",
            reply_markup=get_account_actions_keyboard(account_id, account['username'], account_id in active_workers)
        )
    else:
        await callback.message.edit_text(
            f"❌ Вход не удался!\n\n"
            f"📱 Аккаунт: {account['username']}\n\n"
            f"🔍 Возможные причины:\n"
            f"• Неправильный логин или пароль\n"
            f"• Требуется двухфакторная аутентификация\n"
            f"• Аккаунт заблокирован TikTok",
            reply_markup=get_account_actions_keyboard(account_id, account['username'], account_id in active_workers)
        )

async def delete_account_action(callback: CallbackQuery, account_id: int, user_id: int):
    """Удаление аккаунта"""
    account = await get_account_by_id(account_id)
    if not account:
        await callback.answer("❌ Аккаунт не найден", show_alert=True)
        return
    
    if account_id in active_workers:
        await active_workers[account_id].stop()
        del active_workers[account_id]
    
    await delete_account(account_id)
    
    await callback.message.edit_text(
        f"🗑 Аккаунт {account['username']} удален",
        reply_markup=get_back_keyboard()
    )
    await callback.answer("✅ Удалено!", show_alert=True)

# ========== АДМИН-ФУНКЦИИ ==========

async def show_admin_stats(callback: CallbackQuery):
    """Показать админ-статистику"""
    accounts = await get_all_accounts()
    
    if not accounts:
        await callback.message.edit_text("📊 В базе нет аккаунтов", reply_markup=get_admin_keyboard())
        return
    
    total = len(accounts)
    active = sum(1 for acc in accounts if acc['active'])
    running = sum(1 for acc in accounts if acc['id'] in active_workers)
    unique_users = len(set(acc['telegram_id'] for acc in accounts))
    
    text = f"📊 Общая статистика:\n\n"
    text += f"👥 Пользователей: {unique_users}\n"
    text += f"📱 Всего аккаунтов: {total}\n"
    text += f"🟢 Активных в БД: {active}\n"
    text += f"🚀 Работающих: {running}\n\n"
    text += f"Список аккаунтов:\n"
    
    for acc in accounts:
        status = "🟢" if acc['active'] else "⚪️"
        running_status = "🚀" if acc['id'] in active_workers else "⏸"
        text += f"{status}{running_status} ID {acc['id']}: {acc['username']} (user: {acc['telegram_id']})\n"
    
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard())

async def show_admin_users(callback: CallbackQuery):
    """Показать список пользователей"""
    accounts = await get_all_accounts()
    
    if not accounts:
        await callback.message.edit_text("📊 Нет пользователей", reply_markup=get_admin_keyboard())
        return
    
    users = {}
    for acc in accounts:
        if acc['telegram_id'] not in users:
            users[acc['telegram_id']] = []
        users[acc['telegram_id']].append(acc)
    
    text = "👥 Список пользователей:\n\n"
    for user_id, user_accounts in users.items():
        text += f"👤 ID: {user_id}\n"
        text += f"📱 Аккаунтов: {len(user_accounts)}\n"
        for acc in user_accounts:
            running = "🚀" if acc['id'] in active_workers else "⏸"
            text += f"   {running} ID {acc['id']}: {acc['username']}\n"
        text += "\n"
    
    await callback.message.edit_text(text, reply_markup=get_admin_keyboard())

async def admin_stop_all(callback: CallbackQuery):
    """Остановить все воркеры"""
    count = len(active_workers)
    for acc_id, worker in list(active_workers.items()):
        await worker.stop()
        del active_workers[acc_id]
    
    await callback.message.edit_text(
        f"✅ Остановлено {count} автоответчиков",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer(f"✅ Остановлено {count} воркеров", show_alert=True)

# ========== ТЕСТ ВХОДА ==========

async def _test_tiktok_login(username, password):
    """Тестовая функция входа в TikTok"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={'width': 1920, 'height': 1080}
            )
            page = await context.new_page()
            
            try:
                await page.goto("https://www.tiktok.com", timeout=30000)
                await asyncio.sleep(3)
                
                login_btn = await page.wait_for_selector("a[href='/login']", timeout=10000)
                await login_btn.click()
                await asyncio.sleep(2)
                
                try:
                    email_tab = await page.wait_for_selector("a[href*='email']", timeout=5000)
                    if email_tab:
                        await email_tab.click()
                        await asyncio.sleep(1)
                except:
                    pass
                
                username_input = await page.wait_for_selector("input[name='username']", timeout=5000)
                await username_input.fill(username)
                await asyncio.sleep(1)
                
                password_input = await page.wait_for_selector("input[type='password']", timeout=5000)
                await password_input.fill(password)
                await asyncio.sleep(1)
                
                submit_btn = await page.wait_for_selector("button[type='submit']", timeout=5000)
                await submit_btn.click()
                
                await asyncio.sleep(5)
                
                current_url = page.url
                if "login" not in current_url and "passwort" not in current_url:
                    return True
                return False
                    
            except Exception as e:
                logger.error(f"Ошибка при входе: {e}")
                return False
            finally:
                await browser.close()
                
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        return False

# ========== ДОБАВЛЕНИЕ АККАУНТА (FSM) ==========

@dp.message(AddAccountState.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username:
        await message.answer("❌ Логин не может быть пустым")
        return
    
    await state.update_data(username=username)
    await state.set_state(AddAccountState.waiting_for_password)
    await message.answer(
        "🔐 Введите пароль от TikTok:",
        reply_markup=get_back_keyboard()
    )

@dp.message(AddAccountState.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    password = message.text.strip()
    if not password:
        await message.answer("❌ Пароль не может быть пустым")
        return
    
    data = await state.get_data()
    username = data['username']
    
    try:
        account_id = await add_account(message.from_user.id, username, password)
        await message.answer(
            f"✅ Аккаунт успешно добавлен!\n\n"
            f"📱 Логин: {username}\n"
            f"🆔 ID: {account_id}\n\n"
            f"Теперь проверьте вход в меню аккаунта",
            reply_markup=get_main_keyboard(is_admin(message.from_user.id))
        )
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer(
            "❌ Ошибка при сохранении аккаунта",
            reply_markup=get_main_keyboard(is_admin(message.from_user.id))
        )
    
    await state.clear()

# ========== ЗАПУСК БОТА ==========

async def main():
    await init_db()
    logger.info("✅ База данных инициализирована")
    logger.info("🚀 Бот запущен и готов к работе!")
    
    me = await bot.get_me()
    logger.info(f"🤖 Бот: @{me.username}")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
