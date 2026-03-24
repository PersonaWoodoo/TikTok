import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

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

# ========== ОСНОВНЫЕ КОМАНДЫ ==========

@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    is_admin_user = is_admin(user_id)
    
    text = (
        "🤖 TikTok Bot Manager\n\n"
        "✅ Бот работает!\n\n"
        "📌 Команды:\n"
        "/add - добавить аккаунт TikTok\n"
        "/my - список ваших аккаунтов\n"
        "/starttiktok - запустить автоответчик\n"
        "/stoptiktok - остановить автоответчик\n"
        "/status - статус работы\n"
        "/help - помощь\n"
    )
    
    if is_admin_user:
        text += "\n🔐 Админ-команды:\n/adminstats - статистика всех аккаунтов\n/adminaccount ID - детали аккаунта\n/adminstopall - остановить все сессии"
    
    await message.answer(text)

@dp.message(Command("help"))
async def help_cmd(message: Message):
    user_id = message.from_user.id
    is_admin_user = is_admin(user_id)
    
    text = (
        "📚 Доступные команды:\n\n"
        "/start - запуск бота\n"
        "/add - добавить аккаунт TikTok\n"
        "/my - список ваших аккаунтов\n"
        "/starttiktok - запустить автоответчик TikTok\n"
        "/stoptiktok - остановить автоответчик\n"
        "/status - статус работы\n\n"
    )
    
    if is_admin_user:
        text += (
            "🔐 Админ-команды:\n"
            "/adminstats - статистика всех аккаунтов\n"
            "/adminaccount ID - детали аккаунта\n"
            "/adminstopall - остановить все сессии\n"
        )
    
    await message.answer(text)

@dp.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Операция отменена")

# ========== ДОБАВЛЕНИЕ АККАУНТА ==========

@dp.message(Command("add"))
async def add_account_start(message: Message, state: FSMContext):
    await state.set_state(AddAccountState.waiting_for_username)
    await message.answer("📱 Введите логин или email TikTok:")

@dp.message(AddAccountState.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username:
        await message.answer("❌ Логин не может быть пустым")
        return
    
    await state.update_data(username=username)
    await state.set_state(AddAccountState.waiting_for_password)
    await message.answer("🔐 Введите пароль от TikTok:")

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
            f"Теперь можно запустить автоответчик: /starttiktok {account_id}"
        )
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer("❌ Ошибка при сохранении аккаунта. Проверьте правильность данных.")
    
    await state.clear()

# ========== ПРОСМОТР АККАУНТОВ ==========

@dp.message(Command("my"))
async def my_accounts_cmd(message: Message):
    accounts = await get_accounts_by_user(message.from_user.id)
    
    if not accounts:
        await message.answer("📭 У вас нет добавленных аккаунтов. Используйте /add")
        return
    
    text = "📱 Ваши аккаунты:\n\n"
    for acc in accounts:
        status = "🟢" if acc['active'] else "⚪️"
        is_running = "🚀 РАБОТАЕТ" if acc['id'] in active_workers else "⏸ ОСТАНОВЛЕН"
        text += f"{status} ID {acc['id']}: {acc['username']}\n"
        text += f"   └ {is_running}\n\n"
    
    await message.answer(text)

# ========== УПРАВЛЕНИЕ TIKTOK ВОРКЕРОМ ==========

@dp.message(Command("starttiktok"))
async def start_tiktok_cmd(message: Message):
    """Запуск автоответчика для аккаунта"""
    args = message.text.split()
    
    # Если есть ID в команде
    if len(args) == 2:
        try:
            account_id = int(args[1])
            account = await get_account_by_id(account_id)
            
            if not account:
                await message.answer("❌ Аккаунт не найден")
                return
                
            if account['telegram_id'] != message.from_user.id and not is_admin(message.from_user.id):
                await message.answer("⛔️ Это не ваш аккаунт")
                return
                
            await _start_worker(message, account_id, account['username'])
            return
            
        except ValueError:
            await message.answer("❌ ID должен быть числом")
            return
    
    # Если ID не указан, показываем список аккаунтов
    accounts = await get_accounts_by_user(message.from_user.id)
    
    if not accounts:
        await message.answer("❌ У вас нет аккаунтов. Сначала добавьте через /add")
        return
    
    text = "📱 Выберите аккаунт для запуска:\n\n"
    for acc in accounts:
        status = "✅" if acc['id'] in active_workers else "❌"
        text += f"{status} ID {acc['id']}: {acc['username']}\n"
    
    text += "\nОтправьте: /starttiktok ID\nПример: /starttiktok 1"
    
    await message.answer(text)

async def _start_worker(message, account_id, username):
    """Запуск воркера"""
    if account_id in active_workers:
        await message.answer(f"⚠️ Автоответчик для {username} уже работает")
        return
    
    # Получаем пароль из БД
    account = await get_account_by_id(account_id)
    if not account:
        await message.answer("❌ Аккаунт не найден")
        return
    
    # Создаем и запускаем воркер
    try:
        worker = TikTokWorker(account_id, account['username'], account['password'])
        await worker.start()
        active_workers[account_id] = worker
        
        await message.answer(
            f"✅ Автоответчик запущен!\n\n"
            f"📱 Аккаунт: {username}\n"
            f"🆔 ID: {account_id}\n\n"
            f"📌 Что делает:\n"
            f"• Мгновенно отвечает на новые сообщения\n"
            f"• Раз в 11 часов отправляет случайный стикер\n"
            f"• Поддерживает активность\n\n"
            f"Остановить: /stoptiktok {account_id}"
        )
    except Exception as e:
        logger.error(f"Ошибка запуска: {e}")
        await message.answer(f"❌ Ошибка запуска: {str(e)}")

@dp.message(Command("stoptiktok"))
async def stop_tiktok_cmd(message: Message):
    """Остановка автоответчика"""
    args = message.text.split()
    
    # Если есть ID в команде
    if len(args) == 2:
        try:
            account_id = int(args[1])
            
            if account_id in active_workers:
                # Проверяем права
                account = await get_account_by_id(account_id)
                if account and (account['telegram_id'] == message.from_user.id or is_admin(message.from_user.id)):
                    await active_workers[account_id].stop()
                    del active_workers[account_id]
                    await message.answer(f"✅ Автоответчик для ID {account_id} остановлен")
                else:
                    await message.answer("⛔️ Нет прав для остановки этого аккаунта")
            else:
                await message.answer("❌ Автоответчик не активен")
            return
            
        except ValueError:
            await message.answer("❌ ID должен быть числом")
            return
    
    # Если ID не указан, показываем активные
    user_workers = []
    for acc_id, worker in active_workers.items():
        account = await get_account_by_id(acc_id)
        if account and (account['telegram_id'] == message.from_user.id or is_admin(message.from_user.id)):
            user_workers.append((acc_id, account['username']))
    
    if not user_workers:
        await message.answer("❌ Нет активных автоответчиков для остановки")
        return
        
    text = "🛑 Активные автоответчики:\n\n"
    for acc_id, username in user_workers:
        text += f"ID {acc_id}: {username}\n"
    text += "\nОтправьте: /stoptiktok ID\nПример: /stoptiktok 1"
    
    await message.answer(text)

@dp.message(Command("status"))
async def status_cmd(message: Message):
    """Статус работы всех аккаунтов пользователя"""
    accounts = await get_accounts_by_user(message.from_user.id)
    
    if not accounts:
        await message.answer("📭 Нет добавленных аккаунтов. Используйте /add")
        return
    
    text = "📊 Статус работы:\n\n"
    
    for acc in accounts:
        is_active = acc['id'] in active_workers
        status = "🟢 РАБОТАЕТ" if is_active else "⚪️ ОСТАНОВЛЕН"
        text += f"ID {acc['id']}: {acc['username']}\n"
        text += f"└ {status}\n\n"
    
    await message.answer(text)

# ========== АДМИН-КОМАНДЫ ==========

@dp.message(Command("adminstats"))
async def admin_stats_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Доступ только для администратора!")
        return
    
    accounts = await get_all_accounts()
    if not accounts:
        await message.answer("📊 В базе нет ни одного аккаунта")
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
    
    await message.answer(text)

@dp.message(Command("adminaccount"))
async def admin_account_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Доступ только для администратора!")
        return
    
    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /adminaccount ID")
        return
    
    try:
        account_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом")
        return
    
    account = await get_account_by_id(account_id)
    if not account:
        await message.answer(f"❌ Аккаунт с ID {account_id} не найден")
        return
    
    is_running = account_id in active_workers
    
    text = (
        f"🔐 Детали аккаунта ID {account['id']}\n\n"
        f"👤 Владелец: {account['telegram_id']}\n"
        f"📱 Логин: {account['username']}\n"
        f"🔑 Пароль: {account['password']}\n"
        f"🚀 Работает: {'Да' if is_running else 'Нет'}\n"
    )
    
    await message.answer(text)

@dp.message(Command("adminstopall"))
async def admin_stop_all_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Доступ только для администратора!")
        return
    
    count = len(active_workers)
    for acc_id, worker in list(active_workers.items()):
        await worker.stop()
        del active_workers[acc_id]
    
    await message.answer(f"✅ Остановлено {count} автоответчиков")

# ========== ОБРАБОТКА НЕИЗВЕСТНЫХ КОМАНД ==========

@dp.message()
async def unknown_command(message: Message):
    await message.answer("❓ Неизвестная команда. Используйте /help для списка команд")

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
