import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# Конфигурация (временно, пока не настроен .env)
BOT_TOKEN = "8340737319:AAGyz2fGHgiSzZWwuE0xioUL5at24Rzt8kI"
ADMIN_ID = 8478884644
DB_PATH = "data/tiktok_bot.db"

from database import init_db, add_account, get_accounts_by_user, get_all_accounts, get_account_by_id

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

# Состояния для FSM
class AddAccountState(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()

# Проверка администратора
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

@dp.message(Command("start"))
async def start_cmd(message: Message):
    text = (
        "🤖 **TikTok Bot Manager**\n\n"
        "/add - добавить аккаунт\n"
        "/my - мои аккаунты\n"
        "/help - помощь"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("help"))
async def help_cmd(message: Message):
    text = (
        "📚 **Команды:**\n"
        "/add - добавить аккаунт TikTok\n"
        "/my - список ваших аккаунтов\n"
        "/admin_stats - статистика (только админ)\n"
        "/cancel - отмена"
    )
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Отменено")

@dp.message(Command("add"))
async def add_account_start(message: Message, state: FSMContext):
    await state.set_state(AddAccountState.waiting_for_username)
    await message.answer("📱 Введите логин TikTok:")

@dp.message(AddAccountState.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username:
        await message.answer("❌ Логин не может быть пустым")
        return
    
    await state.update_data(username=username)
    await state.set_state(AddAccountState.waiting_for_password)
    await message.answer("🔐 Введите пароль:")

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
        await message.answer(f"✅ Аккаунт {username} добавлен! ID: {account_id}")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        await message.answer("❌ Ошибка при сохранении")
    
    await state.clear()

@dp.message(Command("my"))
async def my_accounts_cmd(message: Message):
    accounts = await get_accounts_by_user(message.from_user.id)
    
    if not accounts:
        await message.answer("📭 У вас нет аккаунтов. Используйте /add")
        return
    
    text = "📱 **Ваши аккаунты:**\n\n"
    for acc in accounts:
        status = "🟢" if acc['active'] else "⚪️"
        text += f"{status} ID {acc['id']}: {acc['username']}\n"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("admin_stats"))
async def admin_stats_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ Доступ только для админа")
        return
    
    accounts = await get_all_accounts()
    if not accounts:
        await message.answer("📊 Нет аккаунтов")
        return
    
    text = "📊 **Все аккаунты:**\n\n"
    for acc in accounts:
        status = "🟢" if acc['active'] else "⚪️"
        text += f"{status} ID {acc['id']}: {acc['username']} (владелец: {acc['telegram_id']})\n"
    
    await message.answer(text, parse_mode="Markdown")

async def main():
    await init_db()
    logger.info("✅ Бот запущен и готов к работе")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
