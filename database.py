# database.py

import aiosqlite

DB_NAME = "posts.db"

async def init_db():
    """Создание таблицы, если её нет"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                text TEXT,
                file_id TEXT,
                file_type TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)
        await db.commit()

async def add_post(user_id: int, username: str, text: str, file_id: str, file_type: str) -> int:
    """Добавление поста в базу"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "INSERT INTO posts (user_id, username, text, file_id, file_type) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, text, file_id, file_type)
        )
        await db.commit()
        return cursor.lastrowid

async def get_post(post_id: int):
    """Получение поста по ID"""
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT * FROM posts WHERE id = ?", (post_id,))
        return await cursor.fetchone()

async def update_status(post_id: int, status: str):
    """Обновление статуса поста"""
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE posts SET status = ? WHERE id = ?", (status, post_id))
        await db.commit()
