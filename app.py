import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey_replace_in_production')


def get_db() -> sqlite3.Connection:
    """
    Возвращает соединение с базой данных SQLite.
    Использует row_factory = sqlite3.Row для доступа по имени колонки.
    """
    conn = sqlite3.connect('instance/careervibe.db')
    conn.row_factory = sqlite3.Row
    return conn


@app.before_request
def check_valid_session() -> None:
    """
    Проверяет перед каждым запросом, существует ли пользователь с user_id из сессии.
    Если пользователь удалён из БД, сессия очищается.
    """
    if 'user_id' in session:
        db = get_db()
        user = db.execute('SELECT id FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        db.close()
        if not user:
            session.pop('user_id', None)


@app.context_processor
def inject_user() -> dict:
    """
    Контекстный процессор. Передаёт в каждый шаблон:
    - user_email: email текущего пользователя (или None)
    - user_id: id текущего пользователя (или None)
    """
    user_email = None
    user_id = None
    if 'user_id' in session:
        db = get_db()
        user = db.execute('SELECT id, email FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        db.close()
        if user:
            user_id = user['id']
            user_email = user['email']
    return {'user_email': user_email, 'user_id': user_id}


@app.route('/')
def index() -> str:
    """Главная страница — лендинг с лентой вопросов."""
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login() -> str:
    """
    Страница входа и регистрации.
    GET: отображает формы.
    POST: обрабатывает вход (action=login) или регистрацию (action=register).
    """
    if 'user_id' in session:
        return redirect(url_for('index'))

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'login':
            email = request.form.get('email')
            password = request.form.get('password')
            if not email or not password:
                flash('Заполните все поля.', 'error')
                return redirect(url_for('login'))

            db = get_db()
            user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            db.close()

            if user and check_password_hash(user['password_hash'], password):
                session['user_id'] = user['id']
                flash('Вход выполнен успешно.', 'success')
                return redirect(url_for('index'))
            flash('Неверный email или пароль.', 'error')
            return redirect(url_for('login'))

        elif action == 'register':
            email = request.form.get('email')
            password = request.form.get('password')
            confirm = request.form.get('confirm_password')

            if not email or not password or not confirm:
                flash('Заполните все поля.', 'error')
                return redirect(url_for('login'))
            if password != confirm:
                flash('Пароли не совпадают.', 'error')
                return redirect(url_for('login'))
            if len(password) < 4:
                flash('Пароль должен содержать не менее 4 символов.', 'error')
                return redirect(url_for('login'))

            password_hash = generate_password_hash(password)

            db = get_db()
            try:
                db.execute(
                    'INSERT INTO users (email, password_hash) VALUES (?, ?)',
                    (email, password_hash)
                )
                db.commit()
                flash('Регистрация прошла успешно. Теперь вы можете войти.', 'success')
            except sqlite3.IntegrityError:
                flash('Пользователь с таким email уже существует.', 'error')
            finally:
                db.close()
            return redirect(url_for('login'))

    return render_template('login.html')


@app.route('/logout')
def logout() -> str:
    """Завершение сессии — удаляет user_id и перенаправляет на главную."""
    session.pop('user_id', None)
    flash('Вы вышли из аккаунта.', 'info')
    return redirect(url_for('index'))


@app.route('/mission')
def mission() -> str:
    """Статическая страница «Миссия»."""
    return render_template('mission.html')


if __name__ == '__main__':
    app.run(debug=True)