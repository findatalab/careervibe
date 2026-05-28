import os
import sqlite3


def init_db() -> None:
    """
    Создаёт папку instance (если отсутствует) и таблицу users в базе данных careervibe.db.
    Таблица содержит:
    - id: уникальный идентификатор
    - email: уникальный, не может быть пустым
    - password_hash: хеш пароля
    - created_at: дата регистрации (автоматически)
    """
    os.makedirs('instance', exist_ok=True)

    conn = sqlite3.connect('instance/careervibe.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print("База данных и таблица users успешно созданы.")


if __name__ == '__main__':
    init_db()