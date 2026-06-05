import os
import sqlite3


def init_db() -> None:
    """
    Создаёт папку instance и все необходимые таблицы для MVP:
    - users (уже была)
    - questions
    - answers
    - tags
    - question_tags
    - question_votes
    - answer_votes
    """
    os.makedirs('instance', exist_ok=True)
    conn = sqlite3.connect('instance/careervibe.db')
    cursor = conn.cursor()

    # Пользователи
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            nickname TEXT,
            avatar TEXT,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Вопросы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            views INTEGER DEFAULT 0,
            votes INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    # Ответы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            question_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            votes INTEGER DEFAULT 0,
            is_best BOOLEAN DEFAULT 0,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    ''')

    # Теги
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL
        )
    ''')

    # Связь вопросов с тегами (многие ко многим)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS question_tags (
            question_id INTEGER,
            tag_id INTEGER,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (question_id, tag_id)
        )
    ''')

    # Голоса за вопросы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS question_votes (
            user_id INTEGER,
            question_id INTEGER,
            vote INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, question_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        )
    ''')

    # Голоса за ответы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS answer_votes (
            user_id INTEGER,
            answer_id INTEGER,
            vote INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, answer_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (answer_id) REFERENCES answers(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()
    conn.close()
    print("База данных и все таблицы успешно созданы.")


if __name__ == '__main__':
    init_db()
