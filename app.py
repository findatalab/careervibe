# ======================== ИМПОРТЫ ========================
import os
import sqlite3
import re
import time
import random
import json
import math
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, send_from_directory, \
    jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import markdown
from bleach.sanitizer import Cleaner
from flask_babel import Babel, gettext as _

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey_replace_in_production')

# ======================== НАСТРОЙКА Babel ========================
app.config['BABEL_DEFAULT_LOCALE'] = 'ru'
app.config['BABEL_DEFAULT_TIMEZONE'] = 'UTC'
babel = Babel(app)


def get_locale():
    if 'lang' in session:
        return session['lang']
    return request.accept_languages.best_match(['ru', 'en'])


babel.init_app(app, locale_selector=get_locale)

# ======================== НАСТРОЙКИ ЗАГРУЗКИ ========================
UPLOAD_FOLDER = 'static/avatars'
FILE_UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'zip', 'rar', 'doc', 'docx', 'xls', 'xlsx', 'mp4',
                      'webm', 'mov', 'avi', 'mp3', 'wav'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['FILE_UPLOAD_FOLDER'] = FILE_UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(FILE_UPLOAD_FOLDER, exist_ok=True)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_db():
    conn = sqlite3.connect('instance/careervibe.db')
    conn.row_factory = sqlite3.Row
    return conn


def render_markdown(text):
    if not text:
        return ''
    html = markdown.markdown(text, extensions=['extra', 'codehilite', 'tables', 'fenced_code'])
    cleaner = Cleaner(tags=[
        'p', 'br', 'strong', 'em', 'u', 'strike', 'code', 'pre', 'blockquote',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'a', 'img',
        'table', 'thead', 'tbody', 'tr', 'th', 'td', 'div', 'span'
    ], attributes={
        'a': ['href', 'title'],
        'img': ['src', 'alt', 'title'],
        'div': ['class'],
        'span': ['class']
    }, strip=False)
    return cleaner.clean(html)


# ======================== ПРОВЕРКА EMAIL ========================
EMAIL_REGEX = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
ALLOWED_DOMAINS = ('.ru',)


def is_valid_email(email):
    if not re.match(EMAIL_REGEX, email):
        return False
    if not any(email.lower().endswith(domain) for domain in ALLOWED_DOMAINS):
        return False
    return True


# ======================== КОНТЕКСТНЫЙ ПРОЦЕССОР ========================
@app.context_processor
def inject_user():
    data = {
        'user_id': None,
        'user_nickname': None,
        'user_avatar': None,
        'hero_title': _('Карьерный компас для амбициозных'),
        'hero_subtitle': _(
            'Присоединяйтесь к сообществу профессионалов, чтобы находить ответы, делиться опытом и строить успешную карьеру')
    }
    if 'user_id' in session:
        db = get_db()
        user = db.execute('SELECT id, nickname, avatar FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        db.close()
        if user:
            data['user_id'] = user['id']
            data['user_nickname'] = user['nickname']
            data['user_avatar'] = user['avatar']
    return data


@app.before_request
def check_valid_session():
    if 'user_id' in session:
        db = get_db()
        user = db.execute('SELECT id FROM users WHERE id = ?', (session['user_id'],)).fetchone()
        db.close()
        if not user:
            session.pop('user_id', None)


def dict_from_row(row):
    return {key: row[key] for key in row.keys()}


# ======================== РОУТЫ ========================

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    sort = request.args.get('sort', 'new')

    db = get_db()

    total_count = db.execute('SELECT COUNT(*) as count FROM questions').fetchone()['count']
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 1

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page

    if sort == 'votes':
        rows = db.execute('''
            SELECT q.*, u.nickname, u.avatar,
                (SELECT COUNT(*) FROM answers WHERE question_id = q.id) as answer_count
            FROM questions q JOIN users u ON q.user_id = u.id
            ORDER BY q.votes DESC, q.created_at DESC
            LIMIT ? OFFSET ?
        ''', (per_page, offset)).fetchall()
    else:
        rows = db.execute('''
            SELECT q.*, u.nickname, u.avatar,
                (SELECT COUNT(*) FROM answers WHERE question_id = q.id) as answer_count
            FROM questions q JOIN users u ON q.user_id = u.id
            ORDER BY q.created_at DESC
            LIMIT ? OFFSET ?
        ''', (per_page, offset)).fetchall()

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

    active_rows = db.execute('''
        SELECT u.id, u.nickname, u.avatar,
               (SELECT COUNT(*) FROM questions WHERE user_id = u.id) +
               (SELECT COUNT(*) FROM answers WHERE user_id = u.id) as activity
        FROM users u
        ORDER BY activity DESC
        LIMIT 4
    ''').fetchall()
    active_users = [dict_from_row(u) for u in active_rows]

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
                           popular_tags=popular_tags,
                           page=page,
                           total_pages=total_pages,
                           total_count=total_count,
                           per_page=per_page)


@app.route('/ask', methods=['GET', 'POST'])
def ask_question():
    if 'user_id' not in session:
        flash(_('Войдите, чтобы задать вопрос.'), 'error')
        return redirect(url_for('login'))
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        tags_str = request.form.get('tags', '')
        if not title or not content:
            flash(_('Заголовок и текст обязательны.'), 'error')
            return redirect(url_for('ask_question'))
        db = get_db()
        cursor = db.cursor()
        cursor.execute('INSERT INTO questions (title, content, user_id) VALUES (?, ?, ?)',
                       (title, content, session['user_id']))
        qid = cursor.lastrowid

        if tags_str:
            for tag_name in [t.strip().lower() for t in tags_str.split(',') if t.strip()]:
                if tag_name.startswith('#'):
                    tag_name = tag_name[1:]
                if len(tag_name) > 20:
                    continue
                cursor.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)', (tag_name,))
                cursor.execute('SELECT id FROM tags WHERE name = ?', (tag_name,))
                tag = cursor.fetchone()
                if tag:
                    cursor.execute('INSERT OR IGNORE INTO question_tags (question_id, tag_id) VALUES (?, ?)',
                                   (qid, tag['id']))

        files = request.files.getlist('attachments')
        for file in files:
            if file and file.filename and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                name, ext = os.path.splitext(original_filename)
                unique = f"{qid}_{session['user_id']}_{int(time.time())}_{random.randint(1000, 9999)}{ext}"
                unique = re.sub(r'[^a-zA-Z0-9_.-]', '_', unique)
                filepath = os.path.join(app.config['FILE_UPLOAD_FOLDER'], unique)
                file.save(filepath)
                cursor.execute('''
                    INSERT INTO attachments (question_id, filename, original_filename, filepath, user_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (qid, unique, original_filename, unique, session['user_id']))

        db.commit()
        db.close()
        flash(_('Вопрос создан.'), 'success')
        return redirect(url_for('question_detail', question_id=qid))
    return render_template('ask_question.html')


@app.route('/question/<int:question_id>')
def question_detail(question_id):
    db = get_db()
    db.execute('UPDATE questions SET views = views + 1 WHERE id = ?', (question_id,))
    db.commit()
    row = db.execute('''
        SELECT q.*, u.nickname, u.avatar FROM questions q JOIN users u ON q.user_id = u.id WHERE q.id = ?
    ''', (question_id,)).fetchone()
    if not row:
        db.close()
        abort(404)
    question = dict_from_row(row)
    question['content_html'] = render_markdown(question['content'])

    answers_rows = db.execute('''
        SELECT a.*, u.nickname, u.avatar FROM answers a JOIN users u ON a.user_id = u.id
        WHERE a.question_id = ? AND a.parent_answer_id IS NULL
        ORDER BY a.is_best DESC, a.votes DESC, a.created_at
    ''', (question_id,)).fetchall()
    answers = []
    for ans_row in answers_rows:
        ans = dict_from_row(ans_row)
        ans['content_html'] = render_markdown(ans['content'])
        children = db.execute('''
            SELECT a.*, u.nickname, u.avatar FROM answers a JOIN users u ON a.user_id = u.id
            WHERE a.parent_answer_id = ? ORDER BY a.created_at
        ''', (ans['id'],)).fetchall()
        ans['children'] = [dict_from_row(child) for child in children]
        for child in ans['children']:
            child['content_html'] = render_markdown(child['content'])
            child['attachments'] = db.execute('SELECT * FROM attachments WHERE answer_id = ?',
                                              (child['id'],)).fetchall()
            child['attachments'] = [dict_from_row(a) for a in child['attachments']]
        ans['attachments'] = db.execute('SELECT * FROM attachments WHERE answer_id = ?', (ans['id'],)).fetchall()
        ans['attachments'] = [dict_from_row(a) for a in ans['attachments']]
        answers.append(ans)

    tags = db.execute('''
        SELECT t.name FROM tags t
        JOIN question_tags qt ON t.id = qt.tag_id WHERE qt.question_id = ?
    ''', (question_id,)).fetchall()
    tags = [dict_from_row(t) for t in tags]

    attachments = db.execute('SELECT * FROM attachments WHERE question_id = ? AND answer_id IS NULL',
                             (question_id,)).fetchall()
    attachments = [dict_from_row(a) for a in attachments]

    user_vote = None
    if 'user_id' in session:
        v = db.execute('SELECT vote FROM question_votes WHERE user_id=? AND question_id=?',
                       (session['user_id'], question_id)).fetchone()
        if v:
            user_vote = v['vote']

    user_votes_for_answers = {}
    if 'user_id' in session:
        all_answer_ids = []
        for a in answers:
            all_answer_ids.append(a['id'])
            for c in a.get('children', []):
                all_answer_ids.append(c['id'])
        for aid in all_answer_ids:
            v = db.execute('SELECT vote FROM answer_votes WHERE user_id=? AND answer_id=?',
                           (session['user_id'], aid)).fetchone()
            user_votes_for_answers[aid] = v['vote'] if v else None

    db.close()
    return render_template('question_detail.html',
                           question=question,
                           answers=answers,
                           tags=tags,
                           attachments=attachments,
                           user_vote=user_vote,
                           user_votes_for_answers=user_votes_for_answers)


@app.route('/question/<int:question_id>/edit', methods=['GET', 'POST'])
def edit_question(question_id):
    if 'user_id' not in session:
        flash(_('Войдите.'), 'error')
        return redirect(url_for('login'))
    db = get_db()
    q = db.execute('SELECT * FROM questions WHERE id=?', (question_id,)).fetchone()
    if not q or q['user_id'] != session['user_id']:
        db.close()
        abort(403)

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        tags_str = request.form.get('tags', '')
        deleted_attachments = request.form.get('deleted_attachments', '')

        if not title or not content:
            flash(_('Заполните поля.'), 'error')
            return redirect(url_for('edit_question', question_id=question_id))

        tag_names = [t.strip().lower() for t in tags_str.split(',') if t.strip()]
        tag_names = [t[1:] if t.startswith('#') else t for t in tag_names]
        if len(tag_names) > 7:
            flash(_('Нельзя добавить больше 7 тегов.'), 'error')
            return redirect(url_for('edit_question', question_id=question_id))
        for tag_name in tag_names:
            if len(tag_name) > 20:
                flash(_(f'Тег "{tag_name[:20]}" не может быть длиннее 20 символов.'), 'error')
                return redirect(url_for('edit_question', question_id=question_id))

        if deleted_attachments:
            for att_id in deleted_attachments.split(','):
                att = db.execute('SELECT * FROM attachments WHERE id = ?', (att_id,)).fetchone()
                if att and att['user_id'] == session['user_id']:
                    filepath = os.path.join(app.config['FILE_UPLOAD_FOLDER'], att['filepath'])
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    db.execute('DELETE FROM attachments WHERE id = ?', (att_id,))

        db.execute('UPDATE questions SET title=?, content=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                   (title, content, question_id))
        db.execute('DELETE FROM question_tags WHERE question_id=?', (question_id,))
        for tag_name in tag_names:
            db.execute('INSERT OR IGNORE INTO tags (name) VALUES (?)', (tag_name,))
            cursor = db.execute('SELECT id FROM tags WHERE name=?', (tag_name,))
            tag = cursor.fetchone()
            if tag:
                db.execute('INSERT OR IGNORE INTO question_tags (question_id, tag_id) VALUES (?,?)',
                           (question_id, tag['id']))

        files = request.files.getlist('attachments')
        for file in files:
            if file and file.filename and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                name, ext = os.path.splitext(original_filename)
                unique = f"{question_id}_{session['user_id']}_{int(time.time())}_{random.randint(1000, 9999)}{ext}"
                unique = re.sub(r'[^a-zA-Z0-9_.-]', '_', unique)
                filepath = os.path.join(app.config['FILE_UPLOAD_FOLDER'], unique)
                file.save(filepath)
                db.execute('''
                    INSERT INTO attachments (question_id, filename, original_filename, filepath, user_id)
                    VALUES (?, ?, ?, ?, ?)
                ''', (question_id, unique, original_filename, unique, session['user_id']))

        db.commit()
        db.close()
        flash(_('Вопрос обновлён.'), 'success')
        return redirect(url_for('question_detail', question_id=question_id))

    cur_tags = db.execute('SELECT t.name FROM tags t JOIN question_tags qt ON t.id=qt.tag_id WHERE qt.question_id=?',
                          (question_id,)).fetchall()
    tags_str = ', '.join([t['name'] for t in cur_tags])
    attachments = db.execute('SELECT * FROM attachments WHERE question_id = ? AND answer_id IS NULL',
                             (question_id,)).fetchall()
    attachments = [dict_from_row(a) for a in attachments]
    db.close()
    return render_template('edit_question.html', question=q, tags_str=tags_str, attachments=attachments)


@app.route('/question/<int:question_id>/delete', methods=['POST'])
def delete_question(question_id):
    if 'user_id' not in session:
        flash(_('Войдите.'), 'error')
        return redirect(url_for('login'))
    db = get_db()
    q = db.execute('SELECT user_id FROM questions WHERE id=?', (question_id,)).fetchone()
    if not q or q['user_id'] != session['user_id']:
        db.close()
        abort(403)
    db.execute('DELETE FROM questions WHERE id=?', (question_id,))
    db.commit()
    db.close()
    flash(_('Вопрос удалён.'), 'success')
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
    current = db.execute('SELECT vote FROM question_votes WHERE user_id=? AND question_id=?',
                         (session['user_id'], question_id)).fetchone()
    user_vote = current['vote'] if current else 0
    db.close()
    return {'votes': new['votes'], 'user_vote': user_vote}


@app.route('/answer/<int:question_id>/add', methods=['POST'])
def add_answer(question_id):
    if 'user_id' not in session:
        flash(_('Войдите, чтобы ответить.'), 'error')
        return redirect(url_for('login'))
    content = request.form.get('content', '').strip()
    parent_id = request.form.get('parent_id')
    if not content:
        flash(_('Текст ответа не может быть пустым.'), 'error')
        return redirect(url_for('question_detail', question_id=question_id))
    db = get_db()
    cursor = db.cursor()
    cursor.execute('INSERT INTO answers (content, question_id, user_id, parent_answer_id) VALUES (?,?,?,?)',
                   (content, question_id, session['user_id'], parent_id if parent_id else None))
    answer_id = cursor.lastrowid
    files = request.files.getlist('attachments')
    for file in files:
        if file and file.filename and allowed_file(file.filename):
            original_filename = secure_filename(file.filename)
            name, ext = os.path.splitext(original_filename)
            unique = f"ans_{answer_id}_{session['user_id']}_{int(time.time())}_{random.randint(1000, 9999)}{ext}"
            unique = re.sub(r'[^a-zA-Z0-9_.-]', '_', unique)
            filepath = os.path.join(app.config['FILE_UPLOAD_FOLDER'], unique)
            file.save(filepath)
            cursor.execute('''
                INSERT INTO attachments (question_id, answer_id, filename, original_filename, filepath, user_id)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (question_id, answer_id, unique, original_filename, unique, session['user_id']))
    db.commit()
    db.close()
    flash(_('Ответ добавлен.'), 'success')
    return redirect(url_for('question_detail', question_id=question_id))


@app.route('/answer/<int:answer_id>/edit', methods=['GET', 'POST'])
def edit_answer(answer_id):
    if 'user_id' not in session:
        flash(_('Войдите.'), 'error')
        return redirect(url_for('login'))
    db = get_db()
    ans = db.execute('SELECT * FROM answers WHERE id=?', (answer_id,)).fetchone()
    if not ans or ans['user_id'] != session['user_id']:
        db.close()
        abort(403)

    if request.method == 'POST':
        content = request.form.get('content', '').strip()
        deleted_attachments = request.form.get('deleted_attachments', '')

        if not content:
            flash(_('Текст ответа не может быть пустым.'), 'error')
            return redirect(url_for('edit_answer', answer_id=answer_id))

        if deleted_attachments:
            for att_id in deleted_attachments.split(','):
                att = db.execute('SELECT * FROM attachments WHERE id = ?', (att_id,)).fetchone()
                if att and att['user_id'] == session['user_id']:
                    filepath = os.path.join(app.config['FILE_UPLOAD_FOLDER'], att['filepath'])
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    db.execute('DELETE FROM attachments WHERE id = ?', (att_id,))

        db.execute('UPDATE answers SET content=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
                   (content, answer_id))

        files = request.files.getlist('attachments')
        for file in files:
            if file and file.filename and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                name, ext = os.path.splitext(original_filename)
                unique = f"ans_{answer_id}_{session['user_id']}_{int(time.time())}_{random.randint(1000, 9999)}{ext}"
                unique = re.sub(r'[^a-zA-Z0-9_.-]', '_', unique)
                filepath = os.path.join(app.config['FILE_UPLOAD_FOLDER'], unique)
                file.save(filepath)
                db.execute('''
                    INSERT INTO attachments (question_id, answer_id, filename, original_filename, filepath, user_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (ans['question_id'], answer_id, unique, original_filename, unique, session['user_id']))

        db.commit()
        db.close()
        flash(_('Ответ обновлён.'), 'success')
        return redirect(url_for('question_detail', question_id=ans['question_id']))

    answer_attachments = db.execute('SELECT * FROM attachments WHERE answer_id = ?', (answer_id,)).fetchall()
    answer_attachments = [dict_from_row(a) for a in answer_attachments]
    db.close()
    return render_template('edit_answer.html', answer=ans, answer_attachments=answer_attachments)


@app.route('/answer/<int:answer_id>/delete', methods=['POST'])
def delete_answer(answer_id):
    if 'user_id' not in session:
        flash(_('Войдите.'), 'error')
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
    flash(_('Ответ удалён.'), 'success')
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
    current = db.execute('SELECT vote FROM answer_votes WHERE user_id=? AND answer_id=?',
                         (session['user_id'], answer_id)).fetchone()
    user_vote = current['vote'] if current else 0
    db.close()
    return {'votes': new['votes'], 'user_vote': user_vote}


@app.route('/answer/<int:answer_id>/best', methods=['POST'])
def mark_best_answer(answer_id):
    if 'user_id' not in session:
        flash(_('Войдите.'), 'error')
        return redirect(url_for('login'))
    db = get_db()
    ans = db.execute('SELECT * FROM answers WHERE id=?', (answer_id,)).fetchone()
    if not ans:
        db.close()
        abort(404)
    q = db.execute('SELECT user_id FROM questions WHERE id=?', (ans['question_id'],)).fetchone()
    if q['user_id'] != session['user_id']:
        db.close()
        flash(_('Только автор вопроса может отметить лучший ответ.'), 'error')
        return redirect(url_for('question_detail', question_id=ans['question_id']))
    db.execute('UPDATE answers SET is_best = 0 WHERE question_id=?', (ans['question_id'],))
    db.execute('UPDATE answers SET is_best = 1 WHERE id=?', (answer_id,))
    db.commit()
    db.close()
    flash(_('Лучший ответ отмечен.'), 'success')
    return redirect(url_for('question_detail', question_id=ans['question_id']))


@app.route('/attachment/<int:attachment_id>/delete', methods=['POST'])
def delete_attachment(attachment_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    db = get_db()
    att = db.execute('SELECT * FROM attachments WHERE id = ?', (attachment_id,)).fetchone()
    if not att:
        db.close()
        return jsonify({'error': 'Not found'}), 404
    if att['user_id'] != session['user_id']:
        db.close()
        return jsonify({'error': 'Forbidden'}), 403
    filepath = os.path.join(app.config['FILE_UPLOAD_FOLDER'], att['filepath'])
    if os.path.exists(filepath):
        os.remove(filepath)
    db.execute('DELETE FROM attachments WHERE id = ?', (attachment_id,))
    db.commit()
    db.close()
    return jsonify({'success': True})


@app.route('/tag/<tag_name>')
def tag_questions(tag_name):
    db = get_db()
    tag = db.execute('SELECT id FROM tags WHERE name=?', (tag_name,)).fetchone()
    if not tag:
        db.close()
        abort(404)
    rows = db.execute('''
        SELECT q.*, u.nickname,
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


@app.route('/tags')
def all_tags():
    db = get_db()
    total_tags = db.execute('SELECT COUNT(*) as count FROM tags').fetchone()['count']

    tag_rows = db.execute('''
        SELECT t.name, COUNT(qt.question_id) as count
        FROM tags t
        LEFT JOIN question_tags qt ON t.id = qt.tag_id
        GROUP BY t.id
        ORDER BY count DESC, t.name
        LIMIT 30
    ''').fetchall()
    tags = [dict_from_row(t) for t in tag_rows]
    db.close()
    return render_template('all_tags.html', tags=tags, total_tags=total_tags)


@app.route('/profile/<int:user_id>')
def profile(user_id):
    db = get_db()
    user = db.execute('SELECT id, nickname, avatar, bio, created_at FROM users WHERE id=?', (user_id,)).fetchone()
    if not user:
        db.close()
        abort(404)
    user_dict = dict_from_row(user)
    show_email = None
    if 'user_id' in session and session['user_id'] == user_id:
        email_row = db.execute('SELECT email FROM users WHERE id=?', (user_id,)).fetchone()
        show_email = email_row['email'] if email_row else None
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
    return render_template('profile.html', user=user_dict, questions=questions, answers=answers, show_email=show_email)


@app.route('/profile/edit', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        flash(_('Войдите, чтобы редактировать профиль.'), 'error')
        return redirect(url_for('login'))
    db = get_db()
    user = db.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()
        bio = request.form.get('bio', '').strip()[:500]
        if not nickname:
            flash(_('Никнейм обязателен.'), 'error')
            return redirect(url_for('edit_profile'))
        existing = db.execute('SELECT id FROM users WHERE nickname = ? AND id != ?',
                              (nickname, session['user_id'])).fetchone()
        if existing:
            flash(_('Этот никнейм уже занят.'), 'error')
            return redirect(url_for('edit_profile'))
        avatar = request.files.get('avatar')
        if avatar and allowed_file(avatar.filename):
            if user['avatar']:
                old = os.path.join(app.config['UPLOAD_FOLDER'], user['avatar'])
                if os.path.exists(old):
                    os.remove(old)
            filename = f"user_{session['user_id']}_{secure_filename(avatar.filename)}"
            avatar.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            db.execute('UPDATE users SET nickname=?, avatar=?, bio=? WHERE id=?',
                       (nickname, filename, bio, session['user_id']))
        else:
            db.execute('UPDATE users SET nickname=?, bio=? WHERE id=?',
                       (nickname, bio, session['user_id']))
        db.commit()
        db.close()
        flash(_('Профиль обновлён.'), 'success')
        return redirect(url_for('profile', user_id=session['user_id']))
    db.close()
    return render_template('edit_profile.html', user=user)


@app.route('/search')
def search():
    q = request.args.get('q', '').strip()
    if not q:
        return redirect(url_for('index'))
    db = get_db()
    if q.startswith('#'):
        tag_name = q[1:].strip()
        tag = db.execute('SELECT id FROM tags WHERE name LIKE ?', (f'%{tag_name}%',)).fetchone()
        if tag:
            rows = db.execute('''
                SELECT q.*, u.nickname,
                       (SELECT COUNT(*) FROM answers WHERE question_id = q.id) as answer_count
                FROM questions q JOIN users u ON q.user_id = u.id
                JOIN question_tags qt ON q.id = qt.question_id
                WHERE qt.tag_id = ?
                ORDER BY q.created_at DESC
            ''', (tag['id'],)).fetchall()
        else:
            rows = []
    else:
        like = f'%{q}%'
        rows = db.execute('''
            SELECT q.*, u.nickname,
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


# ======================== AJAX-АВТОДОПОЛНЕНИЕ ТЕГОВ ========================
@app.route('/api/tags/autocomplete')
def autocomplete_tags():
    query = request.args.get('q', '').strip().lower()
    if len(query) < 1:
        return jsonify([])
    db = get_db()
    rows = db.execute('SELECT name FROM tags WHERE name LIKE ? ORDER BY name LIMIT 10', (query + '%',)).fetchall()
    db.close()
    tags = [row['name'] for row in rows]
    return jsonify(tags)


# ======================== СМЕНА ЯЗЫКА ========================
@app.route('/set_language/<lang>')
def set_language(lang):
    if lang in ['ru', 'en']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))


# ======================== СТАТИЧЕСКИЕ СТРАНИЦЫ ========================
@app.route('/mission')
def mission():
    return render_template('mission.html')


@app.route('/help')
def help_page():
    return render_template('help.html')


@app.route('/rules')
def rules():
    return render_template('rules.html')


@app.route('/contacts')
def contacts():
    return render_template('contacts.html')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['FILE_UPLOAD_FOLDER'], filename)


# ======================== РЕГИСТРАЦИЯ / ЛОГИН ========================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'login':
            login_input = request.form.get('login')
            pwd = request.form.get('password')
            if not login_input or not pwd:
                flash(_('Заполните все поля.'), 'error')
                return redirect(url_for('login'))
            db = get_db()
            user = db.execute('SELECT * FROM users WHERE email = ? OR nickname = ?',
                              (login_input, login_input)).fetchone()
            db.close()
            if user and check_password_hash(user['password_hash'], pwd):
                session['user_id'] = user['id']
                flash(_('Вход выполнен успешно.'), 'success')
                return redirect(url_for('index'))
            flash(_('Неверный email/ник или пароль.'), 'error')
        elif action == 'register':
            email = request.form.get('email')
            nickname = request.form.get('nickname')
            pwd = request.form.get('password')
            conf = request.form.get('confirm_password')
            if not email or not nickname or not pwd or not conf:
                flash(_('Заполните все поля.'), 'error')
                return redirect(url_for('login'))
            if not is_valid_email(email):
                flash(
                    _('Введите корректный email адрес (только домены .ru). Подробнее: https://www.consultant.ru/law/hotdocs/81325.html'),
                    'error')
                return redirect(url_for('login'))
            if pwd != conf:
                flash(_('Пароли не совпадают.'), 'error')
                return redirect(url_for('login'))
            if len(pwd) < 4:
                flash(_('Пароль не менее 4 символов.'), 'error')
                return redirect(url_for('login'))
            if len(nickname) < 3:
                flash(_('Никнейм не менее 3 символов.'), 'error')
                return redirect(url_for('login'))
            pwd_hash = generate_password_hash(pwd)
            db = get_db()
            try:
                db.execute('INSERT INTO users (email, nickname, password_hash) VALUES (?, ?, ?)',
                           (email, nickname, pwd_hash))
                db.commit()
                flash(_('Регистрация успешна. Теперь войдите.'), 'success')
            except sqlite3.IntegrityError as e:
                if 'email' in str(e):
                    flash(_('Email уже зарегистрирован.'), 'error')
                else:
                    flash(_('Никнейм уже занят.'), 'error')
            finally:
                db.close()
        return redirect(url_for('login'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash(_('Вы вышли из аккаунта.'), 'info')
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)
