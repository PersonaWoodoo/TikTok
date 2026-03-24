import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN, ADMIN_ID
from database import init_db, add_account, get_accounts_by_user, get_all_accounts, get_account_by_id, delete_account, update_account_status

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Инициализация бота и диспетчера
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Состояния для FSM
class AddAccountState(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()

# ========== Проверка администратора ==========
def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

# ========== Команды для всех пользователей ==========

@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    is_admin_user = is_admin(user_id)
    
    text = (
        "🤖 **TikTok Account Manager Bot**\n\n"
        "Я помогаю управлять аккаунтами TikTok и автоматизировать ответы на сообщения.\n\n"
        "**Доступные команды:**\n"
        "/add - добавить аккаунт TikTok\n"
        "/my - список ваших аккаунтов\n"
        "/help - помощь\n"
    )
    
    if is_admin_user:
        text += "\n🔐 **Админ-команды:**\n/admin_stats - статистика по всем аккаунтам\n/admin_account ID - детали аккаунта"
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("help"))
async def help_cmd(message: Message):
    user_id = message.from_user.id
    is_admin_user = is_admin(user_id)
    
    text = (
        "📚 **Помощь по командам**\n\n"
        "**Для всех пользователей:**\n"
        "/add - добавить новый аккаунт TikTok\n"
        "/my - показать список ваших аккаунтов\n"
        "/start - главное меню\n\n"
        "**Как добавить аккаунт:**\n"
        "1. Введите /add\n"
        "2. Введите логин/email от TikTok\n"
        "3. Введите пароль\n"
        "4. Бот сохранит данные и запустит автоответчик\n\n"
        "⚠️ **Важно:**\n"
        "- Не передавайте данные аккаунтов никому\n"
        "- Бот работает в фоновом режиме\n"
        "- При проблемах обратитесь к администратору"
    )
    
    if is_admin_user:
        text += (
            "\n\n**🔐 Админ-команды:**\n"
            "/admin_stats - статистика по всем аккаунтам\n"
            "/admin_account ID - полная информация об аккаунте"
        )
    
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("add"))
async def add_account_start(message: Message, state: FSMContext):
    await state.set_state(AddAccountState.waiting_for_username)
    await message.answer(
        "📱 **Добавление нового аккаунта TikTok**\n\n"
        "Введите **логин или email** от аккаунта TikTok:\n"
        "(можно отменить командой /cancel)",
        parse_mode="Markdown"
    )

@dp.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Операция отменена")

@dp.message(AddAccountState.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username:
        await message.answer("❌ Логин не может быть пустым. Попробуйте снова:")
        return
    
    await state.update_data(username=username)
    await state.set_state(AddAccountState.waiting_for_password)
    await message.answer(
        "🔐 Введите **пароль** от аккаунта TikTok:\n"
        "(пароль будет храниться в зашифрованном виде)",
        parse_mode="Markdown"
    )

@dp.message(AddAccountState.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    password = message.text.strip()
    if not password:
        await message.answer("❌ Пароль не может быть пустым. Попробуйте снова:")
        return
    
    data = await state.get_data()
    username = data['username']
    
    # Сохраняем аккаунт в БД
    account_id = await add_account(message.from_user.id, username, password)
    
    if account_id:
        await message.answer(
            f"✅ **Аккаунт успешно добавлен!**\n\n"
            f"📱 Логин: `{username}`\n"
            f"🆔 ID: {account_id}\n"
            f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
            f"Автоответчик будет активирован в ближайшее время.",
            parse_mode="Markdown"
        )
    else:
        await message.answer("❌ Ошибка при сохранении аккаунта. Попробуйте позже.")
    
    await state.clear()

@dp.message(Command("my"))
async def my_accounts_cmd(message: Message):
    accounts = await get_accounts_by_user(message.from_user.id)
    
    if not accounts:
        await message.answer(
            "📭 **У вас нет добавленных аккаунтов**\n\n"
            "Используйте команду /add, чтобы добавить первый аккаунт",
            parse_mode="Markdown"
        )
        return
    
    text = "📱 **Ваши аккаунты TikTok:**\n\n"
    for acc in accounts:
        status_emoji = "🟢" if acc['active'] else "⚪️"
        status_text = "Активен" if acc['active'] else "Неактивен"
        created_date = datetime.strptime(acc['created_at'], '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y')
        
        text += (
            f"{status_emoji} **ID {acc['id']}**\n"
            f"└ Логин: `{acc['username']}`\n"
            f"└ Статус: {status_text}\n"
            f"└ Добавлен: {created_date}\n\n"
        )
    
    # Добавляем инлайн-кнопки для управления
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить новый", callback_data="add_new")],
        [InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_list")]
    ])
    
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

# ========== Админ-команды ==========

@dp.message(Command("admin_stats"))
async def admin_stats_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ У вас нет прав администратора.")
        return
    
    accounts = await get_all_accounts()
    if not accounts:
        await message.answer("📊 В базе нет ни одного аккаунта.")
        return
    
    # Статистика
    total = len(accounts)
    active = sum(1 for acc in accounts if acc['active'])
    inactive = total - active
    
    # Уникальные пользователи
    unique_users = len(set(acc['telegram_id'] for acc in accounts))
    
    text = (
        "📊 **Общая статистика**\n\n"
        f"📱 Всего аккаунтов: **{total}**\n"
        f"🟢 Активных: **{active}**\n"
        f"⚪️ Неактивных: **{inactive}**\n"
        f"👥 Пользователей: **{unique_users}**\n\n"
        "**Список всех аккаунтов:**\n"
    )
    
    for acc in accounts:
        status_emoji = "🟢" if acc['active'] else "⚪️"
        created_date = datetime.strptime(acc['created_at'], '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y')
        text += (
            f"{status_emoji} ID {acc['id']}: `{acc['username']}`\n"
            f"└ Владелец: `{acc['telegram_id']}`\n"
            f"└ Добавлен: {created_date}\n"
        )
        
        if len(text) > 3500:  # Ограничение Telegram
            await message.answer(text, parse_mode="Markdown")
            text = ""
    
    if text:
        await message.answer(text, parse_mode="Markdown")

@dp.message(Command("admin_account"))
async def admin_account_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ У вас нет прав администратора.")
        return
    
    args = message.text.split()
    if len(args) != 2:
        await message.answer(
            "📝 **Использование:**\n"
            "/admin_account ID\n\n"
            "Пример: /admin_account 1",
            parse_mode="Markdown"
        )
        return
    
    try:
        account_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    
    acc = await get_account_by_id(account_id)
    if not acc:
        await message.answer(f"❌ Аккаунт с ID {account_id} не найден.")
        return
    
    created_date = datetime.strptime(acc['created_at'], '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M')
    
    text = (
        f"🔐 **Детальная информация об аккаунте**\n\n"
        f"**ID:** {acc['id']}\n"
        f"**Владелец:** `{acc['telegram_id']}`\n"
        f"**Логин:** `{acc['username']}`\n"
        f"**Пароль:** `{acc['password']}`\n"
        f"**Статус:** {'🟢 Активен' if acc['active'] else '⚪️ Неактивен'}\n"
        f"**Дата добавления:** {created_date}\n"
    )
    
    if acc['cookies']:
        text += f"\n**Куки:** `{acc['cookies'][:200]}...`"
    
    # Кнопки для управления аккаунтом
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🟢 Активировать" if not acc['active'] else "🔴 Деактивировать",
                callback_data=f"toggle_{account_id}"
            )
        ],
        [
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_{account_id}")
        ],
        [
            InlineKeyboardButton(text="📊 Обновить", callback_data=f"refresh_{account_id}")
        ]
    ])
    
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)

@dp.message(Command("admin_list_users"))
async def admin_list_users_cmd(message: Message):
    """Список всех пользователей и их аккаунтов"""
    if not is_admin(message.from_user.id):
        await message.answer("⛔️ У вас нет прав администратора.")
        return
    
    accounts = await get_all_accounts()
    if not accounts:
        await message.answer("📊 В базе нет ни одного аккаунта.")
        return
    
    # Группируем по пользователям
    users_dict = {}
    for acc in accounts:
        user_id = acc['telegram_id']
        if user_id not in users_dict:
            users_dict[user_id] = []
        users_dict[user_id].append(acc)
    
    text = "👥 **Список пользователей:**\n\n"
    for user_id, user_accounts in users_dict.items():
        text += f"**Пользователь:** `{user_id}`\n"
        text += f"📱 Аккаунтов: {len(user_accounts)}\n"
        for acc in user_accounts:
            status = "🟢" if acc['active'] else "⚪️"
            text += f"└ {status} ID {acc['id']}: `{acc['username']}`\n"
        text += "\n"
        
        if len(text) > 3500:
            await message.answer(text, parse_mode="Markdown")
            text = ""
    
    if text:
        await message.answer(text, parse_mode="Markdown")

# ========== Обработка инлайн-кнопок ==========

@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery):
    data = callback.data
    
    if data == "add_new":
        await callback.message.answer("Используйте команду /add для добавления аккаунта")
        await callback.answer()
    
    elif data == "refresh_list":
        await my_accounts_cmd(callback.message)
        await callback.answer()
    
    elif data.startswith("toggle_"):
        if not is_admin(callback.from_user.id):
            await callback.answer("⛔️ Нет прав администратора", show_alert=True)
            return
        
        account_id = int(data.split("_")[1])
        acc = await get_account_by_id(account_id)
        
        if acc:
            new_status = not acc['active']
            await update_account_status(account_id, new_status)
            status_text = "активирован" if new_status else "деактивирован"
            await callback.answer(f"✅ Аккаунт {status_text}", show_alert=True)
            
            # Обновляем сообщение
            await admin_account_cmd(callback.message)
        else:
            await callback.answer("❌ Аккаунт не найден", show_alert=True)
    
    elif data.startswith("delete_"):
        if not is_admin(callback.from_user.id):
            await callback.answer("⛔️ Нет прав администратора", show_alert=True)
            return
        
        account_id = int(data.split("_")[1])
        await delete_account(account_id)
        await callback.answer("✅ Аккаунт удален", show_alert=True)
        await callback.message.delete()
    
    elif data.startswith("refresh_"):
        if not is_admin(callback.from_user.id):
            await callback.answer("⛔️ Нет прав администратора", show_alert=True)
            return
        
        await admin_account_cmd(callback.message)
        await callback.answer("✅ Обновлено")

# ========== Обработка ошибок ==========

@dp.errors()
async def error_handler(update, exception):
    logging.error(f"Произошла ошибка: {exception}")
    return True

# ========== Запуск бота ==========

async def main():
    # Инициализируем базу данных
    await init_db()
    logging.info("✅ База данных инициализирована")
    
    # Запускаем бота
    logging.info("🚀 Бот запущен и готов к работе")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
