import os
import io
from datetime import datetime

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    jsonify,
    session,
    send_file
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from werkzeug.utils import secure_filename

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    DateTime,
    LargeBinary,
    text
)

from sqlalchemy.orm import (
    sessionmaker,
    declarative_base
)


# =========================================================
# FLASK APP
# =========================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "dev-key-change-in-production"
)

# Maximum total upload request size
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


# =========================================================
# DATABASE SETUP
# =========================================================

DATABASE_URL = os.environ.get("POSTGRES_URL")

if not DATABASE_URL:

    DATABASE_URL = "sqlite:///engscholar.db"

    print("⚠️ Using SQLite (local development)")

else:

    if DATABASE_URL.startswith("postgres://"):

        DATABASE_URL = DATABASE_URL.replace(
            "postgres://",
            "postgresql://",
            1
        )

    print("✅ Using PostgreSQL")


# =========================================================
# DATABASE ENGINE
# =========================================================

if DATABASE_URL.startswith("sqlite"):

    engine = create_engine(
        DATABASE_URL,
        connect_args={
            "check_same_thread": False
        }
    )

else:

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

    __tablename__ = "users"

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
# NOTES MODEL
# =========================================================
#
# IMPORTANT:
# We use "uploaded_notes" instead of "notes"
# to avoid conflicts with your previous database table.
#
# =========================================================

class Note(Base):

    __tablename__ = "uploaded_notes"

    id = Column(
        Integer,
        primary_key=True,
        index=True
    )

    branch = Column(
        String(20),
        nullable=False,
        index=True
    )

    filename = Column(
        String(255),
        nullable=False
    )

    file_data = Column(
        LargeBinary,
        nullable=False
    )

    uploaded_at = Column(
        DateTime,
        default=datetime.utcnow
    )


# =========================================================
# CREATE TABLES
# =========================================================

try:

    Base.metadata.create_all(
        bind=engine
    )

    print(
        "✅ Database tables created/verified"
    )

except Exception as e:

    print(
        f"⚠️ Database initialization error: {e}"
    )


# =========================================================
# REDIS - OPTIONAL
# =========================================================

redis_client = None

try:

    import redis

    REDIS_URL = os.environ.get(
        "REDIS_URL"
    )

    if REDIS_URL:

        redis_client = redis.from_url(
            REDIS_URL,
            decode_responses=True
        )

        redis_client.ping()

        print(
            "✅ Redis connected"
        )

    else:

        print(
            "⚠️ Redis not configured"
        )

except Exception as e:

    print(
        f"⚠️ Redis not available: {e}"
    )


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return render_template(
        "landing.html"
    )


# =========================================================
# REGISTER
# =========================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        db = None

        try:

            name = request.form.get(
                "name",
                ""
            ).strip()

            email = request.form.get(
                "email",
                ""
            ).strip().lower()

            password = request.form.get(
                "password",
                ""
            )

            confirm_password = request.form.get(
                "confirm_password",
                ""
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
                    "All fields are required.",
                    "danger"
                )

                return render_template(
                    "register.html"
                )


            if password != confirm_password:

                flash(
                    "Passwords do not match.",
                    "danger"
                )

                return render_template(
                    "register.html"
                )


            if len(password) < 8:

                flash(
                    "Password must be at least 8 characters.",
                    "danger"
                )

                return render_template(
                    "register.html"
                )


            # ---------------------------------------------
            # DATABASE
            # ---------------------------------------------

            db = SessionLocal()

            existing_user = (
                db.query(User)
                .filter(
                    User.email == email
                )
                .first()
            )


            if existing_user:

                flash(
                    "Email already registered. Please log in.",
                    "danger"
                )

                return render_template(
                    "register.html"
                )


            # ---------------------------------------------
            # CREATE USER
            # ---------------------------------------------

            hashed_password = (
                generate_password_hash(
                    password
                )
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

                except Exception as redis_error:

                    print(
                        f"Redis cache error: {redis_error}"
                    )


            print(
                f"✅ User registered: {email}"
            )


            flash(
                "Registration successful! Please log in.",
                "success"
            )

            return redirect(
                url_for("login")
            )


        except Exception as e:

            if db:

                db.rollback()

            print(
                f"❌ Registration error: {e}"
            )

            flash(
                "Registration failed. Please try again.",
                "danger"
            )

            return render_template(
                "register.html"
            )


        finally:

            if db:

                db.close()


    return render_template(
        "register.html"
    )


# =========================================================
# LOGIN
# =========================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        db = None

        try:

            email = request.form.get(
                "email",
                ""
            ).strip().lower()

            password = request.form.get(
                "password",
                ""
            )


            if not email or not password:

                flash(
                    "Please enter your email and password.",
                    "danger"
                )

                return render_template(
                    "login.html"
                )


            db = SessionLocal()

            user = (
                db.query(User)
                .filter(
                    User.email == email
                )
                .first()
            )


            if not user:

                flash(
                    "Invalid email or password.",
                    "danger"
                )

                return render_template(
                    "login.html"
                )


            if not check_password_hash(
                user.password_hash,
                password
            ):

                flash(
                    "Invalid email or password.",
                    "danger"
                )

                return render_template(
                    "login.html"
                )


            # ---------------------------------------------
            # LOGIN SUCCESS
            # ---------------------------------------------

            session["user_id"] = user.id
            session["user_name"] = user.name
            session["user_email"] = user.email


            print(
                f"✅ Login successful: {email}"
            )


            return redirect(
                url_for("dashboard")
            )


        except Exception as e:

            print(
                f"❌ Login error: {e}"
            )

            flash(
                "Login failed. Please try again.",
                "danger"
            )

            return render_template(
                "login.html"
            )


        finally:

            if db:

                db.close()


    return render_template(
        "login.html"
    )


# =========================================================
# LOGOUT
# =========================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out.",
        "success"
    )

    return redirect(
        url_for("home")
    )


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():

    return render_template(
        "dashboard.html"
    )


# =========================================================
# SCHOLARSHIPS
# =========================================================

@app.route("/scholarships")
def scholarships():

    return render_template(
        "scholarships.html"
    )


# =========================================================
# INTERNSHIPS
# =========================================================

@app.route("/internships")
def internships():

    return render_template(
        "internships.html"
    )


# =========================================================
# PROJECTS
# =========================================================

@app.route("/projects")
def projects():

    return render_template(
        "projects.html"
    )


# =========================================================
# COURSES
# =========================================================

@app.route("/courses")
def courses():

    return render_template(
        "courses.html"
    )


# =========================================================
# MEMES
# =========================================================

@app.route("/memes")
def memes():

    return render_template(
        "memes.html"
    )


# =========================================================
# NOTES
# =========================================================

@app.route(
    "/notes",
    methods=["GET", "POST"]
)
def notes():

    # =====================================================
    # GET
    # =====================================================

    if request.method == "GET":

        return render_template(
            "notes.html"
        )


    # =====================================================
    # POST - UPLOAD NOTE
    # =====================================================

    db = None

    try:

        # ---------------------------------------------
        # GET BRANCH
        # ---------------------------------------------

        branch = request.form.get(
            "branch",
            ""
        ).strip()


        # ---------------------------------------------
        # GET FILE
        # ---------------------------------------------

        note_file = request.files.get(
            "note_file"
        )


        # ---------------------------------------------
        # VALID BRANCHES
        # ---------------------------------------------

        allowed_branches = {
            "CSE",
            "ECE",
            "ME",
            "CE",
            "EEE",
            "IT"
        }


        if branch not in allowed_branches:

            flash(
                "Please select a valid branch.",
                "danger"
            )

            return redirect(
                url_for("notes")
            )


        # ---------------------------------------------
        # FILE EXISTS?
        # ---------------------------------------------

        if note_file is None:

            flash(
                "Please select a file.",
                "danger"
            )

            return redirect(
                url_for("notes")
            )


        # ---------------------------------------------
        # FILE NAME
        # ---------------------------------------------

        if not note_file.filename:

            flash(
                "Please select a file.",
                "danger"
            )

            return redirect(
                url_for("notes")
            )


        filename = secure_filename(
            note_file.filename
        )


        if not filename:

            flash(
                "Invalid file name.",
                "danger"
            )

            return redirect(
                url_for("notes")
            )


        # ---------------------------------------------
        # CHECK EXTENSION
        # ---------------------------------------------

        allowed_extensions = {
            "pdf",
            "doc",
            "docx",
            "ppt",
            "pptx"
        }


        if "." not in filename:

            flash(
                "Invalid file type.",
                "danger"
            )

            return redirect(
                url_for("notes")
            )


        extension = (
            filename
            .rsplit(".", 1)[1]
            .lower()
        )


        if extension not in allowed_extensions:

            flash(
                "Only PDF, DOC, DOCX, PPT and PPTX files are allowed.",
                "danger"
            )

            return redirect(
                url_for("notes")
            )


        # ---------------------------------------------
        # READ FILE
        # ---------------------------------------------

        file_data = note_file.read()


        # ---------------------------------------------
        # CHECK EMPTY FILE
        # ---------------------------------------------

        if not file_data:

            flash(
                "The uploaded file is empty.",
                "danger"
            )

            return redirect(
                url_for("notes")
            )


        # ---------------------------------------------
        # MAX FILE SIZE = 4MB
        # ---------------------------------------------

        max_file_size = 10 * 1024 * 1024


        if len(file_data) > max_file_size:

            flash(
                "File is too large. Maximum size is 10MB.",
                "danger"
            )

            return redirect(
                url_for("notes")
            )


        # ---------------------------------------------
        # SAVE TO DATABASE
        # ---------------------------------------------

        db = SessionLocal()


        new_note = Note(
            branch=branch,
            filename=filename,
            file_data=file_data,
            uploaded_at=datetime.utcnow()
        )


        db.add(new_note)

        db.commit()

        db.refresh(new_note)


        print(
            f"✅ Note uploaded successfully: "
            f"{filename} ({branch})"
        )


        # ---------------------------------------------
        # SUCCESS
        # ---------------------------------------------

        flash(
            "Note uploaded successfully!",
            "success"
        )


        return redirect(
            url_for("view_notes")
        )


    except Exception as e:

        if db:

            db.rollback()


        print(
            "❌ NOTE UPLOAD ERROR"
        )

        print(
            repr(e)
        )


        flash(
            "Note upload failed. Please try again.",
            "danger"
        )


        return redirect(
            url_for("notes")
        )


    finally:

        if db:

            db.close()


# =========================================================
# VIEW NOTES
# =========================================================

@app.route("/view_notes")
def view_notes():

    db = None

    try:

        db = SessionLocal()


        all_notes = (
            db.query(Note)
            .order_by(
                Note.uploaded_at.desc()
            )
            .all()
        )


        notes_by_branch = {}


        for note in all_notes:

            if note.branch not in notes_by_branch:

                notes_by_branch[
                    note.branch
                ] = []


            notes_by_branch[
                note.branch
            ].append(note)


        return render_template(
            "view_notes.html",
            notes_by_branch=notes_by_branch
        )


    except Exception as e:

        print(
            f"❌ View notes error: {e}"
        )


        flash(
            "Unable to load notes.",
            "danger"
        )


        return render_template(
            "view_notes.html",
            notes_by_branch={}
        )


    finally:

        if db:

            db.close()


# =========================================================
# SUPPORT /VIEW-NOTES TOO
# =========================================================

@app.route("/view-notes")
def view_notes_hyphen():

    return redirect(
        url_for("view_notes")
    )


# =========================================================
# DOWNLOAD NOTE
# =========================================================

@app.route(
    "/uploaded_file/<int:note_id>"
)
def uploaded_file(note_id):

    db = None

    try:

        db = SessionLocal()


        note = (
            db.query(Note)
            .filter(
                Note.id == note_id
            )
            .first()
        )


        if note is None:

            flash(
                "Note not found.",
                "danger"
            )

            return redirect(
                url_for("view_notes")
            )


        return send_file(
            io.BytesIO(note.file_data),
            download_name=note.filename,
            as_attachment=True
        )


    except Exception as e:

        print(
            f"❌ Download error: {e}"
        )


        flash(
            "Unable to download the note.",
            "danger"
        )


        return redirect(
            url_for("view_notes")
        )


    finally:

        if db:

            db.close()


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    status = {
        "status": "ok",
        "database": "❌",
        "redis": "❌"
    }


    # ---------------------------------------------
    # DATABASE
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
    # REDIS
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

@app.route("/test-db")
def test_db():

    db = None

    try:

        db = SessionLocal()


        result = db.execute(
            text("SELECT 1")
        ).scalar()


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


    finally:

        if db:

            db.close()


# =========================================================
# FILE TOO LARGE
# =========================================================

@app.errorhandler(413)
def file_too_large(error):

    flash(
        "File is too large. Maximum upload size is 10MB.",
        "danger"
    )

    return redirect(
        url_for("notes")
    )

# =========================================================
# LOCAL DEVELOPMENT
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )