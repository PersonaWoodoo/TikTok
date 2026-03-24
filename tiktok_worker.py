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
        
    async def start(self):
        """Запуск воркера"""
        self.is_running = True
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
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
                )
                self.page = await self.context.new_page()
                
                # Вход в TikTok
                await self._login()
                
                # Основной цикл
                while self.is_running:
                    try:
                        # Раз в 7 часов отправляем стикер
                        await self._send_random_sticker()
                        
                        # Проверяем новые сообщения
                        await self._check_messages()
                        
                        # Ждем 7 часов (25200 секунд)
                        await asyncio.sleep(25200)
                        
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
            await self.page.goto("https://www.tiktok.com/login")
            await asyncio.sleep(3)
            
            # Ищем кнопку входа по email/логину
            await self.page.click("a[href*='phone/email']")
            await asyncio.sleep(2)
            
            # Вводим логин
            await self.page.fill("input[name='username']", self.username)
            await asyncio.sleep(1)
            
            # Вводим пароль
            await self.page.fill("input[type='password']", self.password)
            await asyncio.sleep(1)
            
            # Нажимаем вход
            await self.page.click("button[type='submit']")
            await asyncio.sleep(5)
            
            logger.info(f"✅ {self.username} - успешный вход")
            
        except Exception as e:
            logger.error(f"Ошибка входа {self.username}: {e}")
            raise
            
    async def _send_random_sticker(self):
        """Отправка случайного стикера/приветствия"""
        try:
            # Список приветствий
            greetings = [
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
            
            # Выбираем случайное
            sticker = random.choice(greetings)
            
            # Заходим в диалоги
            await self.page.goto("https://www.tiktok.com/messages")
            await asyncio.sleep(3)
            
            # Получаем список чатов
            chats = await self.page.query_selector_all("div[data-e2e='inbox-item']")
            
            # Отправляем в первые 5 чатов
            for i, chat in enumerate(chats[:5]):
                try:
                    await chat.click()
                    await asyncio.sleep(2)
                    
                    # Отправляем сообщение
                    textarea = await self.page.query_selector("textarea[placeholder*='Message']")
                    if textarea:
                        await textarea.fill(sticker)
                        await asyncio.sleep(1)
                        
                        send_btn = await self.page.query_selector("button[aria-label='Send']")
                        if send_btn:
                            await send_btn.click()
                            logger.info(f"✅ Отправлен {sticker} в чат {i+1}")
                    
                    await asyncio.sleep(2)
                    await self.page.go_back()
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Ошибка отправки в чат {i}: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка отправки стикера: {e}")
            
    async def _check_messages(self):
        """Проверка и ответ на новые сообщения"""
        try:
            await self.page.goto("https://www.tiktok.com/messages")
            await asyncio.sleep(3)
            
            # Ищем непрочитанные
            unread = await self.page.query_selector_all("div[data-e2e='inbox-item']:has(span[class*='unread'])")
            
            for chat in unread[:3]:
                try:
                    await chat.click()
                    await asyncio.sleep(2)
                    
                    # Ответное сообщение
                    response = random.choice([
                        "Привет! 👋",
                        "Спасибо за сообщение! 😊",
                        "Отвечу позже 🔥",
                        "Хорошего дня! ✨",
                        "👍"
                    ])
                    
                    textarea = await self.page.query_selector("textarea[placeholder*='Message']")
                    if textarea:
                        await textarea.fill(response)
                        await asyncio.sleep(1)
                        
                        send_btn = await self.page.query_selector("button[aria-label='Send']")
                        if send_btn:
                            await send_btn.click()
                            logger.info(f"✅ Ответ на сообщение отправлен")
                    
                    await asyncio.sleep(2)
                    await self.page.go_back()
                    
                except Exception as e:
                    logger.error(f"Ошибка ответа: {e}")
                    
        except Exception as e:
            logger.error(f"Ошибка проверки сообщений: {e}")
