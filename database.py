import aiosqlite
import json

DB_PATH = "tiktok_bot.db"

async def init_db():
    """Инициализация БД"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT NOT NULL,
                password TEXT NOT NULL,
                cookies TEXT,
                active INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP
            )
        ''')
        await db.commit()

async def add_account(telegram_id, username, password):
    """Добавление аккаунта"""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO accounts (telegram_id, username, password) VALUES (?, ?, ?)",
            (telegram_id, username, password)
        )
        await db.commit()
        return cursor.lastrowid

async def get_accounts_by_user(telegram_id):
    """Аккаунты пользователя"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, username, active, created_at FROM accounts WHERE telegram_id = ? ORDER BY id DESC",
            (telegram_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"id": r[0], "username": r[1], "active": bool(r[2]), "created_at": r[3]} for r in rows]

async def get_all_accounts():
    """Все аккаунты"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, telegram_id, username, active, created_at FROM accounts ORDER BY id DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [{"id": r[0], "telegram_id": r[1], "username": r[2], "active": bool(r[3]), "created_at": r[4]} for r in rows]

async def get_account_by_id(account_id):
    """Получить аккаунт по ID"""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, telegram_id, username, password, cookies, active, created_at FROM accounts WHERE id = ?",
            (account_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "id": row[0],
                    "telegram_id": row[1],
                    "username": row[2],
                    "password": row[3],
                    "cookies": row[4],
                    "active": bool(row[5]),
                    "created_at": row[6]
                }
            return None

async def update_account_status(account_id, active):
    """Обновить статус аккаунта"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET active = ? WHERE id = ?",
            (1 if active else 0, account_id)
        )
        await db.commit()

async def update_account_cookies(account_id, cookies):
    """Обновить куки аккаунта"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET cookies = ?, last_active = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(cookies), account_id)
        )
        await db.commit()

async def delete_account(account_id):
    """Удалить аккаунт"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        await db.commit()
