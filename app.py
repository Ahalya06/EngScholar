import os
from datetime import datetime

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    jsonify,
    session
)

from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, Column, Integer, String, DateTime, text
from sqlalchemy.orm import sessionmaker, declarative_base
import redis


# =========================================================
# CREATE FLASK APP
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    'SECRET_KEY',
    'dev-key-change-in-production'
)


# =========================================================
# DATABASE SETUP
# =========================================================

DATABASE_URL = os.environ.get('POSTGRES_URL')

if not DATABASE_URL:
    # Local development
    DATABASE_URL = 'sqlite:///engscholar.db'
    print("⚠️ Using SQLite (local development)")

else:
    # Vercel / PostgreSQL
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace(
            'postgres://',
            'postgresql://',
            1
        )

    print("✅ Using PostgreSQL")


# Create database engine
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

Base = declarative_base()


# =========================================================
# USER MODEL
# =========================================================

class User(Base):
    __tablename__ = 'users'

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    name = Column(
        String(100),
        nullable=False
    )

    email = Column(
        String(100),
        unique=True,
        index=True,
        nullable=False
    )

    password_hash = Column(
        String(200),
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


# =========================================================
# REDIS SETUP
# =========================================================

redis_client = None

try:
    REDIS_URL = (
        os.environ.get('REDIS_URL')
        or os.environ.get('KV_REST_API_URL')
    )

    if REDIS_URL:
        redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True
        )

        redis_client.ping()

        print("✅ Redis connected")

except Exception as e:
    print(f"⚠️ Redis not available: {e}")


# =========================================================
# CREATE DATABASE TABLES
# =========================================================

try:
    Base.metadata.create_all(bind=engine)

    print("✅ Database tables created/verified")

except Exception as e:
    print(f"⚠️ Database init error: {e}")


# =========================================================
# HOME
# =========================================================

@app.route('/')
def home():
    return render_template('landing.html')


# =========================================================
# REGISTER
# =========================================================

@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':

        db = None

        try:
            # Get form data
            name = request.form.get(
                'name',
                ''
            ).strip()

            email = request.form.get(
                'email',
                ''
            ).strip().lower()

            password = request.form.get(
                'password',
                ''
            )

            confirm_password = request.form.get(
                'confirm_password',
                ''
            )


            # ---------------------------------------------
            # VALIDATION
            # ---------------------------------------------

            if not all([
                name,
                email,
                password,
                confirm_password
            ]):

                flash(
                    'All fields are required',
                    'danger'
                )

                return render_template(
                    'register.html'
                )


            if password != confirm_password:

                flash(
                    'Passwords do not match',
                    'danger'
                )

                return render_template(
                    'register.html'
                )


            if len(password) < 8:

                flash(
                    'Password must be at least 8 characters',
                    'danger'
                )

                return render_template(
                    'register.html'
                )


            # ---------------------------------------------
            # DATABASE
            # ---------------------------------------------

            db = SessionLocal()

            existing_user = (
                db.query(User)
                .filter_by(email=email)
                .first()
            )


            # User already exists
            if existing_user:

                flash(
                    'Email already registered. Please log in.',
                    'danger'
                )

                return render_template(
                    'register.html'
                )


            # ---------------------------------------------
            # CREATE USER
            # ---------------------------------------------

            hashed_password = generate_password_hash(
                password
            )

            new_user = User(
                name=name,
                email=email,
                password_hash=hashed_password
            )

            db.add(new_user)

            db.commit()

            db.refresh(new_user)


            # ---------------------------------------------
            # REDIS CACHE
            # ---------------------------------------------

            if redis_client:

                try:

                    redis_client.setex(
                        f"user:{email}",
                        3600,
                        str(new_user.id)
                    )

                except Exception:
                    pass


            # ---------------------------------------------
            # SUCCESS
            # ---------------------------------------------

            flash(
                'Registration successful! Please log in.',
                'success'
            )

            return redirect(
                url_for('login')
            )


        except Exception as e:

            if db:
                db.rollback()

            print(
                f"❌ Registration error: {e}"
            )

            flash(
                'Registration failed. Please try again.',
                'danger'
            )

            return render_template(
                'register.html'
            )


        finally:

            if db:
                db.close()


    return render_template(
        'register.html'
    )


# =========================================================
# LOGIN
# =========================================================

@app.route('/login', methods=['GET', 'POST'])
def login():

    # -----------------------------------------------------
    # GET
    # -----------------------------------------------------

    if request.method == 'GET':

        return render_template(
            'login.html'
        )


    # -----------------------------------------------------
    # POST
    # -----------------------------------------------------

    db = None

    try:

        # Get login form data
        email = request.form.get(
            'email',
            ''
        ).strip().lower()

        password = request.form.get(
            'password',
            ''
        )


        # ---------------------------------------------
        # VALIDATION
        # ---------------------------------------------

        if not email or not password:

            flash(
                'Email and password are required.',
                'danger'
            )

            return render_template(
                'login.html'
            )


        # ---------------------------------------------
        # FIND USER
        # ---------------------------------------------

        db = SessionLocal()

        user = (
            db.query(User)
            .filter_by(email=email)
            .first()
        )


        # ---------------------------------------------
        # CHECK USER/PASSWORD
        # ---------------------------------------------

        if not user:

            flash(
                'Invalid email or password.',
                'danger'
            )

            return render_template(
                'login.html'
            )


        if not check_password_hash(
            user.password_hash,
            password
        ):

            flash(
                'Invalid email or password.',
                'danger'
            )

            return render_template(
                'login.html'
            )


        # ---------------------------------------------
        # LOGIN SUCCESS
        # ---------------------------------------------

        session['user_id'] = user.id
        session['user_name'] = user.name
        session['user_email'] = user.email


        print(
            f"✅ User logged in: {user.email}"
        )


        # ---------------------------------------------
        # REDIRECT TO DASHBOARD
        # ---------------------------------------------

        return redirect(
            url_for('dashboard')
        )


    except Exception as e:

        print(
            f"❌ Login error: {e}"
        )

        flash(
            'Login failed. Please try again.',
            'danger'
        )

        return render_template(
            'login.html'
        )


    finally:

        if db:
            db.close()


# =========================================================
# DASHBOARD
# =========================================================

@app.route('/dashboard')
def dashboard():

    return render_template(
        'dashboard.html'
    )


# =========================================================
# SCHOLARSHIPS
# =========================================================

@app.route('/scholarships')
def scholarships():

    return render_template(
        'scholarships.html'
    )


# =========================================================
# INTERNSHIPS
# =========================================================

@app.route('/internships')
def internships():

    return render_template(
        'internships.html'
    )


# =========================================================
# NOTES
# =========================================================

@app.route('/notes')
def notes():

    return render_template(
        'notes.html'
    )


# =========================================================
# PROJECTS
# =========================================================

@app.route('/projects')
def projects():

    return render_template(
        'projects.html'
    )


# =========================================================
# COURSES
# =========================================================

@app.route('/courses')
def courses():

    return render_template(
        'courses.html'
    )


# =========================================================
# MEMES
# =========================================================

@app.route('/memes')
def memes():

    return render_template(
        'memes.html'
    )


# =========================================================
# VIEW NOTES
# =========================================================

@app.route('/view_notes')
def view_notes():

    return render_template(
        'view_notes.html'
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route('/health')
def health():

    status = {
        "status": "ok",
        "database": "❌",
        "redis": "❌"
    }


    # ---------------------------------------------
    # DATABASE CHECK
    # ---------------------------------------------

    try:

        db = SessionLocal()

        db.execute(
            text("SELECT 1")
        )

        db.close()

        status["database"] = "✅"

    except Exception as e:

        print(
            f"Database health check failed: {e}"
        )


    # ---------------------------------------------
    # REDIS CHECK
    # ---------------------------------------------

    try:

        if (
            redis_client
            and redis_client.ping()
        ):

            status["redis"] = "✅"

    except Exception:
        pass


    return jsonify(status)


# =========================================================
# TEST DATABASE
# =========================================================

@app.route('/test-db')
def test_db():

    try:

        db = SessionLocal()

        result = (
            db.execute(
                text("SELECT 1")
            )
            .scalar()
        )

        db.close()


        return jsonify({
            "status": "success",
            "database": "Connected",
            "test": result
        })


    except Exception as e:

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# =========================================================
# LOCAL DEVELOPMENT
# =========================================================

if __name__ == '__main__':

    app.run(
        debug=True
    )