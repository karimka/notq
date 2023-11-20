from flask import (
    Blueprint, flash, g, redirect, render_template, request, url_for
)
from werkzeug.exceptions import abort

from notq.auth import login_required
from notq.db import get_db
from notq.markup import make_html
from notq.data_model import *
from notq.karma import get_user_karma, get_best_users

bp = Blueprint('blog', __name__)

@bp.route('/')
def index():
    posts = get_top_posts()
    if g.user:
        upvoted, downvoted = get_user_votes_for_posts(g.user['id'])
    else:
        upvoted = downvoted = []
    return render_template('blog/index.html', posts=posts, upvoted=upvoted, downvoted=downvoted)

@bp.route('/new')
def new():
    posts = get_new_posts()
    if g.user:
        upvoted, downvoted = get_user_votes_for_posts(g.user['id'])
    else:
        upvoted = downvoted = []
    return render_template('blog/new.html', posts=posts, upvoted=upvoted, downvoted=downvoted)

def best_title(period):
    if period == "day":
        return 'за день'
    elif period == "week":
        return 'за неделю'
    elif period == "month":
        return 'за месяц'
    elif period == "year":
        return 'за год'
    elif period == "all":
        return 'за всё время'
    else:
        abort(404, f"Unknown time period {period}")

@bp.route('/best/<period>')
def best(period):
    posts = get_best_posts(period)
    if g.user:
        upvoted, downvoted = get_user_votes_for_posts(g.user['id'])
    else:
        upvoted = downvoted = []
    title = 'Лучшие записи ' + best_title(period)
    return render_template('blog/best.html', 
                           besturl=url_for('blog.best', period=period), 
                           posts=posts, 
                           upvoted=upvoted, 
                           downvoted=downvoted,
                           best_title=title)

def add_current_user(users, all_users):
    if not g.user:
        return
    for u in users:
        if g.user['username'] == u[1]:
            return
    for n in range(len(all_users)):
        if all_users[n][0] == g.user['username']:
            users.append((n+1, all_users[n][0], all_users[n][1]))
            return

@bp.route('/best/<period>/users')
def best_users(period):
    title = 'Лучшие пользователи ' + best_title(period)
    all_users = get_best_users(period)
    users = [(n+1, all_users[n][0], all_users[n][1]) for n in range(min(50, len(all_users)))]
    add_current_user(users)
    return render_template('blog/best_users.html',
                           besturl=url_for('blog.best', period=period),
                           besttype='users',
                           users=users,
                           best_title=title)

@bp.route('/best/<period>/comments')
def best_comments(period):
    title = 'Лучшие комментарии ' + best_title(period)
    return render_template('blog/best_comments.html',
                           besturl=url_for('blog.best', period=period),
                           besttype='comments',
                           best_title=title)

@bp.route('/u/<username>')
def userpage(username):
    posts = get_user_posts(username)
    if g.user:
        upvoted, downvoted = get_user_votes_for_posts(g.user['id'])
    else:
        upvoted = downvoted = []
    created, nposts, ncomments = get_user_stats(username)
    if not created:
        abort(404, f"User {username} doesn't exist.") 
    user = {
        'created': created,
        'karma': get_user_karma(username),
        'nposts': nposts,
        'ncomments': ncomments,
        'about': get_about_post(username)['rendered']
    }
    return render_template('blog/userpage.html', name=username, posts=posts, upvoted=upvoted, downvoted=downvoted, user=user)

@bp.route('/<int:id>')
def one_post(id):
    posts = get_posts_by_id(id)
    if g.user:
        upvoted, downvoted = get_user_votes_for_posts(g.user['id'])
        cupvoted, cdownvoted = get_user_votes_for_comments(g.user['id'], id)
    else:
        upvoted = downvoted = []
        cupvoted = cdownvoted = []
    return render_template('blog/one_post.html', posts=posts, 
                            upvoted=upvoted, downvoted=downvoted,
                            cupvoted=cupvoted, cdownvoted=cdownvoted)

def check_post(title, body):
    if not title:
        return 'Нужен заголовок'
    if not body:
        return 'Нужно что-нибудь написать'
    return None

@bp.route('/create', methods=('GET', 'POST'))
@login_required
def create():
    if request.method == 'POST':
        title = request.form['title']
        body = request.form['body']
        error = check_post(title, body)

        if error is not None:
            flash(error)
        else:
            rendered = make_html(body)
            author_id = g.user['id']
            db = get_db()
            db.execute(
                'INSERT INTO post (title, body, rendered, author_id)'
                ' VALUES (?, ?, ?, ?)',
                (title, body, rendered, author_id)
            )
            db.commit()
            # upvote just created post
            post = db.execute('SELECT id FROM post WHERE author_id = ? ORDER BY created DESC LIMIT 1', (author_id,)).fetchone()
            if post:
                db.execute(
                    'INSERT INTO vote (user_id, post_id, vote)'
                    ' VALUES (?, ?, 1)',
                    (author_id, post['id'])
                )
                db.commit()
                return redirect(url_for('blog.one_post', id=post['id']))
            else:
                return redirect(url_for('blog.index'))

    return render_template('blog/create.html')

def get_post_to_update(id):
    post = get_db().execute(
        'SELECT p.id, title, body, p.created, author_id, username'
        ' FROM post p JOIN user u ON p.author_id = u.id'
        ' WHERE p.id = ?',
        (id,)
    ).fetchone()

    if post is None:
        abort(404, f"Post id {id} doesn't exist.")

    if post['author_id'] != g.user['id']:
        abort(403)

    return post

@bp.route('/about', methods=('GET', 'POST'))
@login_required
def about():
    if request.method == 'POST':
        title = "💬 О себе"
        body = request.form['body']
        error = check_post(title, body)

        if error is not None:
            flash(error)
        else:
            rendered = make_html(body)
            author_id = g.user['id']
            db = get_db()
            if not g.user['about_post_id']:
                # create a new post
                db.execute(
                    'INSERT INTO post (title, body, rendered, author_id, show_in_feed)'
                    ' VALUES (?, ?, ?, ?, ?)',
                    (title, body, rendered, author_id, False)
                )
                # set this post as an "about" post
                post = db.execute('SELECT id FROM post WHERE author_id = ? ORDER BY created DESC LIMIT 1', (author_id,)).fetchone()
                if post:
                    db.execute(
                        'UPDATE user SET about_post_id = ? WHERE id = ?',
                        (post['id'], g.user['id'])
                    )
                    db.commit()
            else:
                # update an old post
                db.execute('UPDATE post SET body = ?, rendered = ? WHERE id = ?', (body, rendered, g.user['about_post_id']))
                db.commit()
            return redirect(url_for('blog.userpage', username=g.user['username']))

    username = None
    if g.user:
        username = g.user['username']
    return render_template('blog/about.html', post=get_about_post(username))

@bp.route('/<int:id>/update', methods=('GET', 'POST'))
@login_required
def update(id):
    post = get_post_to_update(id)

    if request.method == 'POST':
        title = request.form['title']
        body = request.form['body']
        error = check_post(title, body)

        if error is not None:
            flash(error)
        else:
            rendered = make_html(body)
            db = get_db()
            db.execute(
                'UPDATE post SET title = ?, body = ?, rendered = ?'
                ' WHERE id = ?',
                (title, body, rendered, id)
            )
            db.commit()
            return redirect(url_for('blog.one_post', id=id))

    return render_template('blog/update.html', post=post)

@bp.route('/<int:id>/delete', methods=('POST',))
@login_required
def delete(id):
    get_post_to_update(id)
    db = get_db()
    db.execute('DELETE FROM post WHERE id = ?', (id,))
    db.commit()
    return redirect(url_for('blog.index'))

@bp.route('/<int:id>/vote/<int:vote>', methods=('POST',))
@login_required
def vote(id, vote):
    if vote == 0 or vote == 1 or vote == 2:
        db = get_db()
        db.execute(
            'INSERT INTO vote(user_id,post_id,vote) VALUES(?,?,?) ON CONFLICT(user_id,post_id) DO UPDATE SET vote=excluded.vote',
            (g.user['id'], id, vote-1)
        )
        db.commit()
    return "1"

@bp.route('/<int:post_id>/votec/<int:comment_id>/<int:vote>', methods=('POST',))
@login_required
def voteс(post_id, comment_id, vote):
    if vote == 0 or vote == 1 or vote == 2:
        db = get_db()
        db.execute(
            'INSERT INTO commentvote(user_id,post_id,comment_id,vote) VALUES(?,?,?,?)'
            'ON CONFLICT(user_id,post_id,comment_id) DO UPDATE SET vote=excluded.vote',
            (g.user['id'], post_id, comment_id, vote-1)
        )
        db.commit()
    return "1"

def check_comment(thing, text):
    if not thing:
        return 'Что-то сломалось или вы делаете что-то странное'
    if not text:
        return 'Нужно что-нибудь написать'
    return None

@bp.route('/addcomment', methods=('POST',))
@login_required
def addcomment():
    post_id = request.form['thing']
    text = request.form['text']
    if 'parent' in request.form:
        parent_id = request.form['parent']
    else:
        parent_id = None
    error = check_comment(post_id, text)

    if error is not None:
        flash(error)
    else:
        rendered = make_html(text)
        author_id = g.user['id']
        add_comment(text, rendered, author_id, post_id, parent_id)
        if parent_id:
            anchor = "#answer" + str(parent_id)
        else:
            anchor = "#sendanswer"

        # upvote just created comment
        db = get_db()
        comment = db.execute('SELECT id FROM comment WHERE author_id = ? ORDER BY created DESC LIMIT 1', (author_id,)).fetchone()
        if comment:
            db.execute(
                'INSERT INTO commentvote (user_id, post_id, comment_id, vote)'
                ' VALUES (?, ?, ?, 1)',
                (author_id, post_id, comment['id'])
            )
            db.commit()
            anchor = "#answer" + str(comment['id'])
        return redirect(url_for('blog.one_post', id=post_id) + anchor)
