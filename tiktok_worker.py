import asyncio
import random
import logging
from datetime import datetime
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class TikTokWorker:
    def __init__(self, account_id, username, password):
        self.account_id = account_id
        self.username = username
        self.password = password
        self.is_running = False
        self.task = None
        self.browser = None
        self.context = None
        self.page = None
        self.last_sticker_time = None
        
    async def start(self):
        """Запуск воркера"""
        self.is_running = True
        self.last_sticker_time = datetime.now()
        self.task = asyncio.create_task(self._run())
        logger.info(f"✅ Запущен воркер для {self.username}")
        
    async def stop(self):
        """Остановка воркера"""
        self.is_running = False
        if self.task:
            self.task.cancel()
        if self.browser:
            await self.browser.close()
        logger.info(f"🛑 Остановлен воркер для {self.username}")
        
    async def _run(self):
        """Основной цикл работы"""
        async with async_playwright() as p:
            try:
                # Запускаем браузер
                self.browser = await p.chromium.launch(headless=True)
                self.context = await self.browser.new_context(
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
                    viewport={'width': 375, 'height': 812}
                )
                self.page = await self.context.new_page()
                
                # Вход в TikTok
                login_success = await self._login()
                if not login_success:
                    logger.error(f"❌ {self.username}: Не удалось войти в TikTok")
                    return
                
                logger.info(f"✅ {self.username}: Успешный вход в TikTok")
                
                # Основной цикл - проверяем каждые 30 секунд
                while self.is_running:
                    try:
                        # 1. ПРОВЕРКА НОВЫХ СООБЩЕНИЙ (мгновенный ответ)
                        await self._check_and_reply_messages()
                        
                        # 2. ОТПРАВКА СТИКЕРА (каждые 11 часов)
                        now = datetime.now()
                        hours_passed = (now - self.last_sticker_time).total_seconds() / 3600
                        
                        if hours_passed >= 11:
                            await self._send_sticker_to_chats()
                            self.last_sticker_time = now
                            logger.info(f"📤 {self.username}: Отправлен плановый стикер")
                        
                        # Ждем 30 секунд перед следующей проверкой
                        await asyncio.sleep(30)
                        
                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        logger.error(f"Ошибка в цикле: {e}")
                        await asyncio.sleep(60)
                        
            except Exception as e:
                logger.error(f"Критическая ошибка: {e}")
            finally:
                if self.browser:
                    await self.browser.close()
                    
    async def _login(self):
        """Авторизация в TikTok"""
        try:
            # Переходим на страницу входа
            await self.page.goto("https://www.tiktok.com/login", timeout=30000)
            await asyncio.sleep(3)
            
            # Ищем кнопку входа по email/логину
            try:
                await self.page.click("a[href*='phone/email']", timeout=5000)
                await asyncio.sleep(2)
            except:
                pass
            
            # Вводим логин
            await self.page.fill("input[name='username']", self.username, timeout=5000)
            await asyncio.sleep(1)
            
            # Вводим пароль
            await self.page.fill("input[type='password']", self.password, timeout=5000)
            await asyncio.sleep(1)
            
            # Нажимаем вход
            await self.page.click("button[type='submit']", timeout=5000)
            await asyncio.sleep(5)
            
            # Проверяем успешность входа (по наличию аватара или ленты)
            try:
                await self.page.wait_for_selector("div[data-e2e='recommend-list-item']", timeout=10000)
                return True
            except:
                # Проверяем наличие аватара
                try:
                    await self.page.wait_for_selector("a[data-e2e='user-avatar']", timeout=5000)
                    return True
                except:
                    logger.error(f"❌ {self.username}: Не удалось подтвердить вход")
                    return False
                    
        except Exception as e:
            logger.error(f"Ошибка входа {self.username}: {e}")
            return False
            
    async def _check_and_reply_messages(self):
        """Проверка новых сообщений и мгновенный ответ"""
        try:
            # Переходим в раздел сообщений
            await self.page.goto("https://www.tiktok.com/messages", timeout=15000)
            await asyncio.sleep(2)
            
            # Ищем непрочитанные чаты
            unread_chats = await self.page.query_selector_all(
                "div[data-e2e='inbox-item']:has(span[class*='unread'])"
            )
            
            if not unread_chats:
                return
                
            logger.info(f"💬 {self.username}: Найдено {len(unread_chats)} непрочитанных сообщений")
            
            # Список ответов
            replies = [
                "👋 Привет!",
                "🔥 Спасибо за сообщение!",
                "❤️ Отвечу позже",
                "👍 Хорошего дня!",
                "😊 Рад общению!",
                "✨ Спасибо!",
                "💫 Отличный день!",
                "🎉 Приветствую!",
                "🌟 Класс!",
                "💪 Всегда на связи!",
                "👋 Привет! Как дела?",
                "🔥 Огонек!",
                "❤️ С уважением!",
                "😊 Отличного настроения!",
                "✨ Всего хорошего!"
            ]
            
            # Отвечаем на каждое непрочитанное
            for chat in unread_chats[:5]:  # Не более 5 за раз
                try:
                    await chat.click()
                    await asyncio.sleep(2)
                    
                    # Выбираем случайный ответ
                    reply = random.choice(replies)
                    
                    # Находим поле ввода
                    textarea = await self.page.query_selector("textarea[placeholder*='Message']")
                    if textarea:
                        await textarea.fill(reply)
                        await asyncio.sleep(1)
                        
                        # Нажимаем отправить
                        send_btn = await self.page.query_selector("button[aria-label='Send']")
                        if send_btn:
                            await send_btn.click()
                            logger.info(f"✅ {self.username}: Ответ отправлен: {reply}")
                    
                    await asyncio.sleep(1)
                    await self.page.go_back()
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Ошибка ответа на сообщение: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка проверки сообщений: {e}")
            
    async def _send_sticker_to_chats(self):
        """Отправка стикера в активные чаты"""
        try:
            # Переходим в раздел сообщений
            await self.page.goto("https://www.tiktok.com/messages", timeout=15000)
            await asyncio.sleep(2)
            
            # Получаем все чаты
            chats = await self.page.query_selector_all("div[data-e2e='inbox-item']")
            
            if not chats:
                logger.info(f"📭 {self.username}: Нет активных чатов для отправки")
                return
            
            # Список стикеров
            stickers = [
                "👋",
                "🔥",
                "❤️",
                "👍",
                "😊",
                "✨",
                "💫",
                "🎉",
                "🌟",
                "💪"
            ]
            
            # Выбираем случайный стикер
            sticker = random.choice(stickers)
            
            # Отправляем в первые 3 чата
            sent_count = 0
            for i, chat in enumerate(chats[:3]):
                try:
                    await chat.click()
                    await asyncio.sleep(2)
                    
                    # Находим поле ввода
                    textarea = await self.page.query_selector("textarea[placeholder*='Message']")
                    if textarea:
                        await textarea.fill(sticker)
                        await asyncio.sleep(1)
                        
                        # Нажимаем отправить
                        send_btn = await self.page.query_selector("button[aria-label='Send']")
                        if send_btn:
                            await send_btn.click()
                            sent_count += 1
                            logger.info(f"📤 {self.username}: Отправлен {sticker} в чат {i+1}")
                    
                    await asyncio.sleep(1)
                    await self.page.go_back()
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Ошибка отправки в чат {i}: {e}")
            
            logger.info(f"✅ {self.username}: Отправлено {sent_count} стикеров")
                
        except Exception as e:
            logger.error(f"Ошибка отправки стикеров: {e}")
