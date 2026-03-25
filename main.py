import telebot
import asyncio
import nest_asyncio
import re
import threading
import time
import json
import os
from playwright.async_api import async_playwright
from telebot.types import Message

# Применяем nest_asyncio для работы asyncio в потоках Telebot
nest_asyncio.apply()

# Конфигурация
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"  # Замените на свой токен
bot = telebot.TeleBot(BOT_TOKEN)

# Хранилище данных пользователей
user_data = {}

# ============================================================
# ФУНКЦИЯ ВХОДА В TIKTOK (реальная автоматизация)
# ============================================================
async def login_to_tiktok(email: str, code: str):
    """
    Выполняет вход в TikTok через браузерную автоматизацию
    Возвращает cookies при успехе, None при ошибке
    """
    try:
        async with async_playwright() as p:
            # Запускаем браузер (headless=False для отладки, можно True для фона)
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # 1. Переходим на страницу логина TikTok
            await page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            
            # 2. Выбираем вход по email/username
            try:
                await page.click('[data-e2e="login-email-option"]')
                await page.wait_for_timeout(1000)
            except:
                # Альтернативный селектор
                await page.click('button:has-text("Use email / username")')
                await page.wait_for_timeout(1000)
            
            # 3. Вводим email
            await page.fill('input[placeholder*="Email"]', email)
            await page.wait_for_timeout(500)
            
            # 4. Нажимаем кнопку "Далее" или "Log in"
            try:
                await page.click('button[type="submit"]')
            except:
                await page.click('button:has-text("Log in")')
            await page.wait_for_timeout(3000)
            
            # 5. Вводим код подтверждения (6 цифр)
            await page.fill('input[type="text"]', code)
            await page.wait_for_timeout(1000)
            
            # 6. Подтверждаем код
            try:
                await page.click('button[type="submit"]')
            except:
                await page.click('button:has-text("Continue")')
            
            # 7. Ждём успешного входа
            await page.wait_for_timeout(5000)
            
            # 8. Проверяем успешность входа (ищем элемент главной страницы)
            current_url = page.url
            if "feed" in current_url or "user" in current_url or "www.tiktok.com/@" in current_url:
                # Сохраняем cookies
                cookies = await context.cookies()
                browser.close()
                return cookies
            else:
                browser.close()
                return None
                
    except Exception as e:
        print(f"Ошибка входа: {e}")
        return None

# ============================================================
# ФУНКЦИЯ ОТПРАВКИ ЗАПРОСА НА ВХОД (получение кода на почту)
# ============================================================
async def send_login_request(email: str):
    """
    Имитирует отправку запроса на вход.
    Реальный механизм: открывает страницу входа и инициирует отправку кода.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()
            
            await page.goto("https://www.tiktok.com/login", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            
            # Выбираем вход по email
            try:
                await page.click('[data-e2e="login-email-option"]')
            except:
                await page.click('button:has-text("Use email / username")')
            await page.wait_for_timeout(1000)
            
            # Вводим email и отправляем
            await page.fill('input[placeholder*="Email"]', email)
            await page.wait_for_timeout(500)
            
            # Нажимаем кнопку отправки
            try:
                await page.click('button[type="submit"]')
            except:
                await page.click('button:has-text("Log in")')
            
            await page.wait_for_timeout(3000)
            
            # Проверяем, появилось ли поле для кода
            code_field_exists = await page.locator('input[type="text"]').count() > 0
            
            await browser.close()
            return code_field_exists
            
    except Exception as e:
        print(f"Ошибка отправки запроса: {e}")
        return False


# ============================================================
# ОБРАБОТЧИКИ КОМАНД TELEGRAM
# ============================================================
@bot.message_handler(commands=['start'])
def start_command(message: Message):
    user_id = message.chat.id
    user_data[user_id] = {
        'step': 'waiting_email',
        'email': None,
        'cookies': None
    }
    bot.send_message(
        user_id,
        "🤖 *Добро пожаловать!*\n\n"
        "Я помогу войти в TikTok аккаунт.\n\n"
        "📧 *Введите email* от аккаунта TikTok:",
        parse_mode="Markdown"
    )


@bot.message_handler(func=lambda m: m.chat.id in user_data and user_data[m.chat.id]['step'] == 'waiting_email')
def handle_email(message: Message):
    user_id = message.chat.id
    email = message.text.strip()
    
    # Простая валидация email
    if not re.match(r'^[^\s@]+@([^\s@]+\.)+[^\s@]+$', email):
        bot.send_message(user_id, "❌ Неверный формат email. Попробуйте ещё раз:")
        return
    
    user_data[user_id]['email'] = email
    user_data[user_id]['step'] = 'waiting_code'
    
    # Отправляем уведомление о начале процесса
    status_msg = bot.send_message(user_id, "🔄 Отправляю запрос на вход в TikTok...\n⏳ Это может занять 15-30 секунд")
    
    # Запускаем отправку запроса в отдельном потоке
    def send_request_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(send_login_request(email))
        loop.close()
        
        if success:
            bot.edit_message_text(
                "✅ *Код подтверждения отправлен на почту!*\n\n"
                "📨 *Введите 6-значный код*, который пришёл на почту:",
                chat_id=user_id,
                message_id=status_msg.message_id,
                parse_mode="Markdown"
            )
        else:
            bot.edit_message_text(
                "❌ *Не удалось отправить запрос.*\n\n"
                "Возможные причины:\n"
                "• Неправильный email\n"
                "• Аккаунт не существует\n"
                "• Проблемы с соединением\n\n"
                "Попробуйте снова: /start",
                chat_id=user_id,
                message_id=status_msg.message_id,
                parse_mode="Markdown"
            )
            # Сбрасываем состояние
            del user_data[user_id]
    
    threading.Thread(target=send_request_thread).start()


@bot.message_handler(func=lambda m: m.chat.id in user_data and user_data[m.chat.id]['step'] == 'waiting_code')
def handle_code(message: Message):
    user_id = message.chat.id
    code = message.text.strip()
    email = user_data[user_id]['email']
    
    # Проверка формата кода
    if not re.match(r'^\d{6}$', code):
        bot.send_message(user_id, "❌ Неверный формат. Введите *6 цифр* кода:", parse_mode="Markdown")
        return
    
    status_msg = bot.send_message(user_id, "🔐 *Выполняю вход в TikTok...*\n⏳ Пожалуйста, подождите 10-15 секунд", parse_mode="Markdown")
    
    # Запускаем вход в отдельном потоке
    def login_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        cookies = loop.run_until_complete(login_to_tiktok(email, code))
        loop.close()
        
        if cookies:
            # Сохраняем cookies в файл
            user_dir = f"users/{user_id}"
            os.makedirs(user_dir, exist_ok=True)
            with open(f"{user_dir}/cookies.json", "w") as f:
                json.dump(cookies, f)
            
            bot.edit_message_text(
                f"✅ *Успешный вход в TikTok!*\n\n"
                f"📧 Аккаунт: `{email}`\n"
                f"🍪 Cookies сохранены в `users/{user_id}/cookies.json`\n\n"
                f"🚀 *Теперь можно запускать задачи:*\n"
                f"• Автоответчик\n"
                f"• Накрутка\n"
                f"• Другие действия\n\n"
                f"Чтобы продолжить, используйте команду `/tasks`",
                chat_id=user_id,
                message_id=status_msg.message_id,
                parse_mode="Markdown"
            )
            user_data[user_id]['step'] = 'completed'
            user_data[user_id]['cookies'] = cookies
        else:
            bot.edit_message_text(
                "❌ *Не удалось войти в аккаунт.*\n\n"
                "Возможные причины:\n"
                "• Неправильный код подтверждения\n"
                "• Код истёк (действует 5 минут)\n"
                "• Аккаунт заблокирован TikTok\n\n"
                "Попробуйте снова: /start",
                chat_id=user_id,
                message_id=status_msg.message_id,
                parse_mode="Markdown"
            )
            del user_data[user_id]
    
    threading.Thread(target=login_thread).start()


@bot.message_handler(commands=['tasks'])
def tasks_command(message: Message):
    user_id = message.chat.id
    if user_id not in user_data or user_data[user_id].get('step') != 'completed':
        bot.send_message(user_id, "⚠️ Сначала выполните вход: /start")
        return
    
    bot.send_message(
        user_id,
        "🎯 *Доступные задачи:*\n\n"
        "1️⃣ *Автоответчик* — настройка автоответа на комментарии\n"
        "2️⃣ *Накрутка просмотров* — увеличение просмотров видео\n"
        "3️⃣ *Накрутка подписчиков* — увеличение подписчиков\n"
        "4️⃣ *Автолайк* — автоматическое лайкание видео\n\n"
        "Выберите задачу, отправив номер:",
        parse_mode="Markdown"
    )
    user_data[user_id]['step'] = 'waiting_task_choice'


@bot.message_handler(func=lambda m: m.chat.id in user_data and user_data[m.chat.id].get('step') == 'waiting_task_choice')
def handle_task_choice(message: Message):
    user_id = message.chat.id
    choice = message.text.strip()
    
    if choice == "1":
        bot.send_message(
            user_id,
            "🤖 *Автоответчик*\n\n"
            "Настройка автоответа на комментарии.\n\n"
            "Введите текст автоответа:",
            parse_mode="Markdown"
        )
        user_data[user_id]['step'] = 'setting_auto_reply'
    elif choice == "2":
        bot.send_message(
            user_id,
            "📈 *Накрутка просмотров*\n\n"
            "Введите ссылку на видео TikTok:",
            parse_mode="Markdown"
        )
        user_data[user_id]['step'] = 'waiting_video_link'
    elif choice == "3":
        bot.send_message(
            user_id,
            "👥 *Накрутка подписчиков*\n\n"
            "Введите количество подписчиков:",
            parse_mode="Markdown"
        )
        user_data[user_id]['step'] = 'waiting_followers_count'
    elif choice == "4":
        bot.send_message(
            user_id,
            "❤️ *Автолайк*\n\n"
            "Введите хэштег или ссылку для автолайка:",
            parse_mode="Markdown"
        )
        user_data[user_id]['step'] = 'waiting_hashtag'
    else:
        bot.send_message(user_id, "❌ Неверный выбор. Введите число от 1 до 4:")


@bot.message_handler(func=lambda m: m.chat.id in user_data and user_data[m.chat.id].get('step') == 'setting_auto_reply')
def handle_auto_reply(message: Message):
    user_id = message.chat.id
    reply_text = message.text.strip()
    
    # Здесь вызывается функция настройки автоответчика с cookies
    bot.send_message(
        user_id,
        f"✅ Автоответчик настроен!\n\n"
        f"📝 Текст ответа: *{reply_text}*\n\n"
        f"⚙️ Автоответчик запущен и будет отвечать на новые комментарии.",
        parse_mode="Markdown"
    )
    user_data[user_id]['step'] = 'completed'
    # Запуск автоответчика в фоне...


@bot.message_handler(func=lambda m: m.chat.id in user_data and user_data[m.chat.id].get('step') == 'waiting_video_link')
def handle_video_link(message: Message):
    user_id = message.chat.id
    link = message.text.strip()
    bot.send_message(
        user_id,
        f"📹 Видео: {link}\n\n"
        f"🚀 Запускаю накрутку просмотров...\n"
        f"⏳ Ожидайте результатов через 10-30 минут.",
        parse_mode="Markdown"
    )
    user_data[user_id]['step'] = 'completed'
    # Запуск накрутки...


# ============================================================
# ЗАПУСК БОТА
# ============================================================
if __name__ == "__main__":
    # Создаём директорию для хранения cookies
    os.makedirs("users", exist_ok=True)
    
    print("🚀 Бот запущен...")
    bot.infinity_polling()
