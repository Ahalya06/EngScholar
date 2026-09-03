from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory
import os
import time
import requests
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from functools import wraps
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your_secret_key_change_this_in_production")

# --- Database configuration -------------------------------------------------
# On Vercel, the filesystem is read-only, so SQLite can't be written to.
# If a Postgres connection string is present (set automatically when you
# connect a Vercel Postgres / Neon store to the project), use that.
# Otherwise fall back to a local SQLite file for local development.
database_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if database_url:
    # SQLAlchemy 1.4+/2.x requires the "postgresql://" scheme; some
    # providers still hand out "postgres://".
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'engscholar.db')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- File storage configuration ---------------------------------------------
# Same problem as the database: Vercel's filesystem is read-only, so uploaded
# notes can't be saved to local disk in production. When a Vercel Blob store
# is connected, BLOB_READ_WRITE_TOKEN is set automatically and we upload
# there instead. Without it (e.g. running locally), we fall back to saving
# on local disk exactly like before.
UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

BLOB_READ_WRITE_TOKEN = os.environ.get("BLOB_READ_WRITE_TOKEN")
BLOB_API_BASE = "https://blob.vercel-storage.com"


def save_uploaded_note(file_storage, branch):
    """Save an uploaded note. Returns (filename, url).

    url is None when saved to local disk (dev fallback) — the app then
    serves it via the /uploads/<branch>/<filename> route as before.
    """
    filename = secure_filename(file_storage.filename)

    if BLOB_READ_WRITE_TOKEN:
        pathname = f"notes/{branch}/{int(time.time())}-{filename}"
        resp = requests.put(
            f"{BLOB_API_BASE}/{pathname}",
            data=file_storage.read(),
            headers={
                "Authorization": f"Bearer {BLOB_READ_WRITE_TOKEN}",
                "x-api-version": "7",
                "content-type": file_storage.content_type or "application/octet-stream",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return filename, resp.json()["url"]

    branch_folder = os.path.join(app.config['UPLOAD_FOLDER'], branch)
    os.makedirs(branch_folder, exist_ok=True)
    file_storage.save(os.path.join(branch_folder, filename))
    return filename, None

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<User {self.email}>'

class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(200), nullable=False)
    url = db.Column(db.String(500), nullable=True)  # Vercel Blob URL; None for local-disk fallback
    branch = db.Column(db.String(50), nullable=False)
    uploader_email = db.Column(db.String(120), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Note {self.filename}>'

class MemeComment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_name = db.Column(db.String(100), nullable=False)
    comment = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Comment by {self.user_name}>'

# Create database tables
with app.app_context():
    db.create_all()

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_email' not in session:
            flash('Please login to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validation
        if not name or not email or not password:
            flash('All fields are required!', 'error')
            return redirect(url_for('register'))
        
        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return redirect(url_for('register'))
        
        # Check if user exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already registered!', 'error')
            return redirect(url_for('register'))
        
        # Create new user
        hashed_password = generate_password_hash(password)
        new_user = User(name=name, email=email, password=hashed_password)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('Registration failed. Please try again.', 'error')
            return redirect(url_for('register'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            session['user_email'] = user.email
            session['user_name'] = user.name
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password!', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('landing'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user_name=session.get('user_name'))

@app.route('/scholarships')
@login_required
def scholarships():
    return render_template('scholarships.html')

@app.route('/internships')
@login_required
def internships():
    return render_template('internships.html')

@app.route('/Courses')
@login_required
def courses():
    return render_template('Courses.html')

@app.route('/projects')
@login_required
def projects():
    return render_template('projects.html')

@app.route('/notes', methods=['GET', 'POST'])
@login_required
def notes():
    if request.method == 'POST':
        if 'note_file' in request.files:
            file = request.files['note_file']
            branch = request.form.get('branch')
            
            if file.filename != "" and branch:
                try:
                    filename, blob_url = save_uploaded_note(file, branch)
                except Exception:
                    flash('Note upload failed. Please try again.', 'error')
                    return redirect(url_for('notes'))

                # Save to database
                new_note = Note(
                    filename=filename,
                    url=blob_url,
                    branch=branch,
                    uploader_email=session.get('user_email')
                )
                db.session.add(new_note)
                db.session.commit()
                
                flash('Note uploaded successfully!', 'success')
                return redirect(url_for('notes'))
    
    return render_template('notes.html')

@app.route("/view-notes")
@login_required
def view_notes():
    # Get all notes from database
    notes = Note.query.order_by(Note.uploaded_at.desc()).all()
    
    # Organize by branch
    notes_by_branch = {}
    for note in notes:
        if note.branch not in notes_by_branch:
            notes_by_branch[note.branch] = []
        notes_by_branch[note.branch].append(note)
    
    return render_template("view_notes.html", notes_by_branch=notes_by_branch)

@app.route('/uploads/<branch>/<filename>')
@login_required
def uploaded_file(branch, filename):
    return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], branch), filename)

@app.route('/memes', methods=['GET', 'POST'])
@login_required
def memes():
    if request.method == 'POST':
        comment = request.form.get('comment')
        if comment:
            new_comment = MemeComment(
                user_name=session.get('user_name'),
                comment=comment
            )
            db.session.add(new_comment)
            db.session.commit()
            flash('Comment added!', 'success')
        return redirect(url_for('memes'))
    
    # Get all comments
    comments = MemeComment.query.order_by(MemeComment.created_at.desc()).all()
    comments_list = [{'user': c.user_name, 'comment': c.comment} for c in comments]
    
    return render_template('memes.html', comments=comments_list)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)