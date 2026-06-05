import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename


app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey_replace_in_production')

UPLOAD_FOLDER = 'static/avatars'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    conn = sqlite3.connect('instance/careervibe.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.before_request
def check_valid_session():
    if 'user_id' in session:
        db = get_db()
        user = db.execute('SELECT id FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        db.close()
        if not user:
            session.pop('user_id', None)

@app.context_processor
def inject_user():
    data = {'user_id': None, 'user_email': None, 'user_nickname': None, 'user_avatar': None}
    if 'user_id' in session:
        db = get_db()
        user = db.execute('SELECT id, email, nickname, avatar FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        db.close()
        if user:
            data['user_id'] = user['id']
            data['user_email'] = user['email']
            data['user_nickname'] = user['nickname']
            data['user_avatar'] = user['avatar']
    return data

def dict_from_row(row):
    """Преобразует sqlite3.Row в обычный словарь."""
    return {key: row[key] for key in row.keys()}

@app.route('/')
def index():
    sort = request.args.get('sort', 'new')
    db = get_db()
    if sort == 'votes':
        rows = db.execute('''
            SELECT q.*, u.email, u.nickname, u.avatar,
                (SELECT COUNT(*) FROM answers WHERE question_id = q.id) as answer_count
            FROM questions q JOIN users u ON q.user_id = u.id
            ORDER BY q.votes DESC, q.created_at DESC
        ''').fetchall()
    else:
        rows = db.execute('''
            SELECT q.*, u.email, u.nickname, u.avatar,
                (SELECT COUNT(*) FROM answers WHERE question_id = q.id) as answer_count
            FROM questions q JOIN users u ON q.user_id = u.id
            ORDER BY q.created_at DESC
        ''').fetchall()

    questions = []
    for row in rows:
        q = dict_from_row(row)
        tags = db.execute(
            'SELECT t.name FROM tags t JOIN question_tags qt ON t.id = qt.tag_id WHERE qt.question_id = ?',
            (q['id'],)).fetchall()
        q['tags'] = [t['name'] for t in tags]
        best = db.execute('SELECT 1 FROM answers WHERE question_id = ? AND is_best = 1', (q['id'],)).fetchone()
        q['has_best_answer'] = best is not None
        questions.append(q)

    # Активные пользователи (топ-4 по сумме вопросов и ответов)
    active_rows = db.execute('''
        SELECT u.id, u.email, u.nickname, u.avatar,
               (SELECT COUNT(*) FROM questions WHERE user_id = u.id) +
               (SELECT COUNT(*) FROM answers WHERE user_id = u.id) as activity
        FROM users u
        ORDER BY activity DESC
        LIMIT 4
    ''').fetchall()
    active_users = [dict_from_row(u) for u in active_rows]

    # Популярные теги (топ-5 по количеству использований)
    tag_rows = db.execute('''
        SELECT t.name, COUNT(qt.question_id) as count
        FROM tags t
        JOIN question_tags qt ON t.id = qt.tag_id
        GROUP BY t.id
        ORDER BY count DESC
        LIMIT 5
    ''').fetchall()
    popular_tags = [dict_from_row(t) for t in tag_rows]

    db.close()
    return render_template('index.html',
                           questions=questions,
                           current_sort=sort,
                           active_users=active_users,
                           popular_tags=popular_tags)

@app.route('/ask', methods=['GET', 'POST'])
def ask_question():
    if 'user_id' not in session:
        flash('Войдите, чтобы задать вопрос.', 'error')
        return redirect(url_for('login'))
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        tags_str = request.form.get('tags', '')
        if not title or not content:
            flash('Заголовок и текст обязательны.', 'error')
            return redirect(url_for('ask_question'))
        db = get_db()
        cursor = db.cursor()
        cursor.execute('INSERT INTO questions (title, content, user_id) VALUES (?, ?, ?)',
                       (title, content, session['user_id']))
        qid = cursor.lastrowid
        if tags_str:
            for tag_name in [t.strip().lower() for t in tags_str.split(',') if t.strip()]:
                cursor.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)', (tag_name,))
                cursor.execute('SELECT id FROM tags WHERE name = ?', (tag_name,))
                tag = cursor.fetchone()
                if tag:
                    cursor.execute('INSERT OR IGNORE INTO question_tags (question_id, tag_id) VALUES (?, ?)',
                                   (qid, tag['id']))
        db.commit()
        db.close()
        flash('Вопрос создан.', 'success')
        return redirect(url_for('question_detail', question_id=qid))
    return render_template('ask_question.html')

@app.route('/question/<int:question_id>')
def question_detail(question_id):
    db = get_db()
    db.execute('UPDATE questions SET views = views + 1 WHERE id = ?', (question_id,))
    db.commit()
    row = db.execute('''
        SELECT q.*, u.email, u.nickname FROM questions q JOIN users u ON q.user_id = u.id WHERE q.id = ?
    ''', (question_id,)).fetchone()
    if not row:
        db.close()
        abort(404)
    question = dict_from_row(row)
    answers_rows = db.execute('''
        SELECT a.*, u.email, u.nickname FROM answers a JOIN users u ON a.user_id = u.id
        WHERE a.question_id = ? ORDER BY a.is_best DESC, a.votes DESC, a.created_at
    ''', (question_id,)).fetchall()
    answers = [dict_from_row(r) for r in answers_rows]
    tags = db.execute('''
        SELECT t.name, COUNT(qt.question_id) as popularity FROM tags t
        JOIN question_tags qt ON t.id = qt.tag_id WHERE qt.question_id = ? GROUP BY t.id
    ''', (question_id,)).fetchall()
    tags = [dict_from_row(t) for t in tags]
    user_vote = None
    if 'user_id' in session:
        v = db.execute('SELECT vote FROM question_votes WHERE user_id=? AND question_id=?',
                       (session['user_id'], question_id)).fetchone()
        if v:
            user_vote = v['vote']
    db.close()
    return render_template('question_detail.html', question=question, answers=answers, tags=tags, user_vote=user_vote)

@app.route('/question/<int:question_id>/edit', methods=['GET', 'POST'])
def edit_question(question_id):
    if 'user_id' not in session:
        flash('Войдите.', 'error')
        return redirect(url_for('login'))
    db = get_db()
    q = db.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()
    if not q or q['user_id'] != session['user_id']:
        db.close()
        abort(403)
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        tags_str = request.form.get('tags', '')
        if not title or not content:
            flash('Заполните поля.', 'error')
            return redirect(url_for('edit_question', question_id=question_id))

        # Разбор тегов
        tag_names = [t.strip().lower() for t in tags_str.split(',') if t.strip()]

        # Валидация тегов
        if len(tag_names) > 7:
            flash('Нельзя добавить больше 7 тегов. Удалите лишние.', 'error')
            return redirect(url_for('edit_question', question_id=question_id))

        for tag_name in tag_names:
            if len(tag_name) > 20:
                flash(f'Тег "{tag_name[:20]}" не может быть длиннее 20 символов.', 'error')
                return redirect(url_for('edit_question', question_id=question_id))

        db.execute('UPDATE questions SET title=?, content=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                   (title, content, question_id))
        db.execute('DELETE FROM question_tags WHERE question_id=?', (question_id,))

        for tag_name in tag_names:
            db.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)', (tag_name,))
            # Исправление: сохраняем результат execute в переменную и вызываем fetchone() на нём
            cursor = db.execute('SELECT id FROM tags WHERE name=?', (tag_name,))
            tag = cursor.fetchone()
            if tag:
                db.execute('INSERT OR IGNORE INTO question_tags (question_id, tag_id) VALUES (?,?)',
                           (question_id, tag['id']))
        db.commit()
        db.close()
        flash('Вопрос обновлён.', 'success')
        return redirect(url_for('question_detail', question_id=question_id))

    cur_tags = db.execute('SELECT t.name FROM tags t JOIN question_tags qt ON t.id=qt.tag_id WHERE qt.question_id=?',
                          (question_id,)).fetchall()
    tags_str = ', '.join([t['name'] for t in cur_tags])
    db.close()
    return render_template('edit_question.html', question=q, tags_str=tags_str)

@app.route('/question/<int:question_id>/delete', methods=['POST'])
def delete_question(question_id):
    if 'user_id' not in session:
        flash('Войдите.', 'error')
        return redirect(url_for('login'))
    db = get_db()
    q = db.execute('SELECT user_id FROM questions WHERE id=?', (question_id,)).fetchone()
    if not q or q['user_id'] != session['user_id']:
        db.close()
        abort(403)
    db.execute('DELETE FROM questions WHERE id=?', (question_id,))
    db.commit()
    db.close()
    flash('Вопрос удалён.', 'success')
    return redirect(url_for('index'))

@app.route('/question/<int:question_id>/vote', methods=['POST'])
def vote_question(question_id):
    if 'user_id' not in session:
        return {'error': 'Auth required'}, 401
    vote_value = 1 if request.form.get('vote_type') == 'up' else -1
    db = get_db()
    existing = db.execute('SELECT vote FROM question_votes WHERE user_id=? AND question_id=?',
                          (session['user_id'], question_id)).fetchone()
    if existing:
        if existing['vote'] == vote_value:
            db.execute('DELETE FROM question_votes WHERE user_id=? AND question_id=?',
                       (session['user_id'], question_id))
            db.execute('UPDATE questions SET votes = votes - ? WHERE id=?', (vote_value, question_id))
        else:
            db.execute('UPDATE question_votes SET vote=? WHERE user_id=? AND question_id=?',
                       (vote_value, session['user_id'], question_id))
            db.execute('UPDATE questions SET votes = votes + ? WHERE id=?', (vote_value * 2, question_id))
    else:
        db.execute('INSERT INTO question_votes (user_id, question_id, vote) VALUES (?,?,?)',
                   (session['user_id'], question_id, vote_value))
        db.execute('UPDATE questions SET votes = votes + ? WHERE id=?', (vote_value, question_id))
    db.commit()
    new = db.execute('SELECT votes FROM questions WHERE id=?', (question_id,)).fetchone()
    db.close()
    return {'votes': new['votes']}

@app.route('/answer/<int:question_id>/add', methods=['POST'])
def add_answer(question_id):
    if 'user_id' not in session:
        flash('Войдите, чтобы ответить.', 'error')
        return redirect(url_for('login'))
    content = request.form.get('content')
    if not content:
        flash('Текст ответа не может быть пустым.', 'error')
        return redirect(url_for('question_detail', question_id=question_id))
    db = get_db()
    db.execute('INSERT INTO answers (content, question_id, user_id) VALUES (?,?,?)',
               (content, question_id, session['user_id']))
    db.commit()
    db.close()
    flash('Ответ добавлен.', 'success')
    return redirect(url_for('question_detail', question_id=question_id))

@app.route('/answer/<int:answer_id>/edit', methods=['GET', 'POST'])
def edit_answer(answer_id):
    if 'user_id' not in session:
        flash('Войдите.', 'error')
        return redirect(url_for('login'))
    db = get_db()
    ans = db.execute('SELECT * FROM answers WHERE id=?', (answer_id,)).fetchone()
    if not ans or ans['user_id'] != session['user_id']:
        db.close()
        abort(403)
    if request.method == 'POST':
        content = request.form.get('content')
        if not content:
            flash('Текст обязателен.', 'error')
            return redirect(url_for('edit_answer', answer_id=answer_id))
        db.execute('UPDATE answers SET content=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                   (content, answer_id))
        db.commit()
        db.close()
        flash('Ответ обновлён.', 'success')
        return redirect(url_for('question_detail', question_id=ans['question_id']))
    db.close()
    return render_template('edit_answer.html', answer=ans)

@app.route('/answer/<int:answer_id>/delete', methods=['POST'])
def delete_answer(answer_id):
    if 'user_id' not in session:
        flash('Войдите.', 'error')
        return redirect(url_for('login'))
    db = get_db()
    ans = db.execute('SELECT * FROM answers WHERE id=?', (answer_id,)).fetchone()
    if not ans or ans['user_id'] != session['user_id']:
        db.close()
        abort(403)
    qid = ans['question_id']
    db.execute('DELETE FROM answers WHERE id=?', (answer_id,))
    db.commit()
    db.close()
    flash('Ответ удалён.', 'success')
    return redirect(url_for('question_detail', question_id=qid))

@app.route('/answer/<int:answer_id>/vote', methods=['POST'])
def vote_answer(answer_id):
    if 'user_id' not in session:
        return {'error': 'Auth required'}, 401
    vote_value = 1 if request.form.get('vote_type') == 'up' else -1
    db = get_db()
    existing = db.execute('SELECT vote FROM answer_votes WHERE user_id=? AND answer_id=?',
                          (session['user_id'], answer_id)).fetchone()
    if existing:
        if existing['vote'] == vote_value:
            db.execute('DELETE FROM answer_votes WHERE user_id=? AND answer_id=?',
                       (session['user_id'], answer_id))
            db.execute('UPDATE answers SET votes = votes - ? WHERE id=?', (vote_value, answer_id))
        else:
            db.execute('UPDATE answer_votes SET vote=? WHERE user_id=? AND answer_id=?',
                       (vote_value, session['user_id'], answer_id))
            db.execute('UPDATE answers SET votes = votes + ? WHERE id=?', (vote_value * 2, answer_id))
    else:
        db.execute('INSERT INTO answer_votes (user_id, answer_id, vote) VALUES (?,?,?)',
                   (session['user_id'], answer_id, vote_value))
        db.execute('UPDATE answers SET votes = votes + ? WHERE id=?', (vote_value, answer_id))
    db.commit()
    new = db.execute('SELECT votes FROM answers WHERE id=?', (answer_id,)).fetchone()
    db.close()
    return {'votes': new['votes']}

@app.route('/answer/<int:answer_id>/best', methods=['POST'])
def mark_best_answer(answer_id):
    if 'user_id' not in session:
        flash('Войдите.', 'error')
        return redirect(url_for('login'))
    db = get_db()
    ans = db.execute('SELECT * FROM answers WHERE id=?', (answer_id,)).fetchone()
    if not ans:
        db.close()
        abort(404)
    q = db.execute('SELECT user_id FROM questions WHERE id=?', (ans['question_id'],)).fetchone()
    if q['user_id'] != session['user_id']:
        db.close()
        flash('Только автор вопроса может отметить лучший ответ.', 'error')
        return redirect(url_for('question_detail', question_id=ans['question_id']))
    db.execute('UPDATE answers SET is_best = 0 WHERE question_id=?', (ans['question_id'],))
    db.execute('UPDATE answers SET is_best = 1 WHERE id=?', (answer_id,))
    db.commit()
    db.close()
    flash('Лучший ответ отмечен.', 'success')
    return redirect(url_for('question_detail', question_id=ans['question_id']))

@app.route('/tag/<tag_name>')
def tag_questions(tag_name):
    db = get_db()
    tag = db.execute('SELECT id FROM tags WHERE name=?', (tag_name,)).fetchone()
    if not tag:
        db.close()
        abort(404)
    rows = db.execute('''
        SELECT q.*, u.email, u.nickname,
               (SELECT COUNT(*) FROM answers WHERE question_id = q.id) as answer_count
        FROM questions q JOIN users u ON q.user_id = u.id
        JOIN question_tags qt ON q.id = qt.question_id
        WHERE qt.tag_id = ? ORDER BY q.created_at DESC
    ''', (tag['id'],)).fetchall()
    questions = []
    for row in rows:
        q = dict_from_row(row)
        tgs = db.execute('SELECT t.name FROM tags t JOIN question_tags qt ON t.id=qt.tag_id WHERE qt.question_id=?',
                         (q['id'],)).fetchall()
        q['tags'] = [t['name'] for t in tgs]
        questions.append(q)
    db.close()
    return render_template('tag_questions.html', tag_name=tag_name, questions=questions)

@app.route('/profile/<int:user_id>')
def profile(user_id):
    db = get_db()
    user = db.execute('SELECT id, email, nickname, avatar, created_at FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        db.close()
        abort(404)
    user_dict = dict_from_row(user)
    questions_rows = db.execute('''
        SELECT q.*, (SELECT COUNT(*) FROM answers WHERE question_id=q.id) as answer_count
        FROM questions q WHERE q.user_id = ? ORDER BY q.created_at DESC
    ''', (user_id,)).fetchall()
    questions = [dict_from_row(r) for r in questions_rows]
    answers_rows = db.execute('''
        SELECT a.*, q.title as question_title, q.id as question_id
        FROM answers a JOIN questions q ON a.question_id = q.id
        WHERE a.user_id = ? ORDER BY a.created_at DESC
    ''', (user_id,)).fetchall()
    answers = [dict_from_row(r) for r in answers_rows]
    db.close()
    return render_template('profile.html', user=user_dict, questions=questions, answers=answers)

@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        flash('Войдите, чтобы редактировать профиль.', 'error')
        return redirect(url_for('login'))
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip() or None
        avatar = request.files.get('avatar')
        if avatar and allowed_file(avatar.filename):
            if user['avatar']:
                old = os.path.join(app.config['UPLOAD_FOLDER'], user['avatar'])
                if os.path.exists(old):
                    os.remove(old)
            filename = f"user_{session['user_id']}_{secure_filename(avatar.filename)}"
            avatar.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            db.execute('UPDATE users SET nickname=?, avatar=? WHERE id=?', (nickname, filename, session['user_id']))
        else:
            db.execute('UPDATE users SET nickname=? WHERE id=?', (nickname, session['user_id']))
        db.commit()
        db.close()
        flash('Профиль обновлён.', 'success')
        return redirect(url_for('profile', user_id=session['user_id']))
    db.close()
    return render_template('edit_profile.html', user=user)

@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return redirect(url_for('index'))
    db = get_db()
    like = f'%{q}%'
    rows = db.execute('''
        SELECT q.*, u.email, u.nickname,
               (SELECT COUNT(*) FROM answers WHERE question_id = q.id) as answer_count
        FROM questions q JOIN users u ON q.user_id = u.id
        WHERE q.title LIKE ? OR q.content LIKE ?
        ORDER BY q.created_at DESC
    ''', (like, like)).fetchall()
    questions = []
    for row in rows:
        qq = dict_from_row(row)
        tags = db.execute('SELECT t.name FROM tags t JOIN question_tags qt ON t.id=qt.tag_id WHERE qt.question_id=?',
                          (qq['id'],)).fetchall()
        qq['tags'] = [t['name'] for t in tags]
        questions.append(qq)
    db.close()
    return render_template('search.html', query=q, questions=questions)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'login':
            email = request.form.get('email')
            pwd = request.form.get('password')
            if not email or not pwd:
                flash('Заполните все поля.', 'error')
                return redirect(url_for('login'))
            db = get_db()
            user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            db.close()
            if user and check_password_hash(user['password_hash'], pwd):
                session['user_id'] = user['id']
                flash('Вход выполнен успешно.', 'success')
                return redirect(url_for('index'))
            flash('Неверный email или пароль.', 'error')
        elif action == 'register':
            email = request.form.get('email')
            pwd = request.form.get('password')
            conf = request.form.get('confirm_password')
            if not email or not pwd or not conf:
                flash('Заполните все поля.', 'error')
                return redirect(url_for('login'))
            if pwd != conf:
                flash('Пароли не совпадают.', 'error')
                return redirect(url_for('login'))
            if len(pwd) < 4:
                flash('Пароль не менее 4 символов.', 'error')
                return redirect(url_for('login'))
            pwd_hash = generate_password_hash(pwd)
            db = get_db()
            try:
                db.execute('INSERT INTO users (email, password_hash) VALUES (?, ?)', (email, pwd_hash))
                db.commit()
                flash('Регистрация успешна. Теперь войдите.', 'success')
            except sqlite3.IntegrityError:
                flash('Email уже зарегистрирован.', 'error')
            finally:
                db.close()
        return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash('Вы вышли из аккаунта.', 'info')
    return redirect(url_for('index'))

@app.route('/mission')
def mission():
    return render_template('mission.html')

if __name__ == '__main__':
    app.run(debug=True)